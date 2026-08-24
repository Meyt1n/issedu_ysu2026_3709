from __future__ import annotations

import json
from pathlib import Path

import pytest

from hct203_train_yolo import (
    YOLOTrainingConfig,
    build_run_manifest,
    load_dataset_config,
)


def _dataset_yaml(tmp_path: Path, *, include_test: bool = True) -> Path:
    for split in ("train", "val", "test"):
        (tmp_path / split).mkdir()
        (tmp_path / split / "sample.jpg").write_bytes(b"synthetic-image")
    config: dict[str, object] = {
        "path": ".",
        "train": "train",
        "val": "val",
        "names": ["package"],
    }
    if include_test:
        config["test"] = "test"
    path = tmp_path / "dataset.yaml"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def test_yolo_dataset_config_is_path_free_and_counts_splits(tmp_path: Path) -> None:
    dataset_yaml = _dataset_yaml(tmp_path)
    metadata = load_dataset_config(dataset_yaml, require_test=True)
    assert metadata["class_count"] == 1
    assert metadata["split_counts"] == {"train": 1, "val": 1, "test": 1}
    assert metadata["paths_omitted"] is True

    manifest = build_run_manifest(
        dataset_yaml,
        metadata,
        YOLOTrainingConfig(base_model="yolo11n.pt"),
        status="DRY_RUN_VALIDATED",
    )
    assert manifest["release_status"] == "EXPERIMENTAL_UNRELEASED"
    assert str(tmp_path) not in json.dumps(manifest)


def test_yolo_training_requires_independent_test_when_requested(tmp_path: Path) -> None:
    dataset_yaml = _dataset_yaml(tmp_path, include_test=False)
    with pytest.raises(ValueError, match="DATASET_TEST_SPLIT_REQUIRED"):
        load_dataset_config(dataset_yaml, require_test=True)


def test_yolo_config_rejects_invalid_confidence() -> None:
    with pytest.raises(ValueError, match="CONFIDENCE_INVALID"):
        YOLOTrainingConfig(confidence=0).validate()
