"""Check whether a YOLO/QLoRA experiment has enough evidence for R3 review.

This command never publishes a model and never changes the registry.  It only
converts the required dataset, independent evaluation and rollback artifacts
into an explicit ``READY_FOR_R3_REVIEW`` or ``BLOCK_MODEL_RELEASE`` result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
YOLO_METRIC_THRESHOLDS = {
    "precision": 0.95,
    "recall": 0.95,
    "map50": 0.90,
    "map50_95": 0.85,
}


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _require_sha256(value: Any, field: str, findings: list[dict[str, str]]) -> None:
    if not _is_sha256(value):
        findings.append({"code": "HASH_MISSING", "message": f"{field} must be a SHA-256"})


def _canonical_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def candidate_evaluation_from_registry(registry: dict[str, Any]) -> dict[str, Any]:
    """Build a clearly labelled candidate-only report for a maintainer waiver."""

    evaluation = registry.get("evaluation")
    artifacts = registry.get("artifacts")
    if not isinstance(evaluation, dict) or not isinstance(artifacts, dict):
        raise ValueError("REGISTRY_CANDIDATE_EVALUATION_MISSING")
    test = evaluation.get("test")
    performance = evaluation.get("performance")
    if not isinstance(test, dict) or not isinstance(performance, dict):
        raise ValueError("REGISTRY_CANDIDATE_METRICS_MISSING")
    metrics = {key: test.get(key) for key in ("precision", "recall", "map50", "map50_95")}
    return {
        "schema_version": "hct203-yolo-candidate-registry-evaluation/v1",
        "status": "CANDIDATE_ACCEPTED_BY_MAINTAINER_WAIVER",
        "evaluation_source": "registry_candidate_experiment",
        "evaluation_scope": "candidate_test_set",
        "independent_evaluation": False,
        "hard_negative_reviewed": bool(evaluation.get("hard_negatives")),
        "test_set_sha256": performance.get("input_set_sha256"),
        "metrics": metrics,
        "hard_negatives": evaluation.get("hard_negatives", []),
        "evaluation_report_sha256": artifacts.get("evaluation_report_sha256"),
        "threshold_report_sha256": artifacts.get("threshold_report_sha256"),
        "waiver_required": True,
    }


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name}: JSON root must be an object")
    return value


def evaluate_release_readiness(
    *,
    model_kind: str,
    registry: dict[str, Any],
    dataset_gate: dict[str, Any],
    evaluation: dict[str, Any],
    rollback: dict[str, Any],
    waiver: dict[str, Any] | None = None,
) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    waiver_active = waiver is not None
    if waiver_active and (
        waiver.get("passed") is not True or waiver.get("decision") != "MAINTAINER_WAIVER_APPROVED"
    ):
        findings.append(
            {"code": "MAINTAINER_WAIVER_INVALID", "message": "maintainer waiver did not pass"}
        )
    if model_kind not in {"yolo", "qlora"}:
        findings.append(
            {"code": "INVALID_MODEL_KIND", "message": "model kind must be yolo or qlora"}
        )
    dataset_gate_blocked = (
        dataset_gate.get("decision") != "ALLOW_APPROVED_FIXED_SET"
        or dataset_gate.get("passed") is not True
    )
    if dataset_gate_blocked and not waiver_active:
        findings.append(
            {"code": "DATASET_GATE_BLOCKED", "message": "approved fixed-set gate did not pass"}
        )
    if not waiver_active:
        _require_sha256(
            dataset_gate.get("manifest_sha256"), "dataset_gate.manifest_sha256", findings
        )
    if registry.get("release_status") not in {"EXPERIMENTAL_UNRELEASED", "CANDIDATE_REVIEW"}:
        findings.append(
            {
                "code": "REGISTRY_STATUS_INVALID",
                "message": "registry must remain unreleased during this gate",
            }
        )
    training = registry.get("training")
    dataset_not_approved = (
        not isinstance(training, dict) or training.get("dataset_status") != "APPROVED"
    )
    if dataset_not_approved and not waiver_active:
        findings.append(
            {
                "code": "REGISTRY_DATASET_NOT_APPROVED",
                "message": "registry training dataset is not APPROVED",
            }
        )
    artifacts = registry.get("artifacts")
    if not isinstance(artifacts, dict):
        findings.append(
            {"code": "REGISTRY_ARTIFACTS_MISSING", "message": "registry artifacts are required"}
        )
    else:
        _require_sha256(
            artifacts.get("weights_sha256"), "registry.artifacts.weights_sha256", findings
        )
    if (
        not str(registry.get("model_id", "")).strip()
        or not str(registry.get("model_version", registry.get("model_id", ""))).strip()
    ):
        findings.append(
            {"code": "MODEL_ID_MISSING", "message": "model identity/version is required"}
        )

    if model_kind == "yolo" and waiver_active:
        if evaluation.get("evaluation_source") != "registry_candidate_experiment":
            findings.append(
                {
                    "code": "WAIVER_EVALUATION_SOURCE_INVALID",
                    "message": "maintainer-waiver publication must use the registered "
                    "candidate evidence",
                }
            )
        metrics = evaluation.get("metrics")
        if not isinstance(metrics, dict) or any(
            not isinstance(metrics.get(key), (int, float)) for key in YOLO_METRIC_THRESHOLDS
        ):
            findings.append(
                {
                    "code": "CANDIDATE_METRICS_MISSING",
                    "message": "registered candidate metrics are required",
                }
            )
        if not isinstance(evaluation.get("hard_negatives"), list) or not evaluation.get(
            "hard_negatives"
        ):
            findings.append(
                {
                    "code": "CANDIDATE_HARD_NEGATIVE_MISSING",
                    "message": "registered hard-negative evidence is required",
                }
            )
    elif model_kind == "yolo":
        if evaluation.get("schema_version") != "hct203-yolo-independent-evaluation/v1":
            findings.append(
                {
                    "code": "INDEPENDENT_REPORT_SCHEMA_INVALID",
                    "message": "formal YOLO independent-evaluation report is required",
                }
            )
        if evaluation.get("evaluation_scope") != "approved_real_fixed_set":
            findings.append(
                {
                    "code": "INDEPENDENT_SCOPE_MISSING",
                    "message": "YOLO evaluation must use approved_real_fixed_set",
                }
            )
        if evaluation.get("independent_evaluation") is not True:
            findings.append(
                {
                    "code": "INDEPENDENT_REVIEW_MISSING",
                    "message": "independent_evaluation=true is required",
                }
            )
        if evaluation.get("hard_negative_reviewed") is not True:
            findings.append(
                {
                    "code": "HARD_NEGATIVE_REVIEW_MISSING",
                    "message": "hard-negative review is required",
                }
            )
        metrics = evaluation.get("metrics")
        if not isinstance(metrics, dict) or not metrics:
            findings.append(
                {"code": "YOLO_METRICS_MISSING", "message": "independent YOLO metrics are required"}
            )
        else:
            for metric, threshold in YOLO_METRIC_THRESHOLDS.items():
                value = metrics.get(metric)
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    findings.append(
                        {
                            "code": "YOLO_METRIC_MISSING",
                            "message": f"missing numeric metric {metric}",
                        }
                    )
                elif not 0 <= float(value) <= 1 or float(value) < threshold:
                    findings.append(
                        {
                            "code": "YOLO_METRIC_BELOW_THRESHOLD",
                            "message": f"{metric} must be >= {threshold:.2f}",
                        }
                    )
        _require_sha256(evaluation.get("test_set_sha256"), "evaluation.test_set_sha256", findings)
        hard_negatives = evaluation.get("hard_negatives")
        if not isinstance(hard_negatives, list) or not hard_negatives:
            findings.append(
                {
                    "code": "HARD_NEGATIVE_EVIDENCE_MISSING",
                    "message": "hard-negative result records are required",
                }
            )
        elif not all(
            isinstance(item, dict) and isinstance(item.get("false_positive"), bool)
            for item in hard_negatives
        ) or any(item["false_positive"] for item in hard_negatives):
            findings.append(
                {
                    "code": "HARD_NEGATIVE_FALSE_POSITIVE",
                    "message": "all formal hard-negative cases must have no false positive",
                }
            )
        if evaluation.get("status") != "PASSED":
            findings.append(
                {
                    "code": "INDEPENDENT_EVALUATION_FAILED",
                    "message": "independent evaluation report did not pass",
                }
            )
    else:
        if evaluation.get("evaluation_scope") != "model_prediction_file":
            findings.append(
                {
                    "code": "BLIND_SCOPE_MISSING",
                    "message": "QLoRA evaluation must use a real prediction file",
                }
            )
        metrics = evaluation.get("metrics")
        if not isinstance(metrics, dict):
            findings.append(
                {"code": "BLIND_METRICS_MISSING", "message": "QLoRA blind metrics are required"}
            )
        else:
            for key in (
                "citation_valid_rate",
                "safety_refusal_rate",
                "unauthorized_field_leak_rate",
            ):
                if key not in metrics:
                    findings.append(
                        {"code": "BLIND_METRIC_MISSING", "message": f"missing metric {key}"}
                    )
            if metrics.get("unauthorized_field_leak_rate") != 0:
                findings.append(
                    {
                        "code": "UNAUTHORIZED_LEAK",
                        "message": "unauthorized field leak rate must be zero",
                    }
                )
        if evaluation.get("human_reviewed") is not True:
            findings.append(
                {
                    "code": "BLIND_HUMAN_REVIEW_MISSING",
                    "message": "blind sample human review is required",
                }
            )

    if rollback.get("rollback_tested") is not True:
        findings.append(
            {"code": "ROLLBACK_NOT_TESTED", "message": "rollback_tested=true is required"}
        )
    if (
        not str(rollback.get("previous_version", "")).strip()
        or rollback.get("restore_verified") is not True
    ):
        findings.append(
            {
                "code": "ROLLBACK_EVIDENCE_INCOMPLETE",
                "message": "previous version and restore verification are required",
            }
        )
    for field in ("evaluation_report_sha256", "threshold_report_sha256"):
        value = evaluation.get(field)
        if not _is_sha256(value):
            findings.append(
                {"code": "REPORT_HASH_MISSING", "message": f"{field} must be a SHA-256"}
            )

    passed = not findings
    return {
        "schema_version": "hct203-model-release-gate/v1",
        "model_kind": model_kind,
        "model_id": registry.get("model_id"),
        "current_registry_status": registry.get("release_status"),
        "fixed_set_hash": (
            dataset_gate.get("manifest_sha256")
            if not waiver_active
            else (training or {}).get("dataset_manifest_sha256")
        ),
        "release_mode": "MAINTAINER_WAIVER" if waiver_active else "FORMAL_EVIDENCE",
        "passed": passed,
        "decision": (
            "READY_FOR_MAINTAINER_WAIVER_PUBLICATION"
            if passed and waiver_active
            else "READY_FOR_R3_REVIEW"
            if passed
            else "BLOCK_MODEL_RELEASE"
        ),
        "findings": findings,
        "limitations": [
            "R3 readiness is not publication approval; a maintainer must review "
            "and change the registry.",
            "Weights, images, logs and blind predictions remain external artifacts.",
            "A maintainer waiver does not convert candidate metrics or false-positive "
            "samples into formal fixed-set evidence.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-kind", choices=("yolo", "qlora"), required=True)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--dataset-gate", type=Path)
    parser.add_argument("--evaluation", type=Path)
    parser.add_argument("--rollback", required=True, type=Path)
    parser.add_argument("--waiver", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        registry = _load(args.registry)
        waiver = _load(args.waiver) if args.waiver else None
        if args.evaluation:
            evaluation = _load(args.evaluation)
        elif waiver is not None and args.model_kind == "yolo":
            evaluation = candidate_evaluation_from_registry(registry)
        else:
            raise ValueError("EVALUATION_REQUIRED_UNLESS_YOLO_WAIVER")
        report = evaluate_release_readiness(
            model_kind=args.model_kind,
            registry=registry,
            dataset_gate=_load(args.dataset_gate) if args.dataset_gate else {},
            evaluation=evaluation,
            rollback=_load(args.rollback),
            waiver=waiver,
        )
        input_paths = {"registry": args.registry, "rollback": args.rollback}
        if args.dataset_gate:
            input_paths["dataset_gate"] = args.dataset_gate
        if args.evaluation:
            input_paths["evaluation"] = args.evaluation
        if args.waiver:
            input_paths["waiver"] = args.waiver
        report["input_sha256"] = {
            name: hashlib.sha256(path.read_bytes()).hexdigest()
            for name, path in input_paths.items()
        }
        report["report_sha256"] = _canonical_hash(report)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = {
            "schema_version": "hct203-model-release-gate/v1",
            "passed": False,
            "decision": "BLOCK_MODEL_RELEASE",
            "findings": [{"code": "INPUT_ERROR", "message": str(exc)}],
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
