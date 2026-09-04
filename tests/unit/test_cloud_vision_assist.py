from __future__ import annotations

import json

from ai.vision.evidence_pipeline import (
    EvidencePipelineRequest,
    FieldProposal,
    LocalMasterData,
    MasterDataRecord,
    OCRToken,
    process_evidence,
)

from app import cloud_vision_assist


class _FakeCloudClient:
    vision_enabled = True

    def __init__(self, content: dict) -> None:
        self.content = content

    def chat(self, **_kwargs):  # noqa: ANN003 - test double for provider adapter
        return {"message": {"content": json.dumps(self.content, ensure_ascii=False)}}


def _evidence_and_master():
    request = EvidencePipelineRequest(
        ocr_tokens=[
            OCRToken(
                id="ocr-name",
                raw_value="阿莫西林胶囊",
                confidence=0.95,
                engine_version="ocr-v1",
            ),
            OCRToken(
                id="ocr-spec",
                raw_value="0.25g×24粒",
                confidence=0.93,
                engine_version="ocr-v1",
            ),
        ],
        field_proposals=[
            FieldProposal(
                field_name="drug_name",
                raw_value="阿莫西林胶囊",
                evidence_ids=["ocr-name"],
                confidence=0.9,
                parser_version="parser-v1",
            ),
            FieldProposal(
                field_name="specification",
                raw_value="0.25g×24粒",
                evidence_ids=["ocr-spec"],
                confidence=0.9,
                parser_version="parser-v1",
            ),
        ],
    )
    master = LocalMasterData(
        version="master-v1",
        available=True,
        records=[
            MasterDataRecord(
                record_id="amox-1",
                name_aliases=["阿莫西林胶囊"],
                specification="0.25g×24粒",
                active_ingredients=["阿莫西林"],
            )
        ],
    )
    return process_evidence(request, master_data=master), master


def test_cloud_assist_is_grounded_and_completes_approved_ingredients(monkeypatch) -> None:
    evidence, master = _evidence_and_master()
    monkeypatch.setattr(cloud_vision_assist, "cloud_backend_enabled", lambda: True)
    monkeypatch.setattr(
        cloud_vision_assist,
        "build_cloud_client",
        lambda: _FakeCloudClient(
            {
                "selected_candidate_id": "amox-1",
                "drug_name": {
                    "value": "阿莫西林胶囊",
                    "source": "ocr",
                    "evidence_ids": ["ocr-name"],
                },
                "specification": {
                    "value": "0.25g×24粒",
                    "source": "ocr",
                    "evidence_ids": ["ocr-spec"],
                },
                "active_ingredients": [{"value": "不在主数据中的成分"}],
                "confidence": 0.88,
                "rationale": "OCR 名称与本地候选一致",
            }
        ),
    )

    result = cloud_vision_assist.assist_vision_evidence(evidence, master)

    assert result["status"] == "READY"
    assert result["candidate_id"] == "amox-1"
    assert result["drug_name"] == "阿莫西林胶囊"
    assert result["specification"] == "0.25g×24粒"
    assert result["active_ingredients"] == ["阿莫西林"]


def test_cloud_assist_rejects_hallucinated_field_values(monkeypatch) -> None:
    evidence, master = _evidence_and_master()
    monkeypatch.setattr(cloud_vision_assist, "cloud_backend_enabled", lambda: True)
    monkeypatch.setattr(
        cloud_vision_assist,
        "build_cloud_client",
        lambda: _FakeCloudClient(
            {
                "selected_candidate_id": "amox-1",
                "drug_name": {
                    "value": "头孢克肟",
                    "source": "ocr",
                    "evidence_ids": ["ocr-name"],
                },
                "specification": {
                    "value": "1g",
                    "source": "ocr",
                    "evidence_ids": ["ocr-spec"],
                },
                "active_ingredients": [],
                "confidence": 0.99,
            }
        ),
    )

    result = cloud_vision_assist.assist_vision_evidence(evidence, master)

    assert result["status"] == "READY"
    assert result["drug_name"] == "阿莫西林胶囊"
    assert result["specification"] == "0.25g×24粒"
    assert "drug_name:OCR_VALUE_NOT_GROUNDED" in result["warnings"]
    assert "specification:OCR_VALUE_NOT_GROUNDED" in result["warnings"]
