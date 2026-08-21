"""Run a reproducible HCT-203 YOLO training experiment outside Git.

This launcher validates the external dataset YAML, pins the training
configuration and delegates the actual training to Ultralytics.  Images,
labels, weights, caches and logs must stay in the supplied external output
directory.  The generated run manifest intentionally omits local paths.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


@dataclass(frozen=True)
class YOLOTrainingConfig:
    base_model: str = "yolo11n.pt"
    epochs: int = 50
    image_size: int = 640
    batch_size: int = 16
    device: str = "0"
    workers: int = 4
    seed: int = 42
    confidence: float = 0.25
    deterministic: bool = True

    def validate(self) -> None:
        if not self.base_model.strip():
            raise ValueError("BASE_MODEL_REQUIRED")
        if self.epochs < 1 or self.image_size < 32 or self.batch_size < 1:
            raise ValueError("TRAINING_HYPERPARAMETER_INVALID")
        if self.workers < 0 or self.seed < 0:
            raise ValueError("RESOURCE_OR_SEED_INVALID")
        if not 0 < self.confidence <= 1:
            raise ValueError("CONFIDENCE_INVALID")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("DATASET_CONFIG_DEPENDENCY_MISSING: install pyyaml") from exc
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("DATASET_CONFIG_INVALID")
    return value


def _resolve_split(config_path: Path, root: Path, value: Any, split: str) -> list[Path]:
    values = value if isinstance(value, list) else [value]
    resolved: list[Path] = []
    for item in values:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"DATASET_SPLIT_INVALID:{split}")
        candidate = Path(item)
        if not candidate.is_absolute():
            candidate = root / candidate
        if not candidate.exists():
            raise ValueError(f"DATASET_SPLIT_MISSING:{split}")
        resolved.append(candidate.resolve())
    return resolved


def _count_images(path: Path) -> int:
    if path.is_file():
        if path.suffix.lower() in IMAGE_SUFFIXES:
            return 1
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return sum(
        1
        for item in path.rglob("*")
        if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES
    )


def load_dataset_config(path: Path, *, require_test: bool = False) -> dict[str, Any]:
    """Validate a YOLO dataset YAML and return path-free audit metadata."""
    path = path.resolve()
    if not path.is_file():
        raise ValueError("DATASET_YAML_MISSING")
    raw = _load_yaml(path)
    root_value = raw.get("path", ".")
    root = Path(root_value) if isinstance(root_value, str) else Path(".")
    if not root.is_absolute():
        root = path.parent / root
    split_paths: dict[str, list[Path]] = {}
    for split in ("train", "val"):
        if split not in raw:
            raise ValueError(f"DATASET_SPLIT_REQUIRED:{split}")
        split_paths[split] = _resolve_split(path, root, raw[split], split)
    if "test" in raw:
        split_paths["test"] = _resolve_split(path, root, raw["test"], "test")
    elif require_test:
        raise ValueError("DATASET_TEST_SPLIT_REQUIRED")

    names = raw.get("names")
    if isinstance(names, list):
        class_count = len(names)
    elif isinstance(names, dict):
        class_count = len(names)
    else:
        class_count = int(raw.get("nc") or 0)
    if class_count < 1:
        raise ValueError("DATASET_CLASSES_REQUIRED")
    counts = {
        split: sum(_count_images(item) for item in paths)
        for split, paths in split_paths.items()
    }
    if any(counts[split] < 1 for split in ("train", "val")):
        raise ValueError("DATASET_SPLIT_EMPTY")
    return {
        "schema_version": "hct203-dataset-audit/v1",
        "dataset_yaml_sha256": sha256_file(path),
        "class_count": class_count,
        "split_counts": counts,
        "has_independent_test": "test" in split_paths,
        "paths_omitted": True,
        "yaml_path_omitted": True,
    }


def build_run_manifest(
    dataset_yaml: Path,
    dataset_metadata: dict[str, Any],
    config: YOLOTrainingConfig,
    *,
    status: str,
) -> dict[str, Any]:
    config.validate()
    return {
        "schema_version": "hct203-yolo-run/v1",
        "status": status,
        "release_status": "EXPERIMENTAL_UNRELEASED",
        "dataset": dataset_metadata,
        "configuration": asdict(config),
        "dataset_yaml_sha256": sha256_file(dataset_yaml.resolve()),
        "artifacts_external_to_git": True,
        "weights_loaded_by_homecare_runtime": False,
        "paths_omitted": True,
    }


def train_yolo(
    dataset_yaml: Path,
    output_dir: Path,
    config: YOLOTrainingConfig,
    *,
    require_test: bool = False,
) -> dict[str, Any]:
    config.validate()
    dataset_metadata = load_dataset_config(dataset_yaml, require_test=require_test)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("OUTPUT_DIR_MUST_BE_EMPTY")
    output_dir.mkdir(parents=True, exist_ok=True)
    run_manifest = build_run_manifest(
        dataset_yaml,
        dataset_metadata,
        config,
        status="RUNNING",
    )
    manifest_path = output_dir / "run_manifest.json"
    manifest_path.write_text(
        json.dumps(run_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError(
            "YOLO_TRAINING_DEPENDENCY_MISSING: install ultralytics in the "
            "controlled training environment"
        ) from exc

    random.seed(config.seed)
    model = YOLO(config.base_model)
    model.train(
        data=str(dataset_yaml.resolve()),
        project=str(output_dir),
        name="train",
        exist_ok=False,
        epochs=config.epochs,
        imgsz=config.image_size,
        batch=config.batch_size,
        device=config.device,
        workers=config.workers,
        seed=config.seed,
        deterministic=config.deterministic,
        verbose=True,
    )
    best_weights = output_dir / "train" / "weights" / "best.pt"
    run_manifest["status"] = "COMPLETED"
    run_manifest["artifacts"] = {
        "best_weights_sha256": sha256_file(best_weights) if best_weights.is_file() else None,
        "best_weights_size_bytes": best_weights.stat().st_size if best_weights.is_file() else None,
        "relative_best_weights": "train/weights/best.pt" if best_weights.is_file() else None,
    }
    manifest_path.write_text(
        json.dumps(run_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return run_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-yaml", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--base-model", default="yolo11n.pt")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--image-size", type=int, default=640)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--device", default="0")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument("--require-test", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    config = YOLOTrainingConfig(
        base_model=args.base_model,
        epochs=args.epochs,
        image_size=args.image_size,
        batch_size=args.batch_size,
        device=args.device,
        workers=args.workers,
        seed=args.seed,
        confidence=args.confidence,
    )
    try:
        config.validate()
        metadata = load_dataset_config(args.dataset_yaml, require_test=args.require_test)
        run_manifest = build_run_manifest(
            args.dataset_yaml,
            metadata,
            config,
            status="DRY_RUN_VALIDATED" if args.dry_run else "READY_TO_RUN",
        )
        if args.dry_run:
            if args.output_dir.exists() and any(args.output_dir.iterdir()):
                raise ValueError("OUTPUT_DIR_MUST_BE_EMPTY")
            args.output_dir.mkdir(parents=True, exist_ok=True)
            (args.output_dir / "run_manifest.json").write_text(
                json.dumps(run_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        else:
            run_manifest = train_yolo(
                args.dataset_yaml,
                args.output_dir,
                config,
                require_test=args.require_test,
            )
        print(json.dumps(run_manifest, ensure_ascii=False, indent=2))
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
