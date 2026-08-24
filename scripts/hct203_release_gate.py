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
) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    if model_kind not in {"yolo", "qlora"}:
        findings.append(
            {"code": "INVALID_MODEL_KIND", "message": "model kind must be yolo or qlora"}
        )
    if (
        dataset_gate.get("decision") != "ALLOW_APPROVED_FIXED_SET"
        or dataset_gate.get("passed") is not True
    ):
        findings.append(
            {"code": "DATASET_GATE_BLOCKED", "message": "approved fixed-set gate did not pass"}
        )
    if registry.get("release_status") not in {"EXPERIMENTAL_UNRELEASED", "CANDIDATE_REVIEW"}:
        findings.append(
            {
                "code": "REGISTRY_STATUS_INVALID",
                "message": "registry must remain unreleased during this gate",
            }
        )
    training = registry.get("training")
    if not isinstance(training, dict) or training.get("dataset_status") != "APPROVED":
        findings.append(
            {
                "code": "REGISTRY_DATASET_NOT_APPROVED",
                "message": "registry training dataset is not APPROVED",
            }
        )
    if (
        not str(registry.get("model_id", "")).strip()
        or not str(registry.get("model_version", registry.get("model_id", ""))).strip()
    ):
        findings.append(
            {"code": "MODEL_ID_MISSING", "message": "model identity/version is required"}
        )

    if model_kind == "yolo":
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
        if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
            findings.append(
                {"code": "REPORT_HASH_MISSING", "message": f"{field} must be a SHA-256"}
            )

    passed = not findings
    return {
        "schema_version": "hct203-model-release-gate/v1",
        "model_kind": model_kind,
        "model_id": registry.get("model_id"),
        "current_registry_status": registry.get("release_status"),
        "passed": passed,
        "decision": "READY_FOR_R3_REVIEW" if passed else "BLOCK_MODEL_RELEASE",
        "findings": findings,
        "limitations": [
            "R3 readiness is not publication approval; a maintainer must review "
            "and change the registry.",
            "Weights, images, logs and blind predictions remain external artifacts.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-kind", choices=("yolo", "qlora"), required=True)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--dataset-gate", required=True, type=Path)
    parser.add_argument("--evaluation", required=True, type=Path)
    parser.add_argument("--rollback", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        report = evaluate_release_readiness(
            model_kind=args.model_kind,
            registry=_load(args.registry),
            dataset_gate=_load(args.dataset_gate),
            evaluation=_load(args.evaluation),
            rollback=_load(args.rollback),
        )
        report["input_sha256"] = {
            name: hashlib.sha256(path.read_bytes()).hexdigest()
            for name, path in (
                ("registry", args.registry),
                ("dataset_gate", args.dataset_gate),
                ("evaluation", args.evaluation),
                ("rollback", args.rollback),
            )
        }
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
