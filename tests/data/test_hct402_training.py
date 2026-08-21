from __future__ import annotations

import json
from pathlib import Path

import pytest

from hct402_prepare_dataset import prepare_dataset
from hct402_train_qlora import (
    QLoRAConfig,
    assistant_only_projection,
    build_run_metadata,
    load_and_validate_prepared_dataset,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "hct402" / "starter_source.jsonl"


def test_qlora_config_records_effective_batch_and_validates() -> None:
    config = QLoRAConfig(base_model="Qwen/Qwen3-4B")
    config.validate()
    assert config.effective_batch_size == 8
    assert config.as_dict()["target_modules"] == ["q_proj", "k_proj", "v_proj", "o_proj"]


def test_training_rejects_synthetic_data_without_explicit_demo_flag(tmp_path: Path) -> None:
    prepare_dataset(FIXTURE, tmp_path)
    with pytest.raises(ValueError, match="TRAINING_DATA_NOT_APPROVED"):
        load_and_validate_prepared_dataset(tmp_path)


def test_training_manifest_and_assistant_only_projection(tmp_path: Path) -> None:
    prepare_dataset(FIXTURE, tmp_path)
    manifest, train, validation = load_and_validate_prepared_dataset(
        tmp_path,
        allow_synthetic_demo=True,
    )
    assert len(train) == 6
    assert len(validation) == 2
    projection = assistant_only_projection(train[0]["messages"])
    assert projection["prompt_messages"][-1]["role"] == "user"
    assert json.loads(projection["target"])["schema_version"] == "hct-llm-output/v1"

    metadata = build_run_metadata(
        tmp_path,
        manifest,
        QLoRAConfig(base_model="Qwen/Qwen3-4B"),
        status="DRY_RUN_VALIDATED",
    )
    serialized = str(metadata)
    assert metadata["evaluation_scope"] == "synthetic_fixture_only"
    assert metadata["artifacts_external_to_git"] is True
    assert "C:\\" not in serialized


def test_assistant_only_projection_rejects_multiple_targets() -> None:
    with pytest.raises(ValueError, match="ASSISTANT_TARGET_INVALID"):
        assistant_only_projection(
            [
                {"role": "user", "content": "question"},
                {"role": "assistant", "content": "one"},
                {"role": "assistant", "content": "two"},
            ]
        )
