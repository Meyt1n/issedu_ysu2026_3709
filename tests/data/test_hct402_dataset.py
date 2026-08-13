from __future__ import annotations

import copy
import json
from pathlib import Path

from hct402_prepare_dataset import audit_records, load_jsonl, prepare_dataset

FIXTURE = Path(__file__).parents[1] / "fixtures" / "hct402" / "starter_source.jsonl"


def finding_codes(records: list[dict]) -> set[str]:
    return {finding.code for finding in audit_records(records)}


def test_synthetic_starter_records_pass_audit() -> None:
    records = load_jsonl(FIXTURE)

    assert len(records) == 12
    assert audit_records(records) == []
    assert {record["split"] for record in records} == {"train", "validation", "blind"}
    assert {record["task_category"] for record in records} >= {
        "evidence_extraction",
        "conflict_resolution",
        "unknown_refusal",
        "medical_refusal",
    }


def test_rejects_cross_split_group_duplicate_id_and_non_synthetic_source() -> None:
    records = load_jsonl(FIXTURE)
    changed = copy.deepcopy(records)
    changed[1]["sample_id"] = changed[0]["sample_id"]
    changed[1]["split"] = "validation"
    changed[1]["source"]["type"] = "public-download"

    assert {
        "DUPLICATE_SAMPLE_ID",
        "GROUP_SPLIT_LEAK",
        "SOURCE_NOT_APPROVED",
    } <= finding_codes(changed)


def test_rejects_secret_and_absolute_path() -> None:
    records = load_jsonl(FIXTURE)
    changed = copy.deepcopy(records)
    changed[0]["messages"][1]["content"] += " file=C:\\private\\health.json sk-12345678901234567890"

    assert "SECRET_OR_PATH_LEAK" in finding_codes(changed)


def test_prepare_separates_training_and_blind_targets(tmp_path: Path) -> None:
    manifest = prepare_dataset(FIXTURE, tmp_path)

    assert manifest["status"] == "PREPARED_SYNTHETIC_NOT_RELEASED"
    assert manifest["split_counts"] == {"blind": 4, "train": 6, "validation": 2}
    assert manifest["group_counts"] == {"blind": 2, "train": 3, "validation": 1}
    assert len(manifest["sample_ids_by_split"]["blind"]) == 4
    assert set(manifest["output_sha256"]) == {
        "train.jsonl",
        "validation.jsonl",
        "blind/inputs.jsonl",
        "blind/labels.jsonl",
    }

    train = [
        json.loads(line)
        for line in (tmp_path / "train.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    validation = [
        json.loads(line)
        for line in (tmp_path / "validation.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    blind_inputs = [
        json.loads(line)
        for line in (tmp_path / "blind" / "inputs.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    blind_labels = [
        json.loads(line)
        for line in (tmp_path / "blind" / "labels.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    assert all(len(item["messages"]) == 3 for item in train + validation)
    assert all(len(item["messages"]) == 2 for item in blind_inputs)
    assert all(item["messages"][-1]["role"] != "assistant" for item in blind_inputs)
    assert len(blind_labels) == len(blind_inputs) == 4
    assert all("task_category" in item and "scenario_group" in item for item in blind_labels)


def test_prepared_manifest_has_no_local_paths_or_model_claims(tmp_path: Path) -> None:
    prepare_dataset(FIXTURE, tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    serialized = json.dumps(manifest, ensure_ascii=False)

    assert "C:\\" not in serialized
    assert "/home/" not in serialized
    assert "APPROVED" not in serialized
