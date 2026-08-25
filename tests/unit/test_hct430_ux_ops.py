"""HCT-430 incremental multi-agent UX and operations coverage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.local_agents import _database_agent, plan_agent_execution, run_local_multi_agent
from app.models import HealthEvent, Household, Member
from app.retrieval_cache import (
    cache_get,
    cache_put,
    clear_all,
    digest_query,
    make_entry_key,
    make_session_key,
)
from app.search_providers import (
    clear_search_cache,
    execute_web_search,
    reset_search_ops_metrics,
    search_ops_snapshot,
)
from app.tool_call import OllamaClient, classify_question_detail, execute_whitelisted_tool


def _trace(agent_id: str, role: str, *, source_count: int = 0) -> dict[str, object]:
    return {
        "agent_id": agent_id,
        "role": role,
        "status": "completed",
        "local": True,
        "network_used": False,
        "duration_ms": 1,
        "summary": "ok",
        "source_count": source_count,
        "cache_hit": False,
    }


def test_override_and_classifier_detail_are_exposed() -> None:
    detail = classify_question_detail("你好", override="RULE_EVIDENCE")
    assert detail["lexicon"] == "GENERAL"
    assert detail["merged"] == "RULE_EVIDENCE"
    assert detail["override"] == "RULE_EVIDENCE"

    result = run_local_multi_agent(
        None,
        messages=[{"role": "user", "content": "你好"}],
        actor_id="ux-ops-actor",
        query_type_override="GENERAL",
    )
    router = result["agent_trace"][0]
    assert result["classifier"]["override"] == "GENERAL"
    assert result["route_explanation"]
    assert router["classifier"] == result["classifier"]
    assert "显式覆盖" in router["summary"]


def test_evidence_preview_is_emitted_before_synthesis(monkeypatch) -> None:
    order: list[str] = []
    previews: list[dict[str, object]] = []

    def fake_database(_session, **_kwargs):
        return {
            "get_member_state": {"sources": ["event-1"]},
            "get_health_events": {"sources": ["event-1"]},
            "get_care_plan_status": {"sources": ["plan-1"]},
        }, _trace("database", "健康档案核对", source_count=3)

    def fake_rules(_session, **_kwargs):
        return {
            "get_applied_rules": {"sources": ["RULE-1"]},
            "get_risk_alerts": {"sources": ["RULE-1"]},
        }, _trace("rules", "规则依据核对", source_count=2)

    def fake_knowledge(_session, **_kwargs):
        return {
            "results": [{
                "document_id": "doc-1",
                "chunk_id": "chunk-1",
                "title": "审核资料",
                "version": "v1",
                "text": "受控片段",
            }]
        }, _trace("knowledge", "本地资料检索", source_count=1)

    def fake_synthesis(**kwargs):
        order.append("synthesis")
        assert "get_applied_rules" in kwargs["rules"]
        return {
            "answer": "已按本地证据核对。",
            "sources": [],
            "citations": [],
            "suggested_questions": [],
            "confidence": "high",
            "escalate": False,
            "degraded": False,
            "degrade_reason": None,
            "route": None,
            "model": kwargs["model"],
            "query_type": kwargs["query_type"],
            "risk_notice": None,
            "_trace": _trace("synthesis", "回答生成"),
        }

    def on_preview(preview: dict[str, object]) -> None:
        order.append("preview")
        previews.append(preview)

    monkeypatch.setattr("app.local_agents._database_agent", fake_database)
    monkeypatch.setattr("app.local_agents._rules_agent", fake_rules)
    monkeypatch.setattr("app.local_agents._knowledge_agent", fake_knowledge)
    monkeypatch.setattr("app.local_agents._synthesis_agent", fake_synthesis)

    result = run_local_multi_agent(
        None,
        messages=[{"role": "user", "content": "两种药能否同服？"}],
        actor_id="ux-ops-actor",
        household_id="household",
        member_id="member",
        on_evidence_preview=on_preview,
    )

    assert order == ["preview", "synthesis"]
    assert previews == [result["evidence_preview"]]
    assert result["evidence_preview"] == {
        "query_type": "MEDICATION_SAFETY",
        "database_tools": [
            "get_member_state",
            "get_health_events",
            "get_care_plan_status",
        ],
        "knowledge_titles": ["审核资料"],
        "knowledge_count": 1,
        "external_count": 0,
        "rule_tools": ["get_applied_rules", "get_risk_alerts"],
    }


def test_session_cache_clear_endpoint_is_actor_scoped(client: TestClient) -> None:
    clear_all()
    session_id = "assistant-session"
    actor_key = make_session_key(
        assistant_session_id=session_id,
        actor_id="cache-owner",
        household_id="household-a",
        member_id="member-a",
    )
    other_scope_key = make_session_key(
        assistant_session_id=session_id,
        actor_id="cache-owner",
        household_id="household-b",
        member_id="member-b",
    )
    other_actor_key = make_session_key(
        assistant_session_id=session_id,
        actor_id="other-actor",
        household_id="household-a",
        member_id="member-a",
    )
    entries = [
        make_entry_key(key, agent="database", query_digest=digest_query("record"))
        for key in (actor_key, other_scope_key, other_actor_key)
    ]
    for entry in entries:
        cache_put(entry, {"safe": True}, ttl_seconds=120)

    response = client.post(
        "/api/v1/assistant/session-cache/clear",
        headers={"X-Actor-Id": "cache-owner"},
        json={"assistant_session_id": session_id},
    )

    assert response.status_code == 200
    assert response.json()["cleared_entries"] == 2
    assert cache_get(entries[0]) is None
    assert cache_get(entries[1]) is None
    assert cache_get(entries[2]) == {"safe": True}
    clear_all()


def test_database_agent_marks_authorised_session_cache_hit(db_session: Session) -> None:
    clear_all()
    household = Household(name="Cache household", created_by="cache-owner")
    db_session.add(household)
    db_session.flush()
    member = Member(
        household_id=household.id,
        display_name="Cache member",
        role="DEPENDENT",
    )
    db_session.add(member)
    db_session.commit()
    session_key = make_session_key(
        assistant_session_id="cache-session",
        actor_id="cache-owner",
        household_id=household.id,
        member_id=member.id,
    )

    first, first_trace = _database_agent(
        db_session,
        query="一般问题",
        query_type="GENERAL",
        actor_id="cache-owner",
        household_id=household.id,
        member_id=member.id,
        access_purpose=None,
        retrieval_session_key=session_key,
        cache_ttl_seconds=120,
    )
    second, second_trace = _database_agent(
        db_session,
        query="后续问题",
        query_type="GENERAL",
        actor_id="cache-owner",
        household_id=household.id,
        member_id=member.id,
        access_purpose=None,
        retrieval_session_key=session_key,
        cache_ttl_seconds=120,
    )

    assert first == second
    assert first_trace["cache_hit"] is False
    assert second_trace["cache_hit"] is True
    clear_all()


def test_search_ops_snapshot_reports_cache_metrics(monkeypatch) -> None:
    class StubProvider:
        def search(self, query: str, *, settings: Settings):
            return [{
                "title": "本地运维测试结果",
                "url": "https://example.com/result",
                "snippet": query,
                "domain": "example.com",
                "source": "external_web_search",
            }]

    monkeypatch.setattr(
        "app.search_providers.get_search_provider",
        lambda _settings: StubProvider(),
    )
    clear_search_cache()
    reset_search_ops_metrics()
    settings = Settings(
        agent_web_search_enabled=True,
        agent_web_search_url="https://example.com/search",
        agent_web_search_allowed_domains="example.com",
        agent_web_search_cache_ttl_seconds=120,
        agent_web_search_min_interval_seconds=0,
    )
    execute_web_search("运维指标", settings=settings)
    execute_web_search("运维指标", settings=settings)

    snapshot = search_ops_snapshot(settings)
    assert snapshot["web_search_ready"] is True
    assert snapshot["cache_hits"] == 1
    assert snapshot["cache_misses"] == 1
    assert snapshot["searches"] == 1
    assert "query" not in snapshot


def test_search_ops_endpoint_allows_authenticated_development_actor(
    client: TestClient,
) -> None:
    response = client.get(
        "/api/v1/assistant/web-search/ops",
        headers={"X-Actor-Id": "authenticated-local-operator"},
    )
    assert response.status_code == 200
    assert "web_search_provider" in response.json()


def test_search_ops_endpoint_honours_configured_admins(client: TestClient) -> None:
    settings = get_settings()
    previous = settings.knowledge_admin_actors
    settings.knowledge_admin_actors = "search-ops-admin"
    try:
        denied = client.get(
            "/api/v1/assistant/web-search/ops",
            headers={"X-Actor-Id": "ordinary-actor"},
        )
        allowed = client.get(
            "/api/v1/assistant/web-search/ops",
            headers={"X-Actor-Id": "search-ops-admin"},
        )
    finally:
        settings.knowledge_admin_actors = previous

    assert denied.status_code == 403
    assert allowed.status_code == 200


def test_rules_plan_is_explicit_and_member_scoped() -> None:
    for query_type in ("RULE_EVIDENCE", "URGENT", "MEDICATION_SAFETY"):
        plan = plan_agent_execution(query_type, household_id="h", member_id="m")
        assert plan["rules"].run is True
    assert plan_agent_execution(
        "MEDICATION_RECORD", household_id="h", member_id="m"
    )["rules"].run is False
    assert plan_agent_execution(
        "RULE_EVIDENCE", household_id=None, member_id=None
    )["rules"].run is False


def test_care_plan_tool_returns_compact_authorised_status(db_session: Session) -> None:
    now = datetime.now(UTC)
    household = Household(name="Synthetic household", created_by="plan-owner", time_zone="UTC")
    db_session.add(household)
    db_session.flush()
    member = Member(
        household_id=household.id,
        display_name="Synthetic member",
        role="DEPENDENT",
    )
    db_session.add(member)
    db_session.flush()
    plan = HealthEvent(
        household_id=household.id,
        member_id=member.id,
        sequence_no=1,
        event_type="plan_created",
        source="MANUAL",
        confirmation_status="CONFIRMED",
        payload={"drug": "演示药", "schedule": "每日一次"},
        evidence={},
        created_by="plan-owner",
        confirmed_by="plan-owner",
        correlation_id="synthetic-plan",
        schema_version=1,
        occurred_at=now - timedelta(hours=25),
    )
    db_session.add(plan)
    db_session.commit()

    result = execute_whitelisted_tool(
        db_session,
        name="get_care_plan_status",
        arguments={},
        actor_id="plan-owner",
        household_id=household.id,
        member_id=member.id,
    )

    assert "error" not in result
    assert result["pending_confirm"]
    assert "action_history" not in result["today_plans"][0]


def test_ollama_cancel_closes_response_before_raising(monkeypatch) -> None:
    class FakeResponse:
        closed = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self) -> None:
            return None

        def iter_lines(self):
            yield '{"message":{"content":"draft"},"done":false}'

        def close(self) -> None:
            self.closed = True

    response = FakeResponse()

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def stream(self, *_args, **_kwargs):
            return response

    monkeypatch.setattr("app.tool_call.httpx.Client", FakeClient)
    stream = OllamaClient().chat_stream(
        model="local-model",
        messages=[{"role": "user", "content": "cancel"}],
        cancel_check=lambda: True,
    )

    with pytest.raises(RuntimeError, match="OLLAMA_CANCELLED"):
        list(stream)
    assert response.closed is True
