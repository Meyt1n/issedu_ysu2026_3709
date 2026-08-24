"""Run the formal, independent HCT-203 YOLO evaluation outside Git.

The command evaluates only the external ``test`` split from a controlled
dataset YAML. Images, labels, weights and raw predictions stay outside the
repository; the JSON report contains hashes, aggregate metrics and explicit
hard-negative outcomes only. A report is evidence for the release gate, not a
runtime enablement or publication action.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
from pathlib import Path
from typing import Any

from hct203_benchmark import input_set_sha256
from hct203_train_yolo import IMAGE_SUFFIXES, _load_yaml, _resolve_split, load_dataset_config

SHA256_LENGTH = 64
DEFAULT_THRESHOLDS: dict[str, float] = {
    "min_precision": 0.95,
    "min_recall": 0.95,
    "min_map50": 0.90,
    "min_map50_95": 0.85,
    "max_hard_negative_fp": 0,
}


def canonical_sha256(value: Any) -> str:
    """Hash a JSON value deterministically without exposing local paths."""

    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
    elif hasattr(value, "item"):
        try:
            result = float(value.item())
        except (TypeError, ValueError):
            return None
    else:
        return None
    return result if math.isfinite(result) else None


def _as_float_list(value: Any) -> list[float]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        result: list[float] = []
        for item in value:
            number = _as_float(item)
            if number is not None:
                result.append(number)
        return result
    number = _as_float(value)
    return [] if number is None else [number]


def extract_box_metrics(results: Any) -> dict[str, float]:
    """Extract stable aggregate metrics from an Ultralytics validation result."""

    box = getattr(results, "box", results)
    aliases = {
        "precision": ("mp", "precision"),
        "recall": ("mr", "recall"),
        "map50": ("map50", "map_50"),
        "map50_95": ("map", "map50_95", "map_50_95"),
    }
    metrics: dict[str, float] = {}
    for output_name, candidates in aliases.items():
        for candidate in candidates:
            value = _as_float(getattr(box, candidate, None))
            if value is not None:
                metrics[output_name] = value
                break
    missing = sorted(set(aliases) - set(metrics))
    if missing:
        raise ValueError(f"VALIDATION_METRIC_MISSING:{','.join(missing)}")
    return metrics


def extract_per_class_metrics(results: Any, names: Any = None) -> list[dict[str, Any]]:
    """Return per-class metrics when the validator exposes them."""

    box = getattr(results, "box", results)
    values = {
        "precision": _as_float_list(getattr(box, "p", [])),
        "recall": _as_float_list(getattr(box, "r", [])),
        "map50": _as_float_list(getattr(box, "ap50", [])),
        "map50_95": _as_float_list(getattr(box, "ap", [])),
    }
    count = max((len(item) for item in values.values()), default=0)
    if count == 0:
        return []
    if isinstance(names, dict):
        labels = [str(names.get(index, index)) for index in range(count)]
    elif isinstance(names, list):
        labels = [str(names[index]) if index < len(names) else str(index) for index in range(count)]
    else:
        labels = [str(index) for index in range(count)]
    return [
        {
            "class_index": index,
            "class_name": labels[index],
            **{
                key: series[index] if index < len(series) else None
                for key, series in values.items()
            },
        }
        for index in range(count)
    ]


def evaluate_metrics(
    metrics: dict[str, Any], thresholds: dict[str, float] | None = None
) -> list[dict[str, str]]:
    """Check the release thresholds without interpreting missing metrics as zero."""

    limits = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    findings: list[dict[str, str]] = []
    for metric, threshold_key in (
        ("precision", "min_precision"),
        ("recall", "min_recall"),
        ("map50", "min_map50"),
        ("map50_95", "min_map50_95"),
    ):
        value = _as_float(metrics.get(metric))
        if value is None:
            findings.append({"code": "METRIC_MISSING", "message": f"missing {metric}"})
        elif value < limits[threshold_key]:
            findings.append(
                {
                    "code": "METRIC_BELOW_THRESHOLD",
                    "message": f"{metric}={value:.6f} < {limits[threshold_key]:.6f}",
                }
            )
    return findings


def _resolve_images(config_path: Path, split: str) -> list[Path]:
    raw = _load_yaml(config_path.resolve())
    root_value = raw.get("path", ".")
    root = Path(root_value) if isinstance(root_value, str) else Path(".")
    if not root.is_absolute():
        root = config_path.resolve().parent / root
    images: list[Path] = []
    for entry in _resolve_split(config_path.resolve(), root, raw.get(split), split):
        if entry.is_file() and entry.suffix.lower() in IMAGE_SUFFIXES:
            images.append(entry)
        elif entry.is_file():
            for line in entry.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    image = Path(line.strip())
                    if not image.is_absolute():
                        image = entry.parent / image
                    if image.suffix.lower() in IMAGE_SUFFIXES:
                        images.append(image.resolve())
        else:
            images.extend(
                item.resolve()
                for item in entry.rglob("*")
                if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES
            )
    unique = {path.resolve() for path in images}
    return sorted(unique, key=lambda path: path.name.lower())


def load_hard_negative_manifest(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"HARD_NEGATIVE_RECORD_INVALID:{line_number}")
        sample_id = str(value.get("sample_id", "")).strip()
        image_value = value.get("image_path", value.get("image"))
        if not sample_id or not isinstance(image_value, str) or not image_value.strip():
            raise ValueError(f"HARD_NEGATIVE_RECORD_REQUIRED:{line_number}")
        records.append({"sample_id": sample_id, "image_path": image_value})
    if not records:
        raise ValueError("HARD_NEGATIVE_MANIFEST_EMPTY")
    return records


def _prediction_confidences(result: Any) -> list[float]:
    boxes = getattr(result, "boxes", None)
    return _as_float_list(getattr(boxes, "conf", [])) if boxes is not None else []


def _run_hard_negative_review(
    model: Any,
    records: list[dict[str, Any]],
    *,
    image_size: int,
    confidence: float,
    device: str,
) -> list[dict[str, Any]]:
    reviewed: list[dict[str, Any]] = []
    for record in records:
        image_path = Path(record["image_path"]).resolve()
        if not image_path.is_file():
            raise ValueError(f"HARD_NEGATIVE_IMAGE_MISSING:{record['sample_id']}")
        predictions = model.predict(
            source=str(image_path),
            imgsz=image_size,
            conf=confidence,
            device=device,
            verbose=False,
        )
        confidences = [
            item
            for result in predictions
            for item in _prediction_confidences(result)
            if item >= confidence
        ]
        reviewed.append(
            {
                "sample_id": record["sample_id"],
                "prediction_count": len(confidences),
                "max_confidence": max(confidences, default=0.0),
                "false_positive": bool(confidences),
            }
        )
    return reviewed


def build_independent_evaluation_report(
    *,
    weights_sha256: str,
    weights_size_bytes: int,
    dataset_yaml_sha256: str,
    test_set_sha256: str,
    test_images: int,
    metrics: dict[str, Any],
    hard_negatives: list[dict[str, Any]],
    per_class: list[dict[str, Any]] | None = None,
    thresholds: dict[str, float] | None = None,
    environment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    limits = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    findings = evaluate_metrics(metrics, limits)
    false_positive_count = sum(1 for item in hard_negatives if item.get("false_positive") is True)
    if false_positive_count > limits["max_hard_negative_fp"]:
        findings.append(
            {
                "code": "HARD_NEGATIVE_FALSE_POSITIVE",
                "message": (
                    f"hard-negative false positives={false_positive_count} > "
                    f"{limits['max_hard_negative_fp']}"
                ),
            }
        )
    if not hard_negatives:
        findings.append(
            {"code": "HARD_NEGATIVE_EVIDENCE_MISSING", "message": "review set is empty"}
        )

    report: dict[str, Any] = {
        "schema_version": "hct203-yolo-independent-evaluation/v1",
        "status": "PASSED" if not findings else "FAILED",
        "evaluation_scope": "approved_real_fixed_set",
        "independent_evaluation": True,
        "dataset_yaml_sha256": dataset_yaml_sha256,
        "test_set_sha256": test_set_sha256,
        "weights_sha256": weights_sha256,
        "weights_size_bytes": weights_size_bytes,
        "test": {"images": test_images},
        "metrics": {key: float(value) for key, value in metrics.items()},
        "per_class": per_class or [],
        "hard_negative_reviewed": True,
        "hard_negatives": hard_negatives,
        "thresholds": limits,
        "false_positive_count": false_positive_count,
        "findings": findings,
        "environment": environment
        or {
            "python": platform.python_version(),
            "operating_system": platform.platform(),
        },
        "paths_omitted": True,
    }
    report["threshold_report_sha256"] = canonical_sha256(
        {"schema_version": "hct203-yolo-thresholds/v1", "thresholds": limits}
    )
    report["evaluation_report_sha256"] = canonical_sha256(report)
    return report


def run_independent_evaluation(
    weights: Path,
    dataset_yaml: Path,
    hard_negative_manifest: Path,
    *,
    device: str,
    image_size: int,
    confidence: float,
    thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    if not weights.is_file():
        raise ValueError("WEIGHTS_MISSING")
    dataset = load_dataset_config(dataset_yaml, require_test=True)
    test_images = _resolve_images(dataset_yaml, "test")
    if not test_images:
        raise ValueError("TEST_SPLIT_EMPTY")
    records = load_hard_negative_manifest(hard_negative_manifest)
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError("INDEPENDENT_EVAL_DEPENDENCY_MISSING: install ultralytics") from exc

    model = YOLO(str(weights))
    validation = model.val(
        data=str(dataset_yaml.resolve()),
        split="test",
        imgsz=image_size,
        batch=1,
        conf=confidence,
        device=device,
        verbose=False,
        plots=False,
        save_json=False,
    )
    metrics = extract_box_metrics(validation)
    hard_negatives = _run_hard_negative_review(
        model,
        records,
        image_size=image_size,
        confidence=confidence,
        device=device,
    )
    return build_independent_evaluation_report(
        weights_sha256=sha256_file(weights),
        weights_size_bytes=weights.stat().st_size,
        dataset_yaml_sha256=dataset["dataset_yaml_sha256"],
        test_set_sha256=input_set_sha256(test_images),
        test_images=len(test_images),
        metrics=metrics,
        hard_negatives=hard_negatives,
        per_class=extract_per_class_metrics(validation, getattr(model, "names", None)),
        thresholds=thresholds,
        environment={
            "python": platform.python_version(),
            "operating_system": platform.platform(),
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", required=True, type=Path)
    parser.add_argument("--dataset-yaml", required=True, type=Path)
    parser.add_argument("--hard-negative-manifest", required=True, type=Path)
    parser.add_argument("--device", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--image-size", type=int, default=640)
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument("--min-precision", type=float, default=DEFAULT_THRESHOLDS["min_precision"])
    parser.add_argument("--min-recall", type=float, default=DEFAULT_THRESHOLDS["min_recall"])
    parser.add_argument("--min-map50", type=float, default=DEFAULT_THRESHOLDS["min_map50"])
    parser.add_argument("--min-map50-95", type=float, default=DEFAULT_THRESHOLDS["min_map50_95"])
    parser.add_argument("--max-hard-negative-fp", type=int, default=0)
    args = parser.parse_args()
    thresholds = {
        "min_precision": args.min_precision,
        "min_recall": args.min_recall,
        "min_map50": args.min_map50,
        "min_map50_95": args.min_map50_95,
        "max_hard_negative_fp": args.max_hard_negative_fp,
    }
    try:
        report = run_independent_evaluation(
            args.weights,
            args.dataset_yaml,
            args.hard_negative_manifest,
            device=args.device,
            image_size=args.image_size,
            confidence=args.confidence,
            thresholds=thresholds,
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        report = {
            "schema_version": "hct203-yolo-independent-evaluation/v1",
            "status": "FAILED",
            "evaluation_scope": "approved_real_fixed_set",
            "independent_evaluation": False,
            "findings": [{"code": "INPUT_OR_RUNTIME_ERROR", "message": str(exc)}],
            "paths_omitted": True,
        }
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report.get("status") == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
