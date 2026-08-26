"""HCT-414: guard the video performance probe's contract and safety claims.

The probe is release evidence, so the test asserts the report stays DEMO_ONLY,
records synthetic-only fixtures, keeps the controlled rejection paths rejecting,
and reports hardware and fixture hashes that a reviewer can check.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hct414_video_perf import (
    PIPELINE_P95_BUDGET_MS,
    build_fixtures,
    measure_video_performance,
)

pytest.importorskip("cv2")


@pytest.fixture(scope="module")
def report() -> dict[str, object]:
    # Two samples keep the suite fast; percentile shape is covered by hct409.
    return measure_video_performance(samples=2, warmup=1)


def test_fixtures_are_decodable_and_hashable(tmp_path: Path) -> None:
    import cv2

    fixtures = build_fixtures(tmp_path)
    assert fixtures, "probe must generate at least one fixture"
    for fixture in fixtures:
        assert fixture.path.exists()
        capture = cv2.VideoCapture(str(fixture.path))
        try:
            assert capture.isOpened(), f"fixture not decodable: {fixture.name}"
        finally:
            capture.release()


def test_report_stays_demo_only_and_synthetic(report: dict[str, object]) -> None:
    assert report["release_status"] == "DEMO_ONLY"
    assert report["release_blockers"], "DEMO_ONLY must name its blockers"
    policy = report["data_policy"]
    assert policy["classification"] == "synthetic-only"
    assert policy["real_health_data"] is False
    assert policy["real_packaging_images"] is False
    assert policy["fixtures_persisted"] is False


def test_report_records_reviewable_environment(report: dict[str, object]) -> None:
    environment = report["environment"]
    for key in ("platform", "machine", "logical_cpus", "total_memory_bytes", "opencv"):
        assert environment[key], f"missing environment field: {key}"
    resources = report["resources"]
    assert resources["fixture_disk_bytes"] > 0
    assert "process_rss_delta_bytes" in resources


def test_every_fixture_reports_stage_counts_and_latency(report: dict[str, object]) -> None:
    fixtures = report["fixtures"]
    assert fixtures
    for name, entry in fixtures.items():
        assert len(str(entry["fixture_sha256"])) == 64, f"{name} missing fixture hash"
        assert entry["decision"] in {"PASS", "RETAKE"}
        # decoded >= sampled >= selected documents how much work each stage did.
        assert entry["decoded_frames"] >= entry["sampled_frames"] >= entry["selected_frames"]
        assert entry["latency"]["p95_ms"] >= entry["latency"]["p50_ms"]


def test_controlled_rejections_all_reject(report: dict[str, object]) -> None:
    samples = report["failure_samples"]
    names = {entry["name"] for entry in samples}
    assert {"undecodable_container", "empty_file", "duration_exceeded"} <= names
    for entry in samples:
        assert entry["outcome"] == "rejected", f"{entry['name']} was not rejected: {entry}"
    assert report["unexpected_failure_outcomes"] == []


def test_budget_is_declared_and_evaluated(report: dict[str, object]) -> None:
    assert report["budgets_ms"]["video_pipeline_p95"] == PIPELINE_P95_BUDGET_MS
    assert isinstance(report["within_budget"], bool)
    assert report["worst_pipeline_p95_ms"] >= 0


def test_limits_disclose_what_is_not_measured(report: dict[str, object]) -> None:
    not_measured = " ".join(str(item) for item in report["stages_not_measured"]).casefold()
    assert "ocr" in not_measured
    assert "fusion" in not_measured
    limits = " ".join(str(item) for item in report["known_limits"]).casefold()
    assert "synthetic" in limits
