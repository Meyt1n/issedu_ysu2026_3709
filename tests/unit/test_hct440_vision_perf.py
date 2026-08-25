"""HCT-440: synthetic vision performance report and fail-closed budget."""

from __future__ import annotations

import json

import hct440_vision_perf as perf


def _base_api_report() -> dict:
    stats = {"p95_ms": 1.0, "error_rate": 0.0}
    return {
        "schema_version": "hct409-api-perf-v1",
        "endpoints": {
            "GET /health": stats,
            "GET /api/v1/health/db": stats,
            "POST /api/v1/households": stats,
            "GET /api/v1/households": stats,
        },
    }


def test_report_contains_real_pipeline_stages_and_no_sensitive_payload(monkeypatch) -> None:
    monkeypatch.setattr(perf, "measure_api_performance", lambda **_: _base_api_report())

    report = perf.measure_vision_performance(samples=2, warmup=0)

    assert report["schema_version"] == "hct440-vision-perf-v1"
    assert report["data_policy"] == {
        "classification": "synthetic-only",
        "real_health_data": False,
        "secrets_recorded": False,
        "network_access": False,
    }
    assert set(report["stages"]) == {
        "quality_gate",
        "evidence_normalization",
        "candidate_fusion",
        "vision_full_pipeline",
    }
    assert report["stages"]["vision_full_pipeline"]["error_rate"] == 0.0
    assert report["api_perf"]["vision_full_pipeline_p95_ms"] > 0
    serialized = json.dumps(report, ensure_ascii=False)
    assert "payload" not in serialized
    assert "dev-only" not in serialized


def test_budget_overflow_blocks_synthetic_gate(monkeypatch) -> None:
    monkeypatch.setattr(perf, "measure_api_performance", lambda **_: _base_api_report())

    report = perf.measure_vision_performance(samples=2, warmup=0, max_p95_ms=0.0)

    assert report["gate"]["passed"] is False
    assert "VISION_PIPELINE_P95_TOO_HIGH" in report["gate"]["findings"]
