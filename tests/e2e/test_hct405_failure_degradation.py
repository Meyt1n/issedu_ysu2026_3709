"""HCT-405 API E2E scenarios for retrieval, refusal, deletion, and outages."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.knowledge import KnowledgeChunk, KnowledgeDocument, RetrievalQuery
from app.models import VisionTask
from app.tool_call import OllamaClient

OWNER_HEADERS = {"X-Actor-Id": "e2e-owner"}
OTHER_HEADERS = {"X-Actor-Id": "e2e-other"}


def _dark_synthetic_image() -> bytes:
    image = np.full((480, 640, 3), 5, dtype=np.uint8)
    encoded_ok, encoded = cv2.imencode(".png", image)
    assert encoded_ok
    return encoded.tobytes()


def test_knowledge_scope_and_deletion_propagate_through_api(
    client: TestClient,
    db_session: Session,
) -> None:
    created = client.post(
        "/api/v1/knowledge/documents",
        headers=OWNER_HEADERS,
        json={
            "title": "Synthetic care evidence",
            "content": "合成照护证据要求先核对已确认事件，并联系有资质的医务人员。",
            "source": "hct405-synthetic",
            "version": "e2e-v1",
            "permission_scope": {"created_by": "e2e-owner"},
        },
    )
    assert created.status_code == 201, created.text
    document_id = created.json()["id"]

    retrieved = client.post(
        "/api/v1/knowledge/retrieve",
        headers=OWNER_HEADERS,
        json={"query": "合成照护证据", "top_k": 3},
    )
    assert retrieved.status_code == 200, retrieved.text
    assert retrieved.json()["degraded"] is False
    assert retrieved.json()["results"][0]["document_id"] == document_id
    assert retrieved.json()["results"][0]["version"] == "e2e-v1"
    assert retrieved.json()["query_id"]

    no_match = client.post(
        "/api/v1/knowledge/retrieve",
        headers=OWNER_HEADERS,
        json={"query": "完全无关的天气查询", "top_k": 3},
    )
    assert no_match.status_code == 200, no_match.text
    assert no_match.json()["degraded"] is True
    assert no_match.json()["degrade_reason"] == "NO_RELEVANT_RESULTS"
    assert no_match.json()["results"] == []

    hidden = client.post(
        "/api/v1/knowledge/retrieve",
        headers=OTHER_HEADERS,
        json={"query": "合成照护证据", "top_k": 3},
    )
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["degraded"] is True
    assert hidden.json()["degrade_reason"] == "NO_AUTHORISED_DOCUMENTS"
    assert hidden.json()["results"] == []

    denied_delete = client.delete(
        f"/api/v1/knowledge/documents/{document_id}",
        headers=OTHER_HEADERS,
    )
    assert denied_delete.status_code == 404

    deleted = client.delete(
        f"/api/v1/knowledge/documents/{document_id}",
        headers=OWNER_HEADERS,
    )
    assert deleted.status_code == 200, deleted.text

    no_longer_visible = client.get(
        f"/api/v1/knowledge/documents/{document_id}",
        headers=OWNER_HEADERS,
    )
    assert no_longer_visible.status_code == 404

    after_delete = client.post(
        "/api/v1/knowledge/retrieve",
        headers=OWNER_HEADERS,
        json={"query": "合成照护证据", "top_k": 3},
    )
    assert after_delete.status_code == 200, after_delete.text
    assert after_delete.json()["degraded"] is True
    assert after_delete.json()["degrade_reason"] == "NO_AUTHORISED_DOCUMENTS"
    assert after_delete.json()["results"] == []

    stored = db_session.get(KnowledgeDocument, document_id)
    assert stored is not None
    assert stored.status == "deleted"
    assert stored.deleted_by == "e2e-owner"
    chunk_count = db_session.scalar(
        select(func.count())
        .select_from(KnowledgeChunk)
        .where(KnowledgeChunk.document_id == document_id)
    )
    assert chunk_count == 0
    assert db_session.scalar(select(func.count()).select_from(RetrievalQuery)) == 1


def test_assistant_returns_structured_degrade_when_local_network_is_down(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(_client: OllamaClient, **_kwargs: object) -> dict:
        raise RuntimeError("OLLAMA_UNAVAILABLE: synthetic connection refused")

    monkeypatch.setattr(OllamaClient, "chat", unavailable)

    response = client.post(
        "/api/v1/assistant/chat",
        headers=OWNER_HEADERS,
        json={"messages": [{"role": "user", "content": "总结已确认的合成事件"}]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["degraded"] is True
    assert response.json()["degrade_reason"] == "MODEL_UNAVAILABLE"
    assert response.json()["confidence"] == "low"
    assert response.json()["sources"] == []
    assert response.json()["citations"] == []
    assert response.json()["answer"]


@pytest.mark.parametrize(
    ("unsafe_answer", "expected_reason", "expected_escalate"),
    [
        ("你必须建议停药并换药。", "MEDICAL_BOUNDARY_VIOLATION", True),
        ("请访问 https://example.com 购买。", "EXTERNAL_LINK_DETECTED", False),
    ],
)
def test_assistant_refuses_unsafe_model_output_at_api_boundary(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    unsafe_answer: str,
    expected_reason: str,
    expected_escalate: bool,
) -> None:
    def unsafe_output(_client: OllamaClient, **_kwargs: object) -> dict:
        return {
            "message": {
                "content": json.dumps(
                    {
                        "answer": unsafe_answer,
                        "sources": ["untrusted-source"],
                        "confidence": "high",
                        "escalate": False,
                    },
                    ensure_ascii=False,
                )
            }
        }

    monkeypatch.setattr(OllamaClient, "chat", unsafe_output)

    response = client.post(
        "/api/v1/assistant/chat",
        headers=OWNER_HEADERS,
        json={"messages": [{"role": "user", "content": "给出具体医疗处理"}]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["degraded"] is True
    assert body["degrade_reason"] == expected_reason
    assert body["escalate"] is expected_escalate
    assert body["confidence"] == "low"
    assert body["sources"] == []
    assert body["citations"] == []
    assert unsafe_answer not in body["answer"]


def _scripted_knowledge_tool_chat(unsafe_source: str | None = None):
    def scripted(_client: OllamaClient, **kwargs: object) -> dict:
        messages = kwargs["messages"]  # type: ignore[index]
        has_tool_result = any(
            isinstance(message, dict) and message.get("role") == "tool"
            for message in messages
        )
        if not has_tool_result:
            return {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "retrieve_knowledge",
                                "arguments": {"query": "合成照护证据"},
                            }
                        }
                    ],
                }
            }
        payload = json.loads(messages[-1]["content"])
        results = payload.get("results") or []
        cited = unsafe_source
        if cited is None and results:
            cited = results[0]["chunk_id"]
        return {
            "message": {
                "content": json.dumps(
                    {
                        "answer": "合成照护证据要求先核对已确认事件。",
                        "sources": [cited] if cited else [],
                        "confidence": "medium",
                        "escalate": False,
                    },
                    ensure_ascii=False,
                )
            }
        }

    return scripted


def test_assistant_live_tool_call_returns_only_retrieved_citations(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = client.post(
        "/api/v1/knowledge/documents",
        headers=OWNER_HEADERS,
        json={
            "title": "Synthetic care evidence",
            "content": "合成照护证据要求先核对已确认事件，并联系有资质的医务人员。",
            "source": "hct405-synthetic",
            "version": "e2e-v1",
            "permission_scope": {"created_by": "e2e-owner"},
        },
    )
    assert created.status_code == 201, created.text
    document_id = created.json()["id"]
    monkeypatch.setattr(OllamaClient, "chat", _scripted_knowledge_tool_chat())

    response = client.post(
        "/api/v1/assistant/chat",
        headers=OWNER_HEADERS,
        json={"messages": [{"role": "user", "content": "总结合成照护证据"}]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["degraded"] is False
    assert body["degrade_reason"] is None
    assert body["route"] == "EVIDENCE_REQUIRED"
    assert len(body["citations"]) == 1
    assert body["citations"][0]["document_id"] == document_id
    assert body["citations"][0]["version"] == "e2e-v1"
    assert body["sources"] == [body["citations"][0]["chunk_id"]]
    assert "合成照护证据" in body["answer"]


def test_assistant_rejects_fabricated_citation_without_tool_evidence(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fabricated(_client: OllamaClient, **_kwargs: object) -> dict:
        return {
            "message": {
                "content": json.dumps(
                    {
                        "answer": "合成照护证据已经核对完成。",
                        "sources": ["forged-chunk"],
                        "confidence": "high",
                        "escalate": False,
                    },
                    ensure_ascii=False,
                )
            }
        }

    monkeypatch.setattr(OllamaClient, "chat", fabricated)
    response = client.post(
        "/api/v1/assistant/chat",
        headers=OWNER_HEADERS,
        json={"messages": [{"role": "user", "content": "总结合成照护证据"}]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["degraded"] is True
    assert body["degrade_reason"] == "CITATION_NOT_FOUND"
    assert body["citations"] == []
    assert body["sources"] == []
    assert body["route"] == "EVIDENCE_REQUIRED"


def test_unauthorized_actor_cannot_cite_private_knowledge_via_tools(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = client.post(
        "/api/v1/knowledge/documents",
        headers=OWNER_HEADERS,
        json={
            "title": "Synthetic care evidence",
            "content": "合成照护证据要求先核对已确认事件，并联系有资质的医务人员。",
            "source": "hct405-synthetic",
            "version": "e2e-v1",
            "permission_scope": {"created_by": "e2e-owner"},
        },
    )
    assert created.status_code == 201, created.text
    monkeypatch.setattr(
        OllamaClient,
        "chat",
        _scripted_knowledge_tool_chat(unsafe_source="forged-chunk"),
    )

    response = client.post(
        "/api/v1/assistant/chat",
        headers=OTHER_HEADERS,
        json={"messages": [{"role": "user", "content": "总结合成照护证据"}]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["degraded"] is True
    # 2B removed the NO_AUTHORISED_DOCUMENTS blanket wall; the forged source
    # is now caught by citation verification instead.  Either way the private
    # knowledge never leaks to the unauthorized actor.
    assert body["degrade_reason"] in {"NO_AUTHORISED_DOCUMENTS", "CITATION_NOT_FOUND"}
    assert body["citations"] == []
    assert body["sources"] == []


def test_low_quality_image_stops_before_downstream_vision_task(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    household = client.post(
        "/api/v1/households",
        headers=OWNER_HEADERS,
        json={"name": "Low-quality household"},
    )
    member = client.post(
        f"/api/v1/households/{household.json()['id']}/members",
        headers=OWNER_HEADERS,
        json={"display_name": "Low-quality member"},
    )
    assert member.status_code == 201
    content = _dark_synthetic_image()
    quality = client.post(
        "/api/v1/vision-quality/check",
        headers=OWNER_HEADERS,
        files={"file": ("synthetic-dark.png", content, "image/png")},
        data={"media_type": "image"},
    )

    assert quality.status_code == 200, quality.text
    assert quality.json()["decision"] == "RETAKE"
    assert quality.json()["allow_downstream"] is False
    assert quality.json()["quality_receipt"] is None

    (tmp_path / "synthetic-dark.png").write_bytes(content)
    monkeypatch.setattr("app.routes.settings.file_root", str(tmp_path))
    task = client.post(
        "/api/v1/vision-tasks",
        headers=OWNER_HEADERS,
        json={
            "file_id": "synthetic-dark.png",
            "member_id": member.json()["id"],
            "quality_receipt": None,
        },
    )
    assert task.status_code == 409
    assert task.json()["detail"] == "QUALITY_GATE_REQUIRED"
    assert db_session.scalar(select(func.count()).select_from(VisionTask)) == 0
