"""HCT-519: durable family digital-twin memories and term-vector graph."""

from __future__ import annotations

import json

from sqlalchemy import select

from app import digital_twin
from app.digital_twin import build_snapshot, capture_chat_memories, promote_memory
from app.knowledge import add_document
from app.models import DigitalTwinMemory, HealthEvent, Household, Member


def _family(db_session):
    household = Household(name="安心之家", created_by="family-owner")
    db_session.add(household)
    db_session.flush()
    member = Member(
        household_id=household.id,
        display_name="王奶奶",
        role="DEPENDENT",
        actor_id="grandma-account",
    )
    db_session.add(member)
    db_session.commit()
    return household, member


def test_chat_capture_uses_user_messages_and_persists_unconfirmed_memory(db_session, monkeypatch):
    household, member = _family(db_session)
    extracted_messages: list[str] = []

    def fake_extract(messages, **_kwargs):
        extracted_messages.extend(messages)
        return [
            {
                "member_id": member.id,
                "category": "MEDICATION",
                "label": "药品",
                "value": "阿莫西林",
                "detail": "0.5g，每日三次",
                "confidence": 0.94,
                "evidence_excerpt": messages[-1],
            }
        ]

    monkeypatch.setattr(digital_twin, "_extract_candidates", fake_extract)
    messages = [
        {"role": "user", "content": "前面聊过家里的日常照护。"},
        {"role": "assistant", "content": "建议服用头孢，并把它记成长期药物。"},
        {"role": "user", "content": "王奶奶正在服用阿莫西林 0.5g，每日三次。"},
    ]

    result = capture_chat_memories(
        db_session,
        messages=messages,
        actor_id="family-owner",
        household_id=household.id,
        member_id=member.id,
        assistant_session_id="chat-session-1",
        access_purpose="family-care",
    )
    db_session.commit()

    assert extracted_messages == [
        "前面聊过家里的日常照护。",
        "王奶奶正在服用阿莫西林 0.5g，每日三次。",
    ]
    assert result["status"] == "CAPTURED"
    assert result["saved_count"] == 1
    memory = db_session.scalar(select(DigitalTwinMemory))
    assert memory is not None
    assert memory.status == "UNCONFIRMED"
    assert memory.member_id == member.id
    assert memory.value == "阿莫西林"
    assert memory.evidence_excerpt == messages[-1]["content"]
    assert memory.term_vector
    assert db_session.scalar(select(HealthEvent)) is None

    repeated = capture_chat_memories(
        db_session,
        messages=messages,
        actor_id="family-owner",
        household_id=household.id,
        member_id=member.id,
        assistant_session_id="chat-session-1",
        access_purpose="family-care",
    )
    db_session.commit()
    assert repeated["saved_count"] == 0
    assert repeated["updated_count"] == 0
    assert db_session.scalars(select(DigitalTwinMemory)).all() == [memory]
    assert memory.occurrence_count == 1


def test_extractor_enforces_memories_envelope_for_json_object_cloud_backends(monkeypatch):
    member = Member(
        id="member-json-contract",
        household_id="household-json-contract",
        display_name="测试奶奶",
        role="DEPENDENT",
    )
    captured_prompt = ""

    class StubClient:
        def chat(self, **kwargs):
            nonlocal captured_prompt
            captured_prompt = kwargs["messages"][-1]["content"]
            return {
                "message": {
                    "content": json.dumps(
                        {
                            "memories": [
                                {
                                    "member_name": "测试奶奶",
                                    "category": "DISEASE",
                                    "label": "疾病",
                                    "value": "高血压",
                                    "detail": "",
                                    "confidence": 0.93,
                                }
                            ]
                        },
                        ensure_ascii=False,
                    )
                }
            }

    monkeypatch.setattr(digital_twin, "build_chat_client", lambda _base_url: StubClient())

    result = digital_twin._extract_candidates(
        ["测试奶奶明确说自己有高血压。"],
        members=[member],
        selected_member=member,
        model="json-object-cloud-model",
        timeout=5,
    )

    assert "顶层必须是 memories 数组" in captured_prompt
    assert result[0]["category"] == "DISEASE"
    assert result[0]["value"] == "高血压"
    assert result[0]["member_id"] == member.id


