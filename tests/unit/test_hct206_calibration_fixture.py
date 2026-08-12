from __future__ import annotations

from pathlib import Path

from hct206_calibrate import load_fixture, run_calibration

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "hct206" / "calibration_fixture.json"


def test_hct206_fixture_is_approved_only_for_technical_calibration() -> None:
    fixture = load_fixture(FIXTURE)

    assert fixture["approval"]["status"] == "APPROVED_FOR_TECHNICAL_CALIBRATION"
    assert fixture["production_eligible"] is False
    assert fixture["source"]["type"] == "synthetic"
    assert fixture["human_review"]["review_status"] == "TECHNICAL_FIXTURE_REVIEWED"


def test_hct206_fixture_calibration_is_deterministic_and_independent() -> None:
    first = run_calibration(FIXTURE)
    second = run_calibration(FIXTURE)

    assert first == second
    report = first["report"]
    assert len(report["sample_sha256"]) == 64
    assert report["validation"]["sample_count"] == 7
    assert report["independent_test"]["sample_count"] == 6
    assert report["validation"]["false_matches"] == 0
    assert report["independent_test"]["false_matches"] == 0
    assert report["thresholds"]["config_version"] == "fusion-thresholds-calibrated-v1"
    assert any("HCT-201" in item for item in first["limitations"])
