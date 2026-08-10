"""Audit an HCT-203 experimental vision-model registry record.

The registry contains metadata only. Model weights, images, labels and local paths
must stay outside Git. An experimental record may describe measured results, but it
must never be interpreted as a release approval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")
FORBIDDEN_RELEASE_STATUSES = {"APPROVED", "PUBLISHED", "RELEASED", "PRODUCTION"}
ALLOWED_STATUSES = {"EXPERIMENTAL_UNRELEASED", "REVOKED", "UNAVAILABLE"}
EXPECTED_HARD_NEGATIVE_IDS = frozenset(
    {
        "hct201-v1-hard-negative-00-90370b074a64",
        "hct201-v1-hard-negative-01-440b01bd90f1",
    }
)


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


def _is_local_absolute_path(value: str) -> bool:
    lowered = value.lower()
    return (
        WINDOWS_ABSOLUTE_RE.match(value) is not None
        or value.startswith("\\\\")
        or value.startswith("/")
        or lowered.startswith("file://")
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_weights(record: dict[str, Any], weights_path: Path) -> list[AuditFinding]:
    """Compare a controlled external weights file with the registered digest."""
    if not weights_path.is_file():
        return [
            AuditFinding(
                "WEIGHTS_UNAVAILABLE",
                "$.artifacts.weights_sha256",
                "external weights file is unavailable",
            )
        ]
    expected = record.get("artifacts", {}).get("weights_sha256")
    expected_size = record.get("artifacts", {}).get("weights_size_bytes")
    actual_size = weights_path.stat().st_size
    if actual_size != expected_size:
        return [
            AuditFinding(
                "WEIGHTS_SIZE_MISMATCH",
                "$.artifacts.weights_size_bytes",
                f"registered size does not match external artifact; actual={actual_size}",
            )
        ]
    actual = _sha256_file(weights_path)
    if actual != expected:
        return [
            AuditFinding(
                "WEIGHTS_HASH_MISMATCH",
                "$.artifacts.weights_sha256",
                f"registered digest does not match external artifact; actual={actual}",
            )
        ]
    return []


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
        for field in (
            "evaluation_report_sha256",
            "threshold_report_sha256",
            "benchmark_cpu_report_sha256",
            "benchmark_gpu_report_sha256",
        ):
            _require_sha256(artifacts.get(field), f"$.artifacts.{field}", findings)
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
        expected_ids = evaluation.get("expected_hard_negative_sample_ids")
        hard_negatives = evaluation.get("hard_negatives")
        if not isinstance(hard_negatives, list) or not hard_negatives:
            findings.append(
                AuditFinding(
                    "MISSING_HARD_NEGATIVE_EVIDENCE",
                    "$.evaluation.hard_negatives",
                    "at least one difficult non-target result is required",
                )
            )
        else:
            actual_ids = [
                item.get("sample_id") for item in hard_negatives if isinstance(item, dict)
            ]
            if (
                not isinstance(expected_ids, list)
                or len(expected_ids) != len(set(expected_ids))
                or set(expected_ids) != EXPECTED_HARD_NEGATIVE_IDS
                or set(actual_ids) != EXPECTED_HARD_NEGATIVE_IDS
                or len(actual_ids) != len(set(actual_ids))
            ):
                findings.append(
                    AuditFinding(
                        "HARD_NEGATIVE_SET_MISMATCH",
                        "$.evaluation.hard_negatives",
                        "hard-negative records must exactly match the fixed expected sample IDs",
                    )
                )
        performance = evaluation.get("performance")
        if not isinstance(performance, dict) or performance.get("status") != "MEASURED":
            findings.append(
                AuditFinding(
                    "PERFORMANCE_NOT_MEASURED",
                    "$.evaluation.performance",
                    "CPU/GPU latency and resource evidence are required for this record",
                )
            )
        else:
            for mode in ("cpu", "gpu"):
                metrics = performance.get(mode)
                if not isinstance(metrics, dict):
                    findings.append(
                        AuditFinding(
                            "MISSING_PERFORMANCE_MODE",
                            f"$.evaluation.performance.{mode}",
                            "missing benchmark metrics",
                        )
                    )
                    continue
                for field in (
                    "images",
                    "latency_p95_ms",
                    "throughput_images_per_second",
                    "peak_memory_bytes",
                ):
                    _required(metrics, field, findings)
            if not all(
                item.get("false_positive") is True
                and isinstance(item.get("confidence"), int | float)
                for item in hard_negatives
                if isinstance(item, dict)
            ):
                findings.append(
                    AuditFinding(
                        "HARD_NEGATIVE_FAILURE_HIDDEN",
                        "$.evaluation.hard_negatives",
                        "every fixed hard-negative failure and confidence must remain explicit",
                    )
                )

    for location, value in _walk_strings(record):
        if _is_local_absolute_path(value):
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
    parser.add_argument(
        "--weights",
        type=Path,
        help="optional controlled external weights file for content hash verification",
    )
    args = parser.parse_args()
    record = load_registry(args.registry)
    findings = audit_registry(record)
    artifact_findings: list[AuditFinding] = []
    if args.weights is not None:
        artifact_findings = verify_weights(record, args.weights)
        findings.extend(artifact_findings)
    if args.weights is None:
        artifact_verification = "NOT_REQUESTED"
    elif artifact_findings:
        artifact_verification = "FAILED"
    else:
        artifact_verification = "VERIFIED"
    result = {
        "status": "PASS" if not findings else "FAIL",
        "effective_model_status": record.get("release_status") if not findings else "UNAVAILABLE",
        "artifact_verification": artifact_verification,
        "finding_count": len(findings),
        "findings": [finding.__dict__ for finding in findings],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
