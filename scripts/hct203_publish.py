"""Create an auditable HCT-203 auxiliary-model publication record.

Publication is deliberately a separate, explicit step after the machine gate
and R3 review. The command writes only a small, path-free manifest; it does not
copy weights, change the model registry in-place, call the API, or enable the
family runtime. Applying the manifest to the existing model-version-binding
API remains a controlled deployment action.
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_sha(value: Any, field: str, findings: list[dict[str, str]]) -> None:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        findings.append({"code": "HASH_INVALID", "message": f"{field} must be a lowercase SHA-256"})


def prepare_publication(
    *,
    registry: dict[str, Any],
    machine_gate: dict[str, Any],
    r3_review: dict[str, Any] | None,
    rollback: dict[str, Any],
    waiver: dict[str, Any] | None = None,
) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    waiver_active = waiver is not None
    expected_machine_decision = (
        "READY_FOR_MAINTAINER_WAIVER_PUBLICATION" if waiver_active else "READY_FOR_R3_REVIEW"
    )
    if (
        machine_gate.get("passed") is not True
        or machine_gate.get("decision") != expected_machine_decision
    ):
        findings.append(
            {"code": "MACHINE_GATE_BLOCKED", "message": "machine release gate is not ready"}
        )
    if waiver_active:
        if (
            waiver.get("passed") is not True
            or waiver.get("decision") != "MAINTAINER_WAIVER_APPROVED"
        ):
            findings.append(
                {
                    "code": "MAINTAINER_WAIVER_BLOCKED",
                    "message": "maintainer waiver is not approved",
                }
            )
    elif (
        r3_review is None
        or r3_review.get("passed") is not True
        or r3_review.get("decision") != "R3_APPROVED"
    ):
        findings.append({"code": "R3_REVIEW_BLOCKED", "message": "human R3 review is not approved"})
    if registry.get("release_status") not in {"EXPERIMENTAL_UNRELEASED", "CANDIDATE_REVIEW"}:
        findings.append(
            {
                "code": "REGISTRY_STATUS_INVALID",
                "message": "registry must be an unreleased candidate",
            }
        )
    model_id = registry.get("model_id")
    if not isinstance(model_id, str) or not model_id.strip():
        findings.append({"code": "MODEL_ID_MISSING", "message": "registry model_id is required"})
    artifacts = registry.get("artifacts")
    if not isinstance(artifacts, dict):
        findings.append({"code": "ARTIFACTS_MISSING", "message": "registry artifacts are required"})
        artifacts = {}
    _require_sha(artifacts.get("weights_sha256"), "artifacts.weights_sha256", findings)
    _require_sha(
        machine_gate.get("input_sha256", {}).get("registry"), "machine_gate.registry_hash", findings
    )
    if not waiver_active and r3_review is not None:
        _require_sha(
            r3_review.get("input_sha256", {}).get("machine_gate"),
            "r3_review.machine_gate_hash",
            findings,
        )
    _require_sha(machine_gate.get("fixed_set_hash"), "machine_gate.fixed_set_hash", findings)
    _require_sha(machine_gate.get("report_sha256"), "machine_gate.report_sha256", findings)
    if waiver_active:
        _require_sha(waiver.get("report_sha256"), "waiver.report_sha256", findings)
    elif r3_review is not None:
        _require_sha(r3_review.get("report_sha256"), "r3_review.report_sha256", findings)
    if (
        rollback.get("restore_verified") is not True
        or not str(rollback.get("previous_version", "")).strip()
    ):
        findings.append(
            {
                "code": "ROLLBACK_BLOCKED",
                "message": "verified rollback to a previous version is required",
            }
        )
    if model_id and machine_gate.get("model_id") not in {None, model_id}:
        findings.append(
            {"code": "MODEL_ID_MISMATCH", "message": "machine gate and registry model_id differ"}
        )

    passed = not findings
    authority = "MAINTAINER_WAIVER" if waiver_active else "R3_REVIEW"
    approval_hash = (
        waiver.get("report_sha256")
        if waiver_active
        else r3_review.get("report_sha256")
        if r3_review is not None
        else None
    )
    binding_safety_thresholds = {
        "hct203_publication_status": "PUBLISHED_AUXILIARY_ONLY",
        "hct203_release_authority": authority,
        "hct203_machine_gate_sha256": machine_gate.get("report_sha256"),
        "hct203_waiver_sha256": approval_hash if waiver_active else None,
        "hct203_r3_review_sha256": approval_hash if not waiver_active else None,
    }
    return {
        "schema_version": "hct203-model-publication/v1",
        "publication_status": "PUBLISHED_AUXILIARY_ONLY" if passed else "BLOCKED",
        "decision": "MODEL_PUBLISHED" if passed else "MODEL_PUBLICATION_BLOCKED",
        "release_authority": authority,
        "model_id": model_id,
        "weights_sha256": artifacts.get("weights_sha256"),
        "dataset_version": registry.get("training", {}).get("dataset_version"),
        "fixed_set_hash": machine_gate.get("fixed_set_hash"),
        "fixed_set_scope": (
            "candidate_experiment_waived" if waiver_active else "approved_real_fixed_set"
        ),
        "machine_gate_decision": machine_gate.get("decision"),
        "r3_decision": r3_review.get("decision") if r3_review is not None else None,
        "waiver_decision": waiver.get("decision") if waiver_active else None,
        "previous_version": rollback.get("previous_version"),
        "binding_safety_thresholds": binding_safety_thresholds,
        "runtime_scope": {
            "mode": "AUXILIARY_ONLY",
            "enabled_by_default": False,
            "manual_confirmation_required": True,
            "fallback": "vision_model_version=unavailable",
            "prohibited": [
                "medicine identity decisions",
                "override OCR or barcode evidence",
                "diagnosis, prescription or medication changes",
            ],
        },
        "passed": passed,
        "findings": findings,
        "limitations": [
            "This manifest does not copy weights or activate the household runtime.",
            "The weights remain in the controlled artifact store and must be verified "
            "by SHA-256 at deployment.",
        ],
    }


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name}: JSON root must be an object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--machine-gate", required=True, type=Path)
    parser.add_argument("--rollback", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    approval = parser.add_mutually_exclusive_group(required=True)
    approval.add_argument("--r3-review", type=Path)
    approval.add_argument("--waiver", type=Path)
    args = parser.parse_args()
    try:
        machine_gate = _load(args.machine_gate)
        r3_review = _load(args.r3_review) if args.r3_review else None
        waiver = _load(args.waiver) if args.waiver else None
        rollback = _load(args.rollback)
        publication = prepare_publication(
            registry=_load(args.registry),
            machine_gate=machine_gate,
            r3_review=r3_review,
            rollback=rollback,
            waiver=waiver,
        )
        input_paths = {
            "registry": args.registry,
            "machine_gate": args.machine_gate,
            "rollback": args.rollback,
        }
        if args.r3_review:
            input_paths["r3_review"] = args.r3_review
        if args.waiver:
            input_paths["waiver"] = args.waiver
        publication["input_sha256"] = {name: _sha256(path) for name, path in input_paths.items()}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        publication = {
            "schema_version": "hct203-model-publication/v1",
            "publication_status": "BLOCKED",
            "decision": "MODEL_PUBLICATION_BLOCKED",
            "passed": False,
            "findings": [{"code": "INPUT_ERROR", "message": str(exc)}],
        }
    payload = json.dumps(publication, ensure_ascii=False, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if publication.get("passed") is True else 1


if __name__ == "__main__":
    sys.exit(main())
