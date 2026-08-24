from __future__ import annotations

import json
from pathlib import Path

import pytest

from hct402_prepare_approved_dataset import prepare_approved_dataset
from hct402_train_qlora import load_and_validate_prepared_dataset


def _candidate(index: int) -> dict:
    source_id = f"medicalqa-mb-test-{index:04d}"
    return {
        "source_id": source_id,
        "source_dataset": "Bolin97/MedicalQA/MB",
        "source_license": "Apache-2.0 metadata claim; upstream composition requires review",
        "review_status": "UNREVIEWED",
        "training_consent": "NOT_ESTABLISHED_FOR_HCT_FINE_TUNING",
        "messages": [
            {
                "role": "system",
                "content": "外部医学问答只能作为未核验参考，不做诊断、处方或个体化用药判断。",
            },
            {
                "role": "user",
                "content": (
                    f"问题 {index}：请判断外部资料是否可以直接形成家庭成员结论。"
                    "参考答案：这是一段不应进入训练文本的外部答案。"
                    "请标记为未核验参考并要求受控证据。"
                ),
            },
            {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "schema_version": "hct-llm-output/v1",
                        "route": "EVIDENCE_REQUIRED",
                        "status": "REVIEW",
                        "fields": {},
                        "evidence": [{"source_id": source_id, "supports": []}],
                        "response": "外部内容未核验，需要受控证据或人工确认。",
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }


def _write_candidates(path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for index in range(256):
            stream.write(json.dumps(_candidate(index), ensure_ascii=False) + "\n")


def test_prepare_approved_dataset_records_scope_and_split_hashes(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates.jsonl"
    source = tmp_path / "MB.json"
    prepared = tmp_path / "prepared"
    _write_candidates(candidates)
    source.write_bytes(b"public source bytes for hash binding")

    manifest = prepare_approved_dataset(
        candidates,
        source,
        prepared,
        approved_by="project-owner",
        approval_reference="test-approval",
        approved_at="2026-08-24",
    )

    assert manifest["status"] == "APPROVED_FOR_TRAINING"
    assert manifest["split_counts"] == {"train": 192, "validation": 32, "blind": 32}
    assert manifest["approval"]["model_release"] == "NOT_APPROVED"
    assert manifest["approval"]["manual_quality_review"]["status"] == "OWNER_SCOPE_REVIEW_RECORDED"
    assert set(manifest["split_sha256"]) == {"train", "validation", "blind"}
    train_text = (prepared / "train.jsonl").read_text(encoding="utf-8")
    blind_text = (prepared / "blind" / "inputs.jsonl").read_text(encoding="utf-8")
    assert "参考答案" not in train_text
    assert "参考答案" not in blind_text
    assert all(
        message["role"] != "assistant"
        for row in (json.loads(line) for line in blind_text.splitlines())
        for message in row["messages"]
    )


def test_approved_training_rejects_tampered_split_hash(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates.jsonl"
    source = tmp_path / "MB.json"
    prepared = tmp_path / "prepared"
    _write_candidates(candidates)
    source.write_bytes(b"public source bytes for hash binding")
    prepare_approved_dataset(
        candidates,
        source,
        prepared,
        approved_by="project-owner",
        approval_reference="test-approval",
        approved_at="2026-08-24",
    )
    with (prepared / "train.jsonl").open("a", encoding="utf-8") as stream:
        stream.write("\n")

    with pytest.raises(ValueError, match="OUTPUT_HASH_MISMATCH:train"):
        load_and_validate_prepared_dataset(prepared)
