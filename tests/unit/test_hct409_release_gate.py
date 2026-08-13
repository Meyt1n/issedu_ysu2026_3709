"""HCT-409 backend release-gate contracts."""

from __future__ import annotations

import json
from pathlib import Path

from hct409_api_perf import (
    HEALTH_P95_BUDGET_MS,
    HOUSEHOLD_P95_BUDGET_MS,
    measure_api_performance,
)
from hct409_dependency_audit import collect_finding_ids, evaluate, load_allowlist

REPO_ROOT = Path(__file__).resolve().parents[2]
PACK_PATH = REPO_ROOT / "tests" / "e2e" / "hct409_release_pack.json"
RISK_PATH = REPO_ROOT / "docs" / "reviews" / "hct409-risk-register.json"
STORY_PATH = REPO_ROOT / "docs" / "stories" / "HCT-409-后端发布验收.md"
ALLOWED_DECISIONS = {"closed", "accepted", "deferred"}
REQUIRED_ENDPOINT_KEYS = {
    "GET /health",
    "GET /api/v1/health/db",
    "POST /api/v1/households",
    "GET /api/v1/households",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_release_pack_lists_existing_safety_and_e2e_evidence() -> None:
    pack = _load(PACK_PATH)
    assert pack["schema_version"] == "hct409-release-pack-v1"
    assert pack["issue"] == 72
    assert pack["do_not_close_issue"] is True
    assert pack["remaining_manual"]
    for relative in pack["automated_tests"]:
        assert (REPO_ROOT / relative).is_file(), relative
    assert "uv run pytest" in pack["commands"]["backend_tests"]
    assert "hct409_dependency_audit.py" in pack["commands"]["python_audit"]
    assert "npm audit" in pack["commands"]["npm_audit"]


def test_risk_register_records_decision_owner_impact_and_rollback() -> None:
    register = _load(RISK_PATH)
    assert register["schema_version"] == "hct409-risk-register-v1"
    assert register["issue"] == 72
    assert len(register["items"]) >= 4
    ids: list[str] = []
    for item in register["items"]:
        ids.append(item["id"])
        assert item["severity"] in {"P0", "P1"}
        assert item["decision"] in ALLOWED_DECISIONS
        assert item["owner"]
        assert item["impact"]
        assert item["rollback"]
        serialized = json.dumps(item)
        assert "password" not in serialized
        assert "payload" not in serialized
    assert len(ids) == len(set(ids))
    assert any(item["decision"] == "deferred" for item in register["items"])


def test_backend_story_exists_and_forbids_closing_the_parent_issue() -> None:
    story = STORY_PATH.read_text(encoding="utf-8")
    assert "HCT-409" in story
    assert "#72" in story
    assert "不关闭" in story
    assert "R3" in story


def test_base_tier_api_latency_stays_within_release_budgets() -> None:
    report = measure_api_performance(samples=12, warmup=2)
    assert report["schema_version"] == "hct409-api-perf-v1"
    assert report["tier"] == "base"
    assert report["data_policy"]["real_health_data"] is False
    assert report["data_policy"]["secrets_recorded"] is False
    endpoints = report["endpoints"]
    assert set(endpoints) == REQUIRED_ENDPOINT_KEYS
    for name, stats in endpoints.items():
        assert stats["error_rate"] == 0, name
        assert stats["p95_ms"] > 0, name
    assert endpoints["GET /health"]["p95_ms"] <= HEALTH_P95_BUDGET_MS
    assert endpoints["POST /api/v1/households"]["p95_ms"] <= HOUSEHOLD_P95_BUDGET_MS
    blob = json.dumps(report)
    assert "password" not in blob
    assert "payload" not in blob


def test_pip_audit_allowlist_rejects_unknown_ids() -> None:
    allowlist = load_allowlist()
    assert len(allowlist) >= 7
    known = [{"id": vuln_id} for vuln_id in allowlist]
    unexpected, stale = evaluate(
        {"dependencies": [{"name": "starlette", "vulns": known}]},
        allowlist,
    )
    assert unexpected == []
    assert stale == []
    extra = evaluate(
        {
            "dependencies": [
                {"name": "starlette", "vulns": known + [{"id": "PYSEC-2099-999"}]}
            ]
        },
        allowlist,
    )
    assert extra[0] == ["PYSEC-2099-999"]
    assert collect_finding_ids(
        {"dependencies": [{"vulns": [{"id": "PYSEC-2099-999"}]}]}
    ) == {"PYSEC-2099-999"}
