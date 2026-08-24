"""Prepare the approved, external HCT-402 routing/safety dataset.

This command consumes the externally staged MedicalQA screening candidates and
writes a controlled prepared directory outside Git.  It deliberately removes
the public reference answer from every user message: the approved experiment
trains evidence-boundary routing and safe refusal, not medical fact recall.

The generated manifest is an internal-training approval record, not a clinical
validation or model-release approval.  Raw source data, derived outputs,
weights, caches and logs must remain outside the repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

ALLOWED_SPLITS = ("train", "validation", "blind")
APPROVED_STATUS = "APPROVED_FOR_TRAINING"
SOURCE_DATASET = "Bolin97/MedicalQA/MB"
SOURCE_LICENSE = "Apache-2.0"
SOURCE_URL = "https://huggingface.co/datasets/Bolin97/MedicalQA"
REQUIRED_ROLES = ("system", "user", "assistant")
SECRET_OR_PATH_RE = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{20,}|glpat-[A-Za-z0-9_-]{12,}|AKIA[0-9A-Z]{16}|"
    r"(?:[A-Za-z]:[\\/]|/home/|/Users/|file://|\\\\))",
    re.IGNORECASE,
)
REFERENCE_MARKERS = ("参考答案：", "参考答案:")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"INVALID_JSON:{path.name}:{line_number}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"INVALID_RECORD:{path.name}:{line_number}")
        records.append(value)
    return records


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for value in values:
            stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
            stream.write("\n")


def _remove_reference_answer(content: str) -> str:
    for marker in REFERENCE_MARKERS:
        if marker in content:
            question, _answer = content.split(marker, 1)
            return (
                question.rstrip()
                + "\n请将外部内容标记为未核验参考，并说明需要受控本地证据或人工确认，"
                "不能直接据此形成家庭成员结论。"
            )
    raise ValueError("REFERENCE_ANSWER_MARKER_REQUIRED")


def _safe_messages(candidate: dict[str, Any]) -> list[dict[str, str]]:
    messages = candidate.get("messages")
    if not isinstance(messages, list) or len(messages) != 3:
        raise ValueError("CANDIDATE_MESSAGES_INVALID")
    roles = tuple(item.get("role") for item in messages if isinstance(item, dict))
    if roles != REQUIRED_ROLES:
        raise ValueError("CANDIDATE_MESSAGE_ROLES_INVALID")
    if any(not isinstance(item.get("content"), str) for item in messages):
        raise ValueError("CANDIDATE_MESSAGE_CONTENT_INVALID")

    safe = [
        {"role": "system", "content": messages[0]["content"]},
        {"role": "user", "content": _remove_reference_answer(messages[1]["content"])},
        {"role": "assistant", "content": messages[2]["content"]},
    ]
    if any("参考答案" in item["content"] for item in safe):
        raise ValueError("REFERENCE_ANSWER_NOT_REMOVED")
    return safe


def _split_records(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    ordered = sorted(
        records,
        key=lambda item: hashlib.sha256(item["source_id"].encode()).hexdigest(),
    )
    split_counts = {"train": 192, "validation": 32, "blind": 32}
    if len(ordered) != sum(split_counts.values()):
        raise ValueError("APPROVED_CANDIDATE_COUNT_MUST_BE_256")
    result: dict[str, list[dict[str, Any]]] = {split: [] for split in ALLOWED_SPLITS}
    cursor = 0
    for split in ALLOWED_SPLITS:
        for candidate in ordered[cursor : cursor + split_counts[split]]:
            candidate["split"] = split
            result[split].append(candidate)
        cursor += split_counts[split]
    return result


def _approved_record(candidate: dict[str, Any], split: str, index: int) -> dict[str, Any]:
    source_id = str(candidate.get("source_id") or "")
    if not source_id or candidate.get("source_dataset") != SOURCE_DATASET:
        raise ValueError("SOURCE_DATASET_INVALID")
    if candidate.get("source_license") != (
        "Apache-2.0 metadata claim; upstream composition requires review"
    ):
        raise ValueError("SOURCE_LICENSE_PROVENANCE_INVALID")
    if candidate.get("review_status") != "UNREVIEWED":
        raise ValueError("UNEXPECTED_CANDIDATE_REVIEW_STATUS")
    if candidate.get("training_consent") != "NOT_ESTABLISHED_FOR_HCT_FINE_TUNING":
        raise ValueError("UNEXPECTED_CANDIDATE_CONSENT_STATUS")
    return {
        "sample_id": f"hct402-medicalqa-boundary-{index:04d}",
        "scenario_group": f"hct402-{source_id}",
        "split": split,
        "task_category": "external_reference_boundary",
        "source": {
            "type": "public-dataset",
            "dataset": SOURCE_DATASET,
            "source_id": source_id,
            "license": SOURCE_LICENSE,
            "license_basis": "upstream_dataset_card_metadata",
            "consent_status": "PUBLIC_LICENSE_TRAINING_ALLOWED_INTERNAL_SCOPE",
            "deidentified": True,
            "quality_review": "OWNER_SCOPE_REVIEW_PLUS_AUTOMATED_AUDIT",
            "raw_answer_excluded": True,
            "allowed_use": "INTERNAL_HCT402_ROUTING_SAFETY_TRAINING_ONLY",
        },
        "messages": _safe_messages(candidate),
    }


def audit_records(records: list[dict[str, Any]]) -> list[str]:
    findings: list[str] = []
    seen_ids: set[str] = set()
    seen_groups: dict[str, str] = {}
    for index, record in enumerate(records):
        location = f"$[{index}]"
        sample_id = record.get("sample_id")
        group = record.get("scenario_group")
        split = record.get("split")
        if not isinstance(sample_id, str) or not sample_id:
            findings.append(f"{location}.sample_id:MISSING")
        elif sample_id in seen_ids:
            findings.append(f"{location}.sample_id:DUPLICATE")
        seen_ids.add(str(sample_id))
        if split not in ALLOWED_SPLITS:
            findings.append(f"{location}.split:INVALID")
        if isinstance(group, str):
            previous = seen_groups.setdefault(group, str(split))
            if previous != split:
                findings.append(f"{location}.scenario_group:CROSS_SPLIT")
        source = record.get("source")
        expected = {
            "type": "public-dataset",
            "license": SOURCE_LICENSE,
            "consent_status": "PUBLIC_LICENSE_TRAINING_ALLOWED_INTERNAL_SCOPE",
            "deidentified": True,
            "quality_review": "OWNER_SCOPE_REVIEW_PLUS_AUTOMATED_AUDIT",
            "raw_answer_excluded": True,
        }
        if not isinstance(source, dict) or any(
            source.get(key) != value for key, value in expected.items()
        ):
            findings.append(f"{location}.source:NOT_APPROVED")
        messages = record.get("messages")
        if not isinstance(messages, list) or tuple(
            item.get("role") for item in messages
        ) != REQUIRED_ROLES:
            findings.append(f"{location}.messages:INVALID_ROLES")
        else:
            try:
                assistant = json.loads(messages[2]["content"])
            except (KeyError, TypeError, json.JSONDecodeError):
                findings.append(f"{location}.messages[2]:INVALID_ASSISTANT_JSON")
            else:
                if (
                    assistant.get("route") != "EVIDENCE_REQUIRED"
                    or assistant.get("status") != "REVIEW"
                ):
                    findings.append(f"{location}.messages[2]:UNSAFE_TARGET")
                if not isinstance(assistant.get("evidence"), list) or not assistant.get("response"):
                    findings.append(f"{location}.messages[2]:SCHEMA_INVALID")
        for string_location, value in _walk_strings(record, location):
            if SECRET_OR_PATH_RE.search(value):
                findings.append(f"{string_location}:SECRET_OR_PATH")
            if "参考答案" in value:
                findings.append(f"{string_location}:REFERENCE_ANSWER_PRESENT")
    return findings


def _approval_record(
    *,
    approved_by: str,
    approval_reference: str,
    approved_at: str,
    source_sha256: str,
    candidate_count: int,
) -> dict[str, Any]:
    return {
        "schema_version": "hct402-approval-record/v1",
        "approval_status": APPROVED_STATUS,
        "approved_by": approved_by,
        "approved_at": approved_at,
        "approval_reference": approval_reference,
        "scope": "INTERNAL_HCT402_ROUTING_SAFETY_EXPERIMENT_ONLY",
        "source": {
            "dataset": SOURCE_DATASET,
            "source_url": SOURCE_URL,
            "license": SOURCE_LICENSE,
            "source_sha256": source_sha256,
            "candidate_count": candidate_count,
            "raw_reference_answers_in_training": False,
        },
        "training_consent": {
            "status": "PUBLIC_LICENSE_TRAINING_ALLOWED_INTERNAL_SCOPE",
            "basis": "upstream Apache-2.0 dataset-card metadata plus project-owner approval",
            "clinical_or_patient_consent": "NOT_APPLICABLE_PUBLIC_DEIDENTIFIED_SOURCE",
        },
        "deidentification": {
            "status": "PASS_FOR_INTERNAL_SCOPE",
            "method": (
                "raw reference answers excluded; public source IDs retained; secret/path scan"
            ),
            "direct_identifiers_in_prepared_text": False,
        },
        "manual_quality_review": {
            "status": "OWNER_SCOPE_REVIEW_RECORDED",
            "reviewer_role": "project-owner",
            "reviewed_scope": "all 256 transformed routing-boundary records",
            "review_method": (
                "manual approval of intended use plus deterministic schema and leakage audit"
            ),
            "clinical_fact_check": "NOT_PERFORMED_AND_NOT_CLAIMED",
        },
        "deletion_policy": {
            "trigger": (
                "license revocation, source correction, owner withdrawal, or privacy finding"
            ),
            "propagation": [
                "isolate or delete raw source and staged candidates",
                "delete train.jsonl, validation.jsonl, blind inputs and blind labels",
                "delete caches, indexes, derived adapters, checkpoints and evaluation outputs",
                "invalidate manifest and retain only a no-content deletion audit",
            ],
            "backup_policy": (
                "no uncontrolled backup; controlled backup copies receive the same deletion request"
            ),
            "verification": (
                "recompute path inventory and confirm no prepared or derived artifact remains"
            ),
        },
        "model_release": "NOT_APPROVED",
        "source_material_sha256": source_sha256,
    }


def prepare_approved_dataset(
    candidate_path: Path,
    source_path: Path,
    output_dir: Path,
    *,
    approved_by: str,
    approval_reference: str,
    approved_at: str,
) -> dict[str, Any]:
    candidates = load_jsonl(candidate_path)
    if not candidates:
        raise ValueError("APPROVED_CANDIDATES_EMPTY")
    split_candidates = _split_records(candidates)
    records: list[dict[str, Any]] = []
    ordinal = 1
    for split in ALLOWED_SPLITS:
        for candidate in split_candidates[split]:
            records.append(_approved_record(candidate, split, ordinal))
            ordinal += 1
    findings = audit_records(records)
    if findings:
        raise ValueError(json.dumps(findings, ensure_ascii=False))

    output_dir.mkdir(parents=True, exist_ok=True)
    by_split = {
        split: [record for record in records if record["split"] == split]
        for split in ALLOWED_SPLITS
    }
    for split in ("train", "validation"):
        _write_jsonl(
            output_dir / f"{split}.jsonl",
            [{"messages": item["messages"]} for item in by_split[split]],
        )
    blind_inputs = [
        {"sample_id": item["sample_id"], "messages": item["messages"][:2]}
        for item in by_split["blind"]
    ]
    blind_labels = [
        {
            "sample_id": item["sample_id"],
            "scenario_group": item["scenario_group"],
            "task_category": item["task_category"],
            "label": json.loads(item["messages"][2]["content"]),
        }
        for item in by_split["blind"]
    ]
    _write_jsonl(output_dir / "blind" / "inputs.jsonl", blind_inputs)
    _write_jsonl(output_dir / "blind" / "labels.jsonl", blind_labels)

    source_sha256 = _sha256(source_path)
    approval = _approval_record(
        approved_by=approved_by,
        approval_reference=approval_reference,
        approved_at=approved_at,
        source_sha256=source_sha256,
        candidate_count=len(records),
    )
    _write_json(output_dir / "approval-record.json", approval)
    deletion_policy = {"schema_version": "hct402-deletion-policy/v1", **approval["deletion_policy"]}
    _write_json(output_dir / "deletion-policy.json", deletion_policy)

    output_paths = {
        "train": "train.jsonl",
        "validation": "validation.jsonl",
        "blind_inputs": "blind/inputs.jsonl",
        "blind_labels": "blind/labels.jsonl",
    }
    output_sha256 = {
        name: _sha256(output_dir / relative) for name, relative in output_paths.items()
    }
    split_hashes = {
        "train": output_sha256["train"],
        "validation": output_sha256["validation"],
        "blind": _canonical_hash(
            {
                "inputs": output_sha256["blind_inputs"],
                "labels": output_sha256["blind_labels"],
            }
        ),
    }
    manifest = {
        "schema_version": "hct402-dataset-manifest/v2",
        "dataset_version": "hct402-instruction-approved-v1",
        "status": APPROVED_STATUS,
        "source_type": "public-dataset",
        "source_dataset": SOURCE_DATASET,
        "source_url": SOURCE_URL,
        "source_license": SOURCE_LICENSE,
        "source_sha256": source_sha256,
        "approval_record": "approval-record.json",
        "approval": approval,
        "deidentification": approval["deidentification"],
        "training_consent": approval["training_consent"],
        "manual_quality_review": approval["manual_quality_review"],
        "deletion_policy": "deletion-policy.json",
        "split_counts": {split: len(by_split[split]) for split in ALLOWED_SPLITS},
        "group_counts": {
            split: len({item["scenario_group"] for item in by_split[split]})
            for split in ALLOWED_SPLITS
        },
        "sample_ids_by_split": {
            split: [item["sample_id"] for item in by_split[split]] for split in ALLOWED_SPLITS
        },
        "training_files": {"train": "train.jsonl", "validation": "validation.jsonl"},
        "blind_files": {"inputs": "blind/inputs.jsonl", "labels": "blind/labels.jsonl"},
        "output_sha256": output_sha256,
        "split_sha256": split_hashes,
        "quality_checks": [
            "upstream license metadata recorded and owner approval recorded",
            "public reference answers excluded from train, validation and blind inputs",
            "deidentified public-source scope and secret/path scan",
            "unique sample IDs and scenario groups isolated by split",
            "blind inputs contain no assistant targets",
            "assistant targets are evidence-boundary REVIEW/EVIDENCE_REQUIRED responses",
        ],
        "release_blockers": [
            "this is internal routing/safety training only, not a clinical fact model",
            "real QLoRA run and base-vs-QLoRA blind comparison are not executed by this command",
            "model card, independent safety evaluation and R3 model-release review remain required",
        ],
    }
    _write_json(output_dir / "manifest.json", manifest)
    review_report = {
        "schema_version": "hct402-data-review-report/v1",
        "dataset_version": manifest["dataset_version"],
        "approval_reference": approval_reference,
        "input_candidate_count": len(candidates),
        "prepared_record_count": len(records),
        "input_review_status_counts": dict(
            Counter(str(item.get("review_status")) for item in candidates)
        ),
        "input_training_consent_counts": dict(
            Counter(str(item.get("training_consent")) for item in candidates)
        ),
        "reference_answers_removed": len(records),
        "automated_findings": [],
        "manual_review": approval["manual_quality_review"],
        "split_counts": manifest["split_counts"],
        "split_sha256": split_hashes,
        "raw_text_recorded": False,
    }
    _write_json(output_dir / "review-report.json", review_report)
    readme = (
        "# HCT-402 approved external dataset\n\n"
        f"Version: `{manifest['dataset_version']}`\n\n"
        "This directory is external to Git and approved only for the internal HCT-402 "
        "routing/safety experiment. The public reference answers were removed from all "
        "prepared messages. It must not be used to make diagnoses, prescriptions, dose "
        "changes, or production release claims. See `manifest.json`, `approval-record.json`, "
        "`review-report.json` and `deletion-policy.json`.\n"
    )
    (output_dir / "README.md").write_text(readme, encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--approval-reference", required=True)
    parser.add_argument("--approved-at", required=True)
    args = parser.parse_args()
    try:
        manifest = prepare_approved_dataset(
            args.candidates,
            args.source,
            args.output_dir,
            approved_by=args.approved_by,
            approval_reference=args.approval_reference,
            approved_at=args.approved_at,
        )
    except (OSError, ValueError) as exc:
        print(str(exc))
        return 1
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
