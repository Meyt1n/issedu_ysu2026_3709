"""Prepare and audit the HCT-402 synthetic instruction-data starter set.

The script creates LlamaFactory-compatible train/validation JSONL files and a
separate blind-evaluation directory. It intentionally accepts synthetic data
only; real health data, model weights and training caches stay outside Git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ALLOWED_SPLITS = {"train", "validation", "blind"}
ALLOWED_ROUTES = {
    "DIRECT",
    "EVIDENCE_REQUIRED",
    "RISK_ONLY",
    "REFUSE",
    "URGENT_ESCALATE",
}
ALLOWED_STATUSES = {"MATCHED", "CONFLICT", "UNKNOWN", "REVIEW"}
REQUIRED_ROLES = ("system", "user", "assistant")
SECRET_OR_PATH_RE = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{20,}|glpat-[A-Za-z0-9_-]{12,}|AKIA[0-9A-Z]{16}|"
    r"(?:[A-Za-z]:[\\/]|/home/|/Users/|file://|\\\\))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Finding:
    code: str
    location: str
    message: str


def _walk_strings(value: Any, location: str = "$") -> list[tuple[str, str]]:
    if isinstance(value, dict):
        return [
            item
            for key, nested in value.items()
            for item in _walk_strings(nested, f"{location}.{key}")
        ]
    if isinstance(value, list):
        return [
            item
            for index, nested in enumerate(value)
            for item in _walk_strings(nested, f"{location}[{index}]")
        ]
    if isinstance(value, str):
        return [(location, value)]
    return []


def _required(
    record: dict[str, Any], field: str, findings: list[Finding], location: str = "$"
) -> Any:
    value = record.get(field)
    if value is None or value == "":
        findings.append(Finding("MISSING_FIELD", f"{location}.{field}", "required field is empty"))
    return value


def _parse_json_content(
    content: Any, location: str, findings: list[Finding]
) -> dict[str, Any] | None:
    if not isinstance(content, str):
        findings.append(
            Finding("INVALID_MESSAGE_CONTENT", location, "message content must be text")
        )
        return None
    try:
        value = json.loads(content)
    except json.JSONDecodeError:
        findings.append(
            Finding("INVALID_ASSISTANT_JSON", location, "assistant content must be JSON")
        )
        return None
    if not isinstance(value, dict):
        findings.append(
            Finding("INVALID_ASSISTANT_SCHEMA", location, "assistant content must be an object")
        )
        return None
    return value


def audit_records(records: list[dict[str, Any]]) -> list[Finding]:
    findings: list[Finding] = []
    seen_ids: set[str] = set()
    group_splits: dict[str, str] = {}

    for index, record in enumerate(records):
        location = f"$[{index}]"
        if not isinstance(record, dict):
            findings.append(Finding("INVALID_RECORD", location, "record must be an object"))
            continue

        sample_id = _required(record, "sample_id", findings, location)
        group = _required(record, "scenario_group", findings, location)
        split = _required(record, "split", findings, location)
        _required(record, "task_category", findings, location)
        source = _required(record, "source", findings, location)
        messages = _required(record, "messages", findings, location)

        if isinstance(sample_id, str):
            if sample_id in seen_ids:
                findings.append(Finding("DUPLICATE_SAMPLE_ID", f"{location}.sample_id", sample_id))
            seen_ids.add(sample_id)
        if split not in ALLOWED_SPLITS:
            findings.append(Finding("INVALID_SPLIT", f"{location}.split", str(split)))
        if isinstance(group, str) and split in ALLOWED_SPLITS:
            previous = group_splits.setdefault(group, split)
            if previous != split:
                findings.append(
                    Finding(
                        "GROUP_SPLIT_LEAK",
                        f"{location}.scenario_group",
                        f"group already assigned to {previous}, cannot use {split}",
                    )
                )

        if not isinstance(source, dict):
            findings.append(
                Finding("INVALID_SOURCE", f"{location}.source", "source must be an object")
            )
        else:
            expected_source = {
                "type": "synthetic",
                "license": "internal-teaching-fixture",
                "consent_status": "NOT_APPLICABLE_SYNTHETIC",
                "deidentified": True,
                "quality_review": "SYNTHETIC_REVIEWED",
            }
            for key, expected in expected_source.items():
                if source.get(key) != expected:
                    findings.append(
                        Finding(
                            "SOURCE_NOT_APPROVED",
                            f"{location}.source.{key}",
                            f"expected {expected!r}",
                        )
                    )

        assistant_output: dict[str, Any] | None = None
        if not isinstance(messages, list):
            findings.append(Finding("INVALID_MESSAGES", f"{location}.messages", "must be a list"))
        else:
            roles = [item.get("role") for item in messages if isinstance(item, dict)]
            if tuple(roles) != REQUIRED_ROLES:
                findings.append(
                    Finding("INVALID_MESSAGE_ROLES", f"{location}.messages", str(roles))
                )
            if len(messages) == 3 and isinstance(messages[2], dict):
                assistant_output = _parse_json_content(
                    messages[2].get("content"),
                    f"{location}.messages[2].content",
                    findings,
                )

        if assistant_output is not None:
            route = assistant_output.get("route")
            status = assistant_output.get("status")
            for field in ("schema_version", "route", "status", "evidence", "response"):
                _required(assistant_output, field, findings, f"{location}.messages[2].content")
            if route not in ALLOWED_ROUTES:
                findings.append(
                    Finding("INVALID_ROUTE", f"{location}.messages[2].content.route", str(route))
                )
            if status not in ALLOWED_STATUSES:
                findings.append(
                    Finding("INVALID_STATUS", f"{location}.messages[2].content.status", str(status))
                )
            if not isinstance(assistant_output.get("evidence"), list):
                findings.append(
                    Finding(
                        "INVALID_EVIDENCE",
                        f"{location}.messages[2].content.evidence",
                        "evidence must be a list",
                    )
                )

        for string_location, value in _walk_strings(record, location):
            if SECRET_OR_PATH_RE.search(value):
                findings.append(
                    Finding(
                        "SECRET_OR_PATH_LEAK",
                        string_location,
                        "secret or local path pattern found",
                    )
                )

    return findings


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON at line {line_number}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"record at line {line_number} must be an object")
        records.append(value)
    return records


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for value in values:
            stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
            stream.write("\n")


def prepare_dataset(source_path: Path, output_dir: Path) -> dict[str, Any]:
    records = load_jsonl(source_path)
    findings = audit_records(records)
    if findings:
        raise ValueError(json.dumps([finding.__dict__ for finding in findings], ensure_ascii=False))

    output_dir.mkdir(parents=True, exist_ok=True)
    split_records = {
        split: [record for record in records if record["split"] == split]
        for split in sorted(ALLOWED_SPLITS)
    }

    training_files: dict[str, str] = {}
    for split in ("train", "validation"):
        path = output_dir / f"{split}.jsonl"
        _write_jsonl(path, [{"messages": record["messages"]} for record in split_records[split]])
        training_files[split] = path.name

    blind_inputs = [
        {"messages": record["messages"][:2]} for record in split_records["blind"]
    ]
    blind_labels = []
    for record in split_records["blind"]:
        assistant = json.loads(record["messages"][2]["content"])
        blind_labels.append({"sample_id": record["sample_id"], "label": assistant})
    _write_jsonl(output_dir / "blind" / "inputs.jsonl", blind_inputs)
    _write_jsonl(output_dir / "blind" / "labels.jsonl", blind_labels)

    manifest = {
        "schema_version": "hct402-dataset-manifest/v1",
        "dataset_version": "hct402-instruction-starter-v1",
        "status": "PREPARED_SYNTHETIC_NOT_RELEASED",
        "source_sha256": _sha256(source_path),
        "source_type": "synthetic",
        "license": "internal-teaching-fixture",
        "split_counts": {split: len(split_records[split]) for split in sorted(ALLOWED_SPLITS)},
        "group_counts": {
            split: len({record["scenario_group"] for record in split_records[split]})
            for split in sorted(ALLOWED_SPLITS)
        },
        "sample_ids_by_split": {
            split: [record["sample_id"] for record in split_records[split]]
            for split in sorted(ALLOWED_SPLITS)
        },
        "training_files": training_files,
        "blind_files": {"inputs": "blind/inputs.jsonl", "labels": "blind/labels.jsonl"},
        "quality_checks": [
            "synthetic source and training-consent marker",
            "unique sample IDs",
            "scenario groups do not cross splits",
            "blind inputs contain no assistant targets",
            "secret and absolute-path scan",
        ],
        "release_blockers": [
            "starter fixture is synthetic and intentionally small",
            "no human quality review or production data approval",
            "no baseline versus QLoRA blind evaluation",
            "no model card or approved weights",
        ],
    }
    manifest["output_sha256"] = {
        relative_path: _sha256(output_dir / relative_path)
        for relative_path in (
            "train.jsonl",
            "validation.jsonl",
            "blind/inputs.jsonl",
            "blind/labels.jsonl",
        )
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        manifest = prepare_dataset(args.source, args.output_dir)
    except (OSError, ValueError) as exc:
        print(str(exc))
        return 1
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