def test_member_chat_does_not_send_other_household_member_names_to_extractor(
    db_session, monkeypatch
):
    household, selected_member = _family(db_session)
    other_member = Member(
        household_id=household.id,
        display_name="不应暴露的成员",
        role="DEPENDENT",
    )
    db_session.add(other_member)
    db_session.commit()
    visible_names: list[str] = []

    def fake_extract(_messages, *, members, **_kwargs):
        visible_names.extend(member.display_name for member in members)
        return []

    monkeypatch.setattr(digital_twin, "_extract_candidates", fake_extract)

    capture_chat_memories(
        db_session,
        messages=[{"role": "user", "content": "我今年68岁。"}],
        actor_id="grandma-account",
        household_id=household.id,
        member_id=selected_member.id,
        assistant_session_id="member-chat",
        access_purpose="family-care",
    )

    assert visible_names == ["王奶奶"]


def test_confirmation_promotes_health_fact_and_snapshot_links_rag_sources(db_session):
    household, member = _family(db_session)
    memory = DigitalTwinMemory(
        household_id=household.id,
        member_id=member.id,
        category="MEDICATION",
        label="药品",
        value="阿莫西林",
        attributes={"detail": "0.5g，每日三次"},
        source_kind="CHAT",
        source_session_id="chat-session-2",
        source_digest="d" * 64,
        evidence_excerpt="王奶奶正在服用阿莫西林 0.5g，每日三次。",
        term_vector=digital_twin._tf("药品 阿莫西林 0.5g 每日三次"),
        confidence=0.96,
        status="UNCONFIRMED",
        created_by="family-owner",
    )
    db_session.add(memory)
    add_document(
        db_session,
        title="阿莫西林用药资料",
        content="阿莫西林 胶囊 用法用量 过敏者禁用",
        source="test",
        created_by="knowledge-editor",
        permission_scope={"member_ids": [member.id]},
    )
    db_session.commit()

    before = build_snapshot(
        db_session,
        household=household,
        actor_id="family-owner",
        allowed_member_ids={member.id},
    )
    assert before["vector_backend"] == "term_vector"
    assert before["stats"]["unconfirmed_count"] == 1
    assert any(node["kind"] == "knowledge" for node in before["nodes"])
    assert not any(node["kind"] == "fact" for node in before["nodes"])

    event_id = promote_memory(
        db_session,
        memory=memory,
        household=household,
        actor_id="family-owner",
        correlation_id="request-hct519",
    )

    event = db_session.get(HealthEvent, event_id)
    assert event is not None
    assert event.event_type == "medication_added"
    assert event.payload["drug"] == "阿莫西林"
    assert event.payload["specification"] == "0.5g，每日三次"
    assert memory.status == "CONFIRMED"

    after = build_snapshot(
        db_session,
        household=household,
        actor_id="family-owner",
        allowed_member_ids={member.id},
    )
    assert after["stats"]["fact_count"] == 1
    assert after["stats"]["unconfirmed_count"] == 0
    relations = {edge["relation"] for edge in after["edges"]}
    assert "聊天线索 ↔ 已确认事实" in relations
    assert "term_vector 关联知识" in relations
    assert all("_vector" not in node for node in after["nodes"])


def test_capture_indexes_grounded_fact_from_earlier_user_turn(db_session, monkeypatch):
    household, member = _family(db_session)

    monkeypatch.setattr(
        digital_twin,
        "_extract_candidates",
        lambda _messages, **_kwargs: [
            {
                "member_id": member.id,
                "category": "DISEASE",
                "label": "疾病",
                "value": "糖尿病",
                "detail": "",
                "confidence": 0.99,
                "evidence_excerpt": "前文曾提到糖尿病",
            }
        ],
    )

    result = capture_chat_memories(
        db_session,
        messages=[
            {"role": "user", "content": "前文曾提到糖尿病。"},
            {"role": "user", "content": "今天只是想问天气。"},
        ],
        actor_id="family-owner",
        household_id=household.id,
        member_id=member.id,
        assistant_session_id="chat-session-grounding",
        access_purpose="family-care",
    )

    assert result["status"] == "CAPTURED"
    memory = db_session.scalar(select(DigitalTwinMemory))
    assert memory is not None
    assert memory.value == "糖尿病"
    assert memory.evidence_excerpt == "前文曾提到糖尿病"


