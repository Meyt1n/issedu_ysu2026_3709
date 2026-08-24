from __future__ import annotations

from hct206_release_gate import evaluate_release_readiness
from hct_p0_acceptance import REQUIRED_REPORTS


def _hct201(*, passed: bool = True) -> dict:
    return {
        "schema_version": "hct201-approved-fixed-set-gate/v1",
        "passed": passed,
        "decision": "ALLOW_APPROVED_FIXED_SET" if passed else "BLOCK_APPROVED_FIXED_SET",
        "dataset_scope": "approved_real_fixed_set",
        "approved_drug_count": 12,
        "case_counts": {"known": 12, "unknown": 2, "conflict": 2},
        "manifest_sha256": "a" * 64,
    }


def _hct205(*, passed: bool = True, real: bool = True) -> dict:
    return {
        "schema_version": "hct205-accuracy-report/v1",
        "passed": passed,
        "decision": "ACCEPT_OCR_BARCODE_MASTER_DATA" if passed else "BLOCK_OCR_BARCODE_MASTER_DATA",
        "evaluation_scope": "approved_real_fixed_set" if real else "synthetic_or_mixed",
        "input_sha256": "b" * 64,
        "thresholds": {
            "min_field_accuracy": 0.95,
            "min_barcode_accuracy": 0.98,
            "min_status_accuracy": 0.95,
        },
        "metrics": {
            "overall_field_accuracy": 0.99,
            "status_accuracy": 0.98,
            "field_accuracy": {"barcode": 0.99},
        },
    }


def _hct206(*, production: bool = True, false_match_rate: float = 0.0) -> dict:
    return {
        "schema_version": "hct206-production-calibration-evidence/v1",
        "dataset_scope": "approved_real_fixed_set",
        "production_eligible": production,
        "approval_status": (
            "APPROVED_FOR_PRODUCTION_CALIBRATION"
            if production
            else "APPROVED_FOR_TECHNICAL_CALIBRATION"
        ),
        "source": {"type": "approved_real_fixed_set"},
        "human_review": {
            "review_status": "PRODUCTION_CALIBRATION_REVIEWED",
            "reviewer": "external-r3-reviewer",
            "review_date": "2026-08-24",
        },
        "dataset_gate_ref": "external/hct201-fixed-set.json",
        "accuracy_report_ref": "external/hct205-accuracy.json",
        "review_record_ref": "external/hct206-review",
        "evidence_bindings": {
            "hct201_manifest_sha256": "a" * 64,
            "hct205_input_sha256": "b" * 64,
        },
        "report": {
            "schema_version": "fusion-calibration-report-v1",
            "sample_sha256": "c" * 64,
            "thresholds": {"config_version": "fusion-thresholds-calibrated-v1"},
            "validation": {"sample_count": 20, "false_match_rate": false_match_rate},
            "independent_test": {"sample_count": 20, "false_match_rate": false_match_rate},
        },
    }


def test_hct206_gate_accepts_only_bound_real_evidence() -> None:
    report = evaluate_release_readiness(
        dataset_gate=_hct201(),
        accuracy_report=_hct205(),
        calibration_report=_hct206(),
    )

    assert report["passed"] is True
    assert report["decision"] == "READY_FOR_R3_REVIEW"
    assert report["findings"] == []


def test_hct206_gate_blocks_synthetic_calibration_even_when_rules_are_clean() -> None:
    report = evaluate_release_readiness(
        dataset_gate=_hct201(),
        accuracy_report=_hct205(),
        calibration_report=_hct206(production=False),
    )

    assert report["passed"] is False
    assert report["decision"] == "BLOCK_CANDIDATE_FUSION"
    assert {item["code"] for item in report["findings"]} >= {
        "HCT206_PRODUCTION_MARKER_REQUIRED",
        "HCT206_APPROVAL_REQUIRED",
    }


def test_hct206_gate_blocks_when_hct201_or_hct205_real_gate_is_missing() -> None:
    report = evaluate_release_readiness(
        dataset_gate=_hct201(passed=False),
        accuracy_report=_hct205(real=False),
        calibration_report=_hct206(),
    )

    assert report["passed"] is False
    assert report["decision"] == "BLOCK_CANDIDATE_FUSION"
    assert {item["code"] for item in report["findings"]} >= {
        "HCT201_GATE_BLOCKED",
        "HCT205_REAL_SCOPE_REQUIRED",
    }


def test_hct206_gate_blocks_false_matches_by_default() -> None:
    report = evaluate_release_readiness(
        dataset_gate=_hct201(),
        accuracy_report=_hct205(),
        calibration_report=_hct206(false_match_rate=0.01),
    )

    assert report["passed"] is False
    assert "HCT206_FALSE_MATCH_RATE_TOO_HIGH" in {item["code"] for item in report["findings"]}


def test_hct206_is_required_by_the_p0_evidence_aggregator() -> None:
    assert REQUIRED_REPORTS["HCT-206"] == ("hct206-release.json", {"READY_FOR_R3_REVIEW"})
