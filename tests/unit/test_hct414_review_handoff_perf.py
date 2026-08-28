"""契约测试：#246 API 到人工复核的交接必须可复核且保持 DEMO_ONLY。"""

from __future__ import annotations

import pytest

import hct414_review_handoff_perf as probe

pytest.importorskip("cv2")


@pytest.fixture(scope="module")
def report() -> dict[str, object]:
    return probe.measure_review_handoff_performance(samples=2, warmup=1)


def test_report_declares_synthetic_demo_only_scope(report: dict[str, object]) -> None:
    assert report["schema_version"] == probe.REPORT_SCHEMA
    assert report["release_status"] == "DEMO_ONLY"
    assert report["issue"].startswith("#246")
    policy = report["data_policy"]
    assert policy["classification"] == "synthetic-only"
    assert policy["real_health_data"] is False
    assert policy["real_packaging_images"] is False
    assert policy["fixtures_persisted"] is False
    assert report["release_blockers"]


def test_each_handoff_stage_has_latency_evidence(report: dict[str, object]) -> None:
    stages = report["stages"]
    assert set(stages) == {"evidence_to_review", "fusion_review_finalize"}
    for stage in stages.values():
        assert stage["count"] == 2
        assert stage["p95_ms"] >= stage["p50_ms"]
        assert stage["max_ms"] >= stage["p50_ms"]
        assert stage["api"].startswith("POST /api/v1/vision-tasks/")
    assert report["within_budget"] is True
    assert report["worst_handoff_p95_ms"] <= probe.HANDOFF_P95_BUDGET_MS


def test_review_rows_are_idempotent_pending_and_side_effect_safe(
    report: dict[str, object],
) -> None:
    assertions = report["review_assertions"]
    assert assertions["expected_review_rows"] == 3
    assert assertions["review_rows"] == 3
    assert assertions["pending_review_rows"] == 3
    assert assertions["unique_review_ids_returned"] is True
    assert assertions["review_versions"] == [1]
    assert assertions["health_events_before_human_confirmation"] == 0
    idempotency = report["idempotency"]
    assert idempotency["expected_fusion_replays"] == 3
    assert idempotency["successful_fusion_replays"] == 3
    assert idempotency["all_fusion_replays_idempotent"] is True
    assert report["failures"] == []


def test_report_contains_fixture_hash_and_memory_evidence(report: dict[str, object]) -> None:
    fixture = report["fixture"]
    assert fixture["size_bytes"] > 0
    assert len(fixture["sha256"]) == 64
    assert fixture["duration_seconds"] == 1
    memory = report["process_memory"]
    assert memory["rss_before_bytes"] > 0
    assert isinstance(memory["rss_delta_bytes"], int)


def test_probe_rejects_invalid_sample_counts() -> None:
    with pytest.raises(ValueError, match="SAMPLES_INVALID"):
        probe.measure_review_handoff_performance(samples=0)
    with pytest.raises(ValueError, match="WARMUP_INVALID"):
        probe.measure_review_handoff_performance(warmup=-1)
