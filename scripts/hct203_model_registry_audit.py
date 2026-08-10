"""Audit an HCT-203 experimental vision-model registry record.

The registry contains metadata only. Model weights, images, labels and local paths
must stay outside Git. An experimental record may describe measured results, but it
must never be interpreted as a release approval.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")
FORBIDDEN_RELEASE_STATUSES = {"APPROVED", "PUBLISHED", "RELEASED", "PRODUCTION"}
ALLOWED_STATUSES = {"EXPERIMENTAL_UNRELEASED", "REVOKED", "UNAVAILABLE"}


@dataclass(frozen=True)
class AuditFinding:
    code: str
    location: str
    message: str


def _walk_strings(value: Any, location: str = "$") -> list[tuple[str, str]]:
    strings: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            strings.extend(_walk_strings(item, f"{location}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            strings.extend(_walk_strings(item, f"{location}[{index}]"))
    elif isinstance(value, str):
        strings.append((location, value))
    return strings


def _required(record: dict[str, Any], field: str, findings: list[AuditFinding]) -> Any:
    value = record.get(field)
    if value is None or value == "" or value == [] or value == {}:
        findings.append(AuditFinding("MISSING_FIELD", f"$.{field}", "required field is empty"))
    return value


def _require_sha256(value: Any, location: str, findings: list[AuditFinding]) -> None:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        findings.append(AuditFinding("INVALID_SHA256", location, "expected lowercase SHA-256"))


def audit_registry(record: dict[str, Any]) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    for field in (
        "schema_version",
        "model_id",
        "story",
        "issue",
        "release_status",
        "task",
        "training",
        "artifacts",
        "evaluation",
        "intended_uses",
        "prohibited_uses",
        "release_blockers",
        "fallback",
    ):
        _required(record, field, findings)

    status = record.get("release_status")
    if status in FORBIDDEN_RELEASE_STATUSES or status not in ALLOWED_STATUSES:
        findings.append(
            AuditFinding(
                "FORBIDDEN_RELEASE_STATUS",
                "$.release_status",
                "this registry accepts experimental, revoked or unavailable records only",
            )
        )

    training = record.get("training")
    if isinstance(training, dict):
        for field in (
            "dataset_version",
            "dataset_manifest_sha256",
            "configuration_sha256",
            "random_seed",
            "hardware",
            "dependencies",
            "reproducibility_status",
        ):
            _required(training, field, findings)
        _require_sha256(
            training.get("dataset_manifest_sha256"),
            "$.training.dataset_manifest_sha256",
            findings,
        )
        _require_sha256(
            training.get("configuration_sha256"),
            "$.training.configuration_sha256",
            findings,
        )
        if training.get("reproducibility_status") != "PARTIAL_UNTRACKED_ORIGINAL_CODE":
            findings.append(
                AuditFinding(
                    "MISSTATED_REPRODUCIBILITY",
                    "$.training.reproducibility_status",
                    "the original experiment had no tracked training-code commit",
                )
            )

    artifacts = record.get("artifacts")
    if isinstance(artifacts, dict):
        for field in ("weights_sha256", "weights_size_bytes", "stored_outside_git"):
            _required(artifacts, field, findings)
        _require_sha256(artifacts.get("weights_sha256"), "$.artifacts.weights_sha256", findings)
        if artifacts.get("stored_outside_git") is not True:
            findings.append(
                AuditFinding(
                    "WEIGHTS_NOT_EXTERNAL",
                    "$.artifacts.stored_outside_git",
                    "model weights must remain outside Git",
                )
            )

    evaluation = record.get("evaluation")
    if isinstance(evaluation, dict):
        test = evaluation.get("test")
        if not isinstance(test, dict):
            findings.append(AuditFinding("MISSING_TEST_METRICS", "$.evaluation.test", "missing"))
        else:
            for field in (
                "images",
                "ground_truth_instances",
                "precision",
                "recall",
                "map50",
                "map50_95",
                "confidence",
            ):
                _required(test, field, findings)
        hard_negatives = evaluation.get("hard_negatives")
        if not isinstance(hard_negatives, list) or not hard_negatives:
            findings.append(
                AuditFinding(
                    "MISSING_HARD_NEGATIVE_EVIDENCE",
                    "$.evaluation.hard_negatives",
                    "at least one difficult non-target result is required",
                )
            )
        elif not any(
            item.get("false_positive") is True
            for item in hard_negatives
            if isinstance(item, dict)
        ):
            findings.append(
                AuditFinding(
                    "HARD_NEGATIVE_FAILURE_HIDDEN",
                    "$.evaluation.hard_negatives",
                    "the known false positives must remain explicit",
                )
            )

    for location, value in _walk_strings(record):
        if WINDOWS_ABSOLUTE_RE.match(value) or value.startswith("\\\\"):
            findings.append(
                AuditFinding("LOCAL_PATH_LEAK", location, "absolute local path must be removed")
            )

    blockers = record.get("release_blockers")
    if not isinstance(blockers, list) or not blockers:
        findings.append(
            AuditFinding("MISSING_RELEASE_BLOCKERS", "$.release_blockers", "must not be empty")
        )
    return findings


def load_registry(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("model registry root must be a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True, type=Path)
    args = parser.parse_args()
    findings = audit_registry(load_registry(args.registry))
    result = {
        "status": "PASS" if not findings else "FAIL",
        "finding_count": len(findings),
        "findings": [finding.__dict__ for finding in findings],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
