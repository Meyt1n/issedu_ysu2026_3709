"""契约测试：#246 单主机并发性能探针必须可复核且不越过发布门禁。"""

from __future__ import annotations

import pytest

import hct414_concurrency_perf as probe

pytest.importorskip("cv2")


@pytest.fixture(scope="module")
def report() -> dict[str, object]:
    return probe.measure_concurrency_performance(
        concurrencies=(1, 2),
        requests_per_level=2,
        warmup=0,
        fixture_duration_seconds=1,
    )


def test_report_declares_single_host_and_demo_only(report: dict[str, object]) -> None:
    assert report["schema_version"] == probe.REPORT_SCHEMA
    assert report["release_status"] == "DEMO_ONLY"
    assert report["load_model"] == {
        "kind": "single-host-thread-pool",
        "host_count": 1,
        "worker_processes": 1,
        "multi_host_measured": False,
    }
    assert report["release_blockers"]
    assert "多主机" in " ".join(report["stages_not_measured"])


def test_each_level_reports_latency_throughput_and_isolation(report: dict[str, object]) -> None:
    levels = report["levels"]
    assert set(levels) == {"1", "2"}
    for concurrency, level in levels.items():
        assert level["concurrency"] == int(concurrency)
        assert level["requests"] == 2
        assert level["latency"]["count"] == 2
        assert level["latency"]["p95_ms"] >= level["latency"]["p50_ms"]
        assert level["throughput_requests_per_second"] > 0
        assert level["error_count"] == 0
        assert level["errors"] == []
        assert level["source_ids_isolated"] is True
        assert len(level["decisions"]) == 1


def test_report_has_synthetic_fixture_hash_and_memory_evidence(report: dict[str, object]) -> None:
    fixture = report["fixture"]
    assert fixture["size_bytes"] > 0
    assert len(fixture["sha256"]) == 64
    assert fixture["duration_seconds"] == 1
    assert report["peak_rss_bytes"] >= report["rss_before_bytes"]
    assert isinstance(report["rss_delta_bytes"], int)
    policy = report["data_policy"]
    assert policy["classification"] == "synthetic-only"
    assert policy["real_health_data"] is False
    assert policy["real_packaging_images"] is False
    assert policy["fixtures_persisted"] is False


def test_probe_rejects_unbounded_inputs() -> None:
    with pytest.raises(ValueError, match="CONCURRENCY_OUT_OF_RANGE"):
        probe.measure_concurrency_performance(concurrencies=(probe.MAX_CONCURRENCY + 1,))
    with pytest.raises(ValueError, match="REQUEST_COUNT_INVALID"):
        probe.measure_concurrency_performance(requests_per_level=0)
    with pytest.raises(ValueError, match="FIXTURE_DURATION_OUT_OF_RANGE"):
        probe.measure_concurrency_performance(fixture_duration_seconds=31)
