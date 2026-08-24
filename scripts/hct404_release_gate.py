"""Fail-closed HCT-404 formal model release evidence gate.

The gate validates an external evidence pack and a real V1/V2 comparison
report. It does not accept placeholder metrics, synthetic-only data, missing
consent/export evidence, unverifiable weights, or a text-only approval. A
passing report supplies the hashes that must be copied into a model binding;
it does not activate the binding itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SCHEMA_VERSION = "hct404-model-release-evidence/v1"
COMPARISON_SCHEMA = "hct-404-comparison-report/v2"
METRIC_THRESHOLDS = {
    "precision": 0.95,
    "recall": 0.95,
    "map50": 0.90,
    "map50_95": 0.85,
}


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _required_hash(
    value: Any,
    field: str,
    findings: list[dict[str, str]],
) -> None:
    if not _is_hash(value):
        findings.append({"code": "HASH_MISSING", "message": f"{field} must be a SHA-256"})


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _required_text(value: Any, field: str, findings: list[dict[str, str]]) -> None:
    if not isinstance(value, str) or not value.strip():
        findings.append({"code": "FIELD_MISSING", "message": f"{field} is required"})


def _check_model(
    model: Any,
    label: str,
    findings: list[dict[str, str]],
) -> None:
    if not isinstance(model, dict):
        findings.append(
            {"code": "MODEL_EVIDENCE_MISSING", "message": f"models.{label} is required"}
        )
        return
    _required_text(model.get("model_id"), f"models.{label}.model_id", findings)
    for field in ("weights_sha256", "model_card_sha256", "training_config_sha256"):
        _required_hash(model.get(field), f"models.{label}.{field}", findings)


def _check_metrics(
    model: dict[str, Any],
    label: str,
    findings: list[dict[str, str]],
) -> None:
    if model.get("status") != "PASSED":
        findings.append(
            {
                "code": "MODEL_EVALUATION_NOT_PASSED",
                "message": f"comparison.{label}.status must be PASSED",
            }
        )
    metrics = model.get("metrics")
    if not isinstance(metrics, dict):
        findings.append(
            {"code": "METRICS_MISSING", "message": f"comparison.{label}.metrics is required"}
        )
        return
    for metric, threshold in METRIC_THRESHOLDS.items():
        value = _number(metrics.get(metric))
        if value is None:
            findings.append(
                {"code": "METRIC_MISSING", "message": f"comparison.{label}.{metric} is required"}
            )
        elif not 0 <= value <= 1:
            findings.append(
                {
                    "code": "METRIC_INVALID",
                    "message": f"comparison.{label}.{metric} must be between 0 and 1",
                }
            )
        elif label == "v2" and value < threshold:
            findings.append(
                {
                    "code": "V2_METRIC_BELOW_THRESHOLD",
                    "message": f"comparison.v2.{metric} < {threshold:.2f}",
                }
            )
    per_class = model.get("per_class")
    if not isinstance(per_class, list) or not per_class:
        findings.append(
            {
                "code": "PER_CLASS_EVIDENCE_MISSING",
                "message": f"comparison.{label}.per_class is required",
            }
        )
    hard_negatives = model.get("hard_negatives")
    if not isinstance(hard_negatives, list) or not hard_negatives:
        findings.append(
            {
                "code": "HARD_NEGATIVE_EVIDENCE_MISSING",
                "message": f"comparison.{label}.hard_negatives is required",
            }
        )
    else:
        false_positives = [
            item
            for item in hard_negatives
            if isinstance(item, dict) and item.get("false_positive") is True
        ]
        if label == "v2" and false_positives:
            findings.append(
                {
                    "code": "HARD_NEGATIVE_FALSE_POSITIVE",
                    "message": (
                        f"comparison.v2 has {len(false_positives)} hard-negative false positives"
                    ),
                }
            )
    performance = model.get("performance")
    if not isinstance(performance, dict):
        findings.append(
            {
                "code": "PERFORMANCE_EVIDENCE_MISSING",
                "message": f"comparison.{label}.performance is required",
            }
        )
    else:
        for field in ("device", "images_measured"):
            _required_text(
                str(performance.get(field, "")), f"comparison.{label}.performance.{field}", findings
            )
        for field in ("latency_mean_ms", "latency_p95_ms"):
            value = _number(performance.get(field))
            if value is None or value <= 0:
                findings.append(
                    {
                        "code": "PERFORMANCE_VALUE_INVALID",
                        "message": f"comparison.{label}.performance.{field} must be positive",
                    }
                )


def _check_comparison(
    evidence: dict[str, Any],
    comparison: dict[str, Any],
    findings: list[dict[str, str]],
) -> None:
    comparison_hash = comparison.get("comparison_report_sha256")
    _required_hash(comparison_hash, "comparison.comparison_report_sha256", findings)
    if _is_hash(comparison_hash):
        unsigned_comparison = dict(comparison)
        unsigned_comparison.pop("comparison_report_sha256", None)
        if comparison_hash != canonical_sha256(unsigned_comparison):
            findings.append(
                {
                    "code": "COMPARISON_REPORT_HASH_INVALID",
                    "message": "comparison_report_sha256 does not match the report contents",
                }
            )
    if evidence.get("comparison_report_sha256") != comparison_hash:
        findings.append(
            {
                "code": "COMPARISON_REPORT_HASH_MISMATCH",
                "message": "evidence.comparison_report_sha256 must match the comparison report",
            }
        )
    if comparison.get("schema_version") != COMPARISON_SCHEMA:
        findings.append(
            {
                "code": "COMPARISON_SCHEMA_INVALID",
                "message": f"comparison schema must be {COMPARISON_SCHEMA}",
            }
        )
    if comparison.get("evaluation_scope") != "approved_real_fixed_set":
        findings.append(
            {
                "code": "FIXED_SET_SCOPE_INVALID",
                "message": "comparison must use approved_real_fixed_set",
            }
        )
    if comparison.get("same_fixed_set") is not True:
        findings.append(
            {
                "code": "FIXED_SET_NOT_SHARED",
                "message": "V1 and V2 must use the same fixed test set",
            }
        )
    assessment = comparison.get("release_assessment")
    if not isinstance(assessment, dict) or assessment.get("passes_safety_thresholds") is not True:
        findings.append(
            {
                "code": "COMPARISON_GATE_FAILED",
                "message": "comparison report did not pass safety thresholds",
            }
        )

    dataset = evidence.get("dataset")
    comparison_dataset = comparison.get("dataset")
    if not isinstance(dataset, dict) or not isinstance(comparison_dataset, dict):
        findings.append(
            {
                "code": "DATASET_EVIDENCE_MISSING",
                "message": "dataset and comparison.dataset are required",
            }
        )
    else:
        for field in ("test_set_sha256", "dataset_yaml_sha256"):
            if dataset.get(field) != comparison_dataset.get(field):
                findings.append(
                    {
                        "code": "DATASET_HASH_MISMATCH",
                        "message": f"dataset.{field} must match comparison.dataset.{field}",
                    }
                )
        comparison_fixed_set = comparison.get("fixed_set")
        if not isinstance(comparison_fixed_set, dict):
            findings.append(
                {
                    "code": "FIXED_SET_EVIDENCE_MISSING",
                    "message": "comparison.fixed_set is required",
                }
            )
        else:
            for field in ("test_set_sha256", "dataset_yaml_sha256"):
                if dataset.get(field) != comparison_fixed_set.get(field):
                    findings.append(
                        {
                            "code": "FIXED_SET_HASH_MISMATCH",
                            "message": f"dataset.{field} must match comparison.fixed_set.{field}",
                        }
                    )

    models = evidence.get("models")
    for label in ("v1", "v2"):
        model = models.get(label) if isinstance(models, dict) else None
        comparison_model = comparison.get(label)
        _check_model(model, label, findings)
        if not isinstance(model, dict) or not isinstance(comparison_model, dict):
            findings.append(
                {"code": "COMPARISON_MODEL_MISSING", "message": f"comparison.{label} is required"}
            )
            continue
        if model.get("model_id") != comparison_model.get("model_id"):
            findings.append(
                {
                    "code": "MODEL_ID_MISMATCH",
                    "message": f"models.{label}.model_id must match comparison.{label}.model_id",
                }
            )
        if model.get("weights_sha256") != comparison_model.get("weights_sha256"):
            findings.append(
                {
                    "code": "WEIGHTS_HASH_MISMATCH",
                    "message": (
                        f"models.{label}.weights_sha256 must match "
                        f"comparison.{label}.weights_sha256"
                    ),
                }
            )
        _check_metrics(comparison_model, label, findings)

    evaluation = evidence.get("evaluation")
    if not isinstance(evaluation, dict):
        findings.append(
            {"code": "EVALUATION_EVIDENCE_MISSING", "message": "evaluation is required"}
        )
    else:
        unknown = evaluation.get("unknown_set")
        if not isinstance(unknown, dict) or unknown.get("reviewed") is not True:
            findings.append(
                {"code": "UNKNOWN_SET_REVIEW_MISSING", "message": "unknown-set review is required"}
            )
        else:
            _required_hash(
                unknown.get("report_sha256"), "evaluation.unknown_set.report_sha256", findings
            )
            count = _number(unknown.get("false_positive_count"))
            if count is None or count != 0:
                findings.append(
                    {
                        "code": "UNKNOWN_SET_FALSE_POSITIVE",
                        "message": "unknown-set false-positive count must be zero",
                    }
                )
        _required_hash(
            evaluation.get("label_review_sha256"), "evaluation.label_review_sha256", findings
        )
        if evaluation.get("train_test_disjoint_verified") is not True:
            findings.append(
                {
                    "code": "TRAIN_TEST_LEAKAGE_UNVERIFIED",
                    "message": "train/test disjointness must be verified",
                }
            )

    performance_delta = comparison.get("performance_delta")
    thresholds = comparison.get("thresholds")
    ratio = (
        _number(performance_delta.get("p95_ratio")) if isinstance(performance_delta, dict) else None
    )
    max_ratio = (
        _number(thresholds.get("max_p95_regression_ratio"))
        if isinstance(thresholds, dict)
        else None
    )
    if ratio is None or max_ratio is None or ratio > max_ratio:
        findings.append(
            {
                "code": "PERFORMANCE_REGRESSION",
                "message": "V2 p95 latency regression exceeds the recorded threshold",
            }
        )


def _check_controls(evidence: dict[str, Any], findings: list[dict[str, str]]) -> None:
    controls = evidence.get("release_controls")
    if not isinstance(controls, dict):
        findings.append(
            {"code": "RELEASE_CONTROLS_MISSING", "message": "release_controls are required"}
        )
        return
    if controls.get("decision") != "APPROVE_FORMAL_RELEASE":
        findings.append(
            {"code": "APPROVAL_DECISION_MISSING", "message": "formal approval decision is required"}
        )
    for field in (
        "safety_thresholds_passed",
        "manual_confirmation_coverage_complete",
        "mismatch_impact_reviewed",
        "missed_detection_impact_reviewed",
        "r3_reviewed",
    ):
        if controls.get(field) is not True:
            findings.append(
                {
                    "code": "RELEASE_CONTROL_MISSING",
                    "message": f"release_controls.{field} must be true",
                }
            )
    coverage = _number(controls.get("manual_confirmation_coverage"))
    coverage_threshold = _number(controls.get("manual_confirmation_coverage_threshold"))
    if coverage is None or not 0 <= coverage <= 1:
        findings.append(
            {
                "code": "MANUAL_CONFIRMATION_COVERAGE_INVALID",
                "message": "release_controls.manual_confirmation_coverage must be between 0 and 1",
            }
        )
    if coverage_threshold is None or not 0 <= coverage_threshold <= 1:
        findings.append(
            {
                "code": "MANUAL_CONFIRMATION_THRESHOLD_INVALID",
                "message": (
                    "release_controls.manual_confirmation_coverage_threshold "
                    "must be between 0 and 1"
                ),
            }
        )
    elif coverage is not None and coverage < coverage_threshold:
        findings.append(
            {
                "code": "MANUAL_CONFIRMATION_COVERAGE_BELOW_THRESHOLD",
                "message": "manual confirmation coverage is below the recorded release threshold",
            }
        )
    for field in ("approved_by", "approved_at", "bundle_version"):
        _required_text(controls.get(field), f"release_controls.{field}", findings)
    _required_hash(
        controls.get("approval_record_sha256"), "release_controls.approval_record_sha256", findings
    )


def _check_rollback(evidence: dict[str, Any], findings: list[dict[str, str]]) -> None:
    rollback = evidence.get("rollback")
    if not isinstance(rollback, dict):
        findings.append(
            {"code": "ROLLBACK_EVIDENCE_MISSING", "message": "rollback evidence is required"}
        )
        return
    for field in (
        "rollback_tested",
        "restored_previous_version",
        "new_tasks_use_previous_version",
        "historical_results_preserved",
    ):
        if rollback.get(field) is not True:
            findings.append(
                {"code": "ROLLBACK_CONTROL_MISSING", "message": f"rollback.{field} must be true"}
            )
    models = evidence.get("models")
    previous_id = models.get("v1", {}).get("model_id") if isinstance(models, dict) else None
    if rollback.get("previous_model_id") != previous_id:
        findings.append(
            {"code": "ROLLBACK_TARGET_MISMATCH", "message": "rollback.previous_model_id must be V1"}
        )
    _required_hash(rollback.get("evidence_sha256"), "rollback.evidence_sha256", findings)


def evaluate_release_evidence(
    evidence: dict[str, Any],
    comparison: dict[str, Any],
) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    if evidence.get("schema_version") != SCHEMA_VERSION:
        findings.append(
            {
                "code": "EVIDENCE_SCHEMA_INVALID",
                "message": f"evidence schema must be {SCHEMA_VERSION}",
            }
        )
    if evidence.get("template_only") is True:
        findings.append(
            {
                "code": "EVIDENCE_TEMPLATE_NOT_ACCEPTED",
                "message": "template_only evidence cannot authorize a formal release",
            }
        )
    _required_text(evidence.get("model_id"), "model_id", findings)
    models = evidence.get("models")
    v2_id = models.get("v2", {}).get("model_id") if isinstance(models, dict) else None
    if evidence.get("model_id") != v2_id:
        findings.append({"code": "RELEASE_MODEL_MISMATCH", "message": "model_id must identify V2"})
    if evidence.get("release_status") not in {"CANDIDATE_REVIEW", "EXPERIMENTAL_UNRELEASED"}:
        findings.append(
            {
                "code": "REGISTRY_STATUS_INVALID",
                "message": "release must start from an unreleased candidate",
            }
        )

    dataset = evidence.get("dataset")
    if not isinstance(dataset, dict):
        findings.append({"code": "DATASET_EVIDENCE_MISSING", "message": "dataset is required"})
    else:
        if dataset.get("scope") != "approved_real_fixed_set":
            findings.append(
                {"code": "DATASET_SCOPE_INVALID", "message": "approved_real_fixed_set is required"}
            )
        if dataset.get("export_manifest_status") != "active":
            findings.append(
                {
                    "code": "EXPORT_MANIFEST_INVALID",
                    "message": "active HCT-208 export manifest is required",
                }
            )
        for field in (
            "fixed_set_sha256",
            "dataset_yaml_sha256",
            "test_set_sha256",
            "train_export_manifest_sha256",
        ):
            _required_hash(dataset.get(field), f"dataset.{field}", findings)
        for field in ("license", "export_manifest_version", "group_key"):
            _required_text(dataset.get(field), f"dataset.{field}", findings)
        if dataset.get("train_test_disjoint_verified") is not True:
            findings.append(
                {
                    "code": "TRAIN_TEST_LEAKAGE_UNVERIFIED",
                    "message": "dataset train/test disjointness is required",
                }
            )

    _check_comparison(evidence, comparison, findings)
    _check_controls(evidence, findings)
    _check_rollback(evidence, findings)

    passed = not findings
    return {
        "schema_version": "hct404-model-release-gate/v1",
        "model_id": evidence.get("model_id"),
        "release_mode": "FORMAL_EVIDENCE",
        "passed": passed,
        "decision": "ALLOW_FORMAL_RELEASE" if passed else "BLOCK_MODEL_RELEASE",
        "findings": findings,
        "limitations": [
            (
                "This gate validates evidence references and hashes; it does not copy "
                "model weights or activate an API binding."
            ),
            (
                "A passing report still requires the binding API to receive the emitted "
                "hashes and a separately authorized actor."
            ),
            (
                "No real health payload, image, label, weight or raw prediction belongs "
                "in the repository."
            ),
        ],
    }


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name}: JSON root must be an object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--comparison", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    try:
        evidence = _load(args.evidence)
        comparison = _load(args.comparison)
        report = evaluate_release_evidence(evidence, comparison)
        report["input_sha256"] = {
            "evidence": hashlib.sha256(args.evidence.read_bytes()).hexdigest(),
            "comparison": hashlib.sha256(args.comparison.read_bytes()).hexdigest(),
        }
        binding = report.setdefault("binding_safety_thresholds", {})
        binding.update(
            {
                "hct404_release_evidence_required": True,
                "hct404_release_evidence_schema": "hct404-model-release-evidence/v1",
                "hct404_release_status": report["decision"],
                "hct404_release_evidence_sha256": report["input_sha256"]["evidence"],
                "hct404_comparison_report_sha256": comparison.get("comparison_report_sha256"),
                "hct404_model_artifact_sha256": comparison.get("v2", {}).get("weights_sha256"),
                "hct404_fixed_set_sha256": evidence.get("dataset", {}).get("fixed_set_sha256"),
                "hct404_rollback_evidence_sha256": evidence.get("rollback", {}).get(
                    "evidence_sha256"
                ),
                "hct404_approval_sha256": evidence.get("release_controls", {}).get(
                    "approval_record_sha256"
                ),
            }
        )
        report["hct404_release_gate_sha256"] = canonical_sha256(report)
        report["binding_safety_thresholds"]["hct404_release_gate_sha256"] = report[
            "hct404_release_gate_sha256"
        ]
        report["report_sha256"] = canonical_sha256(report)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = {
            "schema_version": "hct404-model-release-gate/v1",
            "passed": False,
            "decision": "BLOCK_MODEL_RELEASE",
            "findings": [{"code": "INPUT_ERROR", "message": str(exc)}],
        }
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