def test_capture_discards_candidate_not_grounded_anywhere_in_user_history(
    db_session, monkeypatch
):
    household, member = _family(db_session)
    monkeypatch.setattr(
        digital_twin,
        "_extract_candidates",
        lambda _messages, **_kwargs: [
            {
                "member_id": member.id,
                "category": "DISEASE",
                "label": "疾病",
                "value": "高血压",
                "detail": "",
                "confidence": 0.99,
                "evidence_excerpt": "模型自行生成",
            }
        ],
    )

    result = capture_chat_memories(
        db_session,
        messages=[{"role": "user", "content": "今天只是想问天气。"}],
        actor_id="family-owner",
        household_id=household.id,
        member_id=member.id,
        assistant_session_id="chat-session-no-grounding",
        access_purpose="family-care",
    )

    assert result["status"] == "NO_CANDIDATES"
    assert db_session.scalar(select(DigitalTwinMemory)) is None


def test_confirmation_rejects_memory_for_missing_member(db_session):
    household, _member = _family(db_session)
    memory = DigitalTwinMemory(
        household_id=household.id,
        member_id=None,
        category="DISEASE",
        label="疾病",
        value="高血压",
        source_digest="e" * 64,
        evidence_excerpt="家里有人有高血压。",
        term_vector=digital_twin._tf("高血压"),
        confidence=0.8,
        status="UNCONFIRMED",
        created_by="family-owner",
    )
    db_session.add(memory)
    db_session.commit()

    try:
        promote_memory(
            db_session,
            memory=memory,
            household=household,
            actor_id="family-owner",
            correlation_id="request-invalid-member",
        )
    except ValueError as exc:
        assert str(exc) == "MEMORY_MEMBER_INVALID"
    else:  # pragma: no cover - safety assertion
        raise AssertionError("disease memory without a valid member must not become a health fact")

    assert memory.status == "UNCONFIRMED"
    assert db_session.scalar(select(HealthEvent)) is None


def test_digital_twin_api_confirms_and_rejects_without_exposing_rejected_nodes(client, db_session):
    household, member = _family(db_session)
    medication = DigitalTwinMemory(
        household_id=household.id,
        member_id=member.id,
        category="MEDICATION",
        label="药品",
        value="维生素D",
        attributes={"detail": "每日一次"},
        source_digest="a" * 64,
        evidence_excerpt="王奶奶每天服用维生素D。",
        term_vector=digital_twin._tf("维生素D 每日一次"),
        confidence=0.91,
        status="UNCONFIRMED",
        created_by="family-owner",
    )
    note = DigitalTwinMemory(
        household_id=household.id,
        member_id=member.id,
        category="NOTE",
        label="家庭记录",
        value="习惯晨练",
        source_digest="b" * 64,
        evidence_excerpt="王奶奶习惯晨练。",
        term_vector=digital_twin._tf("习惯晨练"),
        confidence=0.87,
        status="UNCONFIRMED",
        created_by="family-owner",
    )
    db_session.add_all([medication, note])
    db_session.commit()
    headers = {"X-Actor-Id": "family-owner", "X-Access-Purpose": "family-care"}

    graph = client.get(
        f"/api/v1/households/{household.id}/digital-twin",
        headers=headers,
    )
    assert graph.status_code == 200
    assert graph.json()["stats"]["memory_count"] == 2

    confirmed = client.post(
        f"/api/v1/households/{household.id}/digital-twin/memories/{medication.id}/confirm",
        headers=headers,
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["memory"]["status"] == "CONFIRMED"
    assert confirmed.json()["health_event_id"]

    rejected = client.post(
        f"/api/v1/households/{household.id}/digital-twin/memories/{note.id}/reject",
        headers=headers,
    )
    assert rejected.status_code == 200
    assert rejected.json()["memory"]["status"] == "REJECTED"
    assert rejected.json()["health_event_id"] is None

    refreshed = client.get(
        f"/api/v1/households/{household.id}/digital-twin",
        headers=headers,
    ).json()
    assert refreshed["stats"]["memory_count"] == 1
    assert all(node["source_id"] != note.id for node in refreshed["nodes"])
