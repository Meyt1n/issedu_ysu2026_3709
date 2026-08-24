"""HCT-404 real model release evidence gate tests."""

from __future__ import annotations

from copy import deepcopy

from hct404_benchmark_compare import build_comparison_report
from hct404_release_gate import evaluate_release_evidence


def _hash(letter: str) -> str:
    return letter * 64


def _model(model_id: str, weights: str, metrics: dict[str, float]) -> dict:
    return {
        "model_id": model_id,
        "weights_sha256": _hash(weights),
        "weights_size_bytes": 1024,
        "metrics": metrics,
        "per_class": [{"class_name": "box", "map50": metrics["map50"]}],
        "hard_negative_reviewed": True,
        "hard_negatives": [{"sample_id": "unknown-1", "false_positive": False}],
        "performance": {
            "device": "cpu",
            "images_measured": 4,
            "latency_mean_ms": 10.0,
            "latency_p95_ms": 12.0,
        },
        "status": "PASSED",
    }


def _comparison() -> dict:
    v1 = _model(
        "hct404-vision-v1",
        "a",
        {"precision": 0.96, "recall": 0.96, "map50": 0.92, "map50_95": 0.86},
    )
    v2 = _model(
        "hct404-vision-v2",
        "b",
        {"precision": 0.97, "recall": 0.97, "map50": 0.94, "map50_95": 0.89},
    )
    v2["performance"]["latency_p95_ms"] = 13.0
    return build_comparison_report(
        v1=v1,
        v2=v2,
        dataset_yaml_sha256=_hash("c"),
        test_set_sha256=_hash("d"),
        test_images=4,
    )


def _evidence(comparison: dict) -> dict:
    return {
        "schema_version": "hct404-model-release-evidence/v1",
        "release_status": "CANDIDATE_REVIEW",
        "model_id": "hct404-vision-v2",
        "models": {
            "v1": {
                "model_id": "hct404-vision-v1",
                "weights_sha256": _hash("a"),
                "model_card_sha256": _hash("e"),
                "training_config_sha256": _hash("f"),
            },
            "v2": {
                "model_id": "hct404-vision-v2",
                "weights_sha256": _hash("b"),
                "model_card_sha256": _hash("1"),
                "training_config_sha256": _hash("2"),
            },
        },
        "dataset": {
            "scope": "approved_real_fixed_set",
            "fixed_set_sha256": _hash("3"),
            "dataset_yaml_sha256": _hash("c"),
            "test_set_sha256": _hash("d"),
            "train_export_manifest_sha256": _hash("4"),
            "export_manifest_version": "hct208-approved-v2",
            "export_manifest_status": "active",
            "license": "internal-approved",
            "group_key": "hct404-v2",
            "train_test_disjoint_verified": True,
        },
        "evaluation": {
            "label_review_sha256": _hash("5"),
            "train_test_disjoint_verified": True,
            "unknown_set": {
                "reviewed": True,
                "false_positive_count": 0,
                "report_sha256": _hash("6"),
            },
        },
        "release_controls": {
            "decision": "APPROVE_FORMAL_RELEASE",
            "safety_thresholds_passed": True,
            "manual_confirmation_coverage": 1.0,
            "manual_confirmation_coverage_threshold": 1.0,
            "manual_confirmation_coverage_complete": True,
            "mismatch_impact_reviewed": True,
            "missed_detection_impact_reviewed": True,
            "r3_reviewed": True,
            "approved_by": "real-reviewer",
            "approved_at": "2026-08-24T12:00:00+08:00",
            "bundle_version": "hct404-v2-release-1",
            "approval_record_sha256": _hash("7"),
        },
        "rollback": {
            "previous_model_id": "hct404-vision-v1",
            "rollback_tested": True,
            "restored_previous_version": True,
            "new_tasks_use_previous_version": True,
            "historical_results_preserved": True,
            "evidence_sha256": _hash("8"),
        },
        "comparison_report_sha256": comparison["comparison_report_sha256"],
    }


def test_real_evidence_pack_passes_formal_gate() -> None:
    comparison = _comparison()
    report = evaluate_release_evidence(_evidence(comparison), comparison)
    assert report["passed"] is True
    assert report["decision"] == "ALLOW_FORMAL_RELEASE"
    assert report["findings"] == []


def test_placeholder_metrics_are_blocked() -> None:
    comparison = _comparison()
    comparison["v2"]["metrics"]["map50"] = "PLACEHOLDER"
    evidence = _evidence(comparison)
    report = evaluate_release_evidence(evidence, comparison)
    assert report["passed"] is False
    assert report["decision"] == "BLOCK_MODEL_RELEASE"
    assert any(item["code"] == "METRIC_MISSING" for item in report["findings"])


def test_unapproved_fixed_set_is_blocked_even_with_model_metrics() -> None:
    comparison = _comparison()
    evidence = _evidence(comparison)
    evidence["dataset"]["scope"] = "candidate_experiment"
    report = evaluate_release_evidence(evidence, comparison)
    assert report["passed"] is False
    assert any(item["code"] == "DATASET_SCOPE_INVALID" for item in report["findings"])


def test_missing_rollback_evidence_is_blocked() -> None:
    comparison = _comparison()
    evidence = _evidence(comparison)
    evidence = deepcopy(evidence)
    evidence["rollback"]["historical_results_preserved"] = False
    report = evaluate_release_evidence(evidence, comparison)
    assert report["passed"] is False
    assert any(item["code"] == "ROLLBACK_CONTROL_MISSING" for item in report["findings"])


def test_tampered_comparison_report_hash_is_blocked() -> None:
    comparison = _comparison()
    evidence = _evidence(comparison)
    comparison["v2"]["metrics"]["recall"] = 0.95
    report = evaluate_release_evidence(evidence, comparison)
    assert report["passed"] is False
    assert any(item["code"] == "COMPARISON_REPORT_HASH_INVALID" for item in report["findings"])


def test_manual_confirmation_coverage_below_threshold_is_blocked() -> None:
    comparison = _comparison()
    evidence = _evidence(comparison)
    evidence["release_controls"]["manual_confirmation_coverage"] = 0.8
    report = evaluate_release_evidence(evidence, comparison)
    assert report["passed"] is False
    assert any(
        item["code"] == "MANUAL_CONFIRMATION_COVERAGE_BELOW_THRESHOLD"
        for item in report["findings"]
    )


def test_template_marker_cannot_authorize_release() -> None:
    comparison = _comparison()
    evidence = _evidence(comparison)
    evidence["template_only"] = True
    report = evaluate_release_evidence(evidence, comparison)
    assert report["passed"] is False
    assert any(item["code"] == "EVIDENCE_TEMPLATE_NOT_ACCEPTED" for item in report["findings"])
