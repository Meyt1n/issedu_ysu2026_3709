"""Run a real HCT-404 V1/V2 comparison on one external fixed test set.

The command loads both external YOLO weight files, evaluates the same ``test``
split, reviews the same hard-negative manifest, and records measured inference
latency. Images, labels, weights and predictions never enter the repository;
the JSON contains hashes and aggregate/per-sample safety outcomes only.

This is an evidence producer, not a publication action. Missing weights,
dataset configuration, labels or the Ultralytics runtime produce a failed
report; placeholders are deliberately not accepted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from hct203_benchmark import input_set_sha256
from hct203_independent_eval import (
    _resolve_images,
    _run_hard_negative_review,
    extract_box_metrics,
    extract_per_class_metrics,
    load_hard_negative_manifest,
    sha256_file,
)
from hct203_train_yolo import load_dataset_config

IMAGE_SAMPLE_LIMIT = 32
METRIC_NAMES = ("precision", "recall", "map50", "map50_95")
DEFAULT_THRESHOLDS: dict[str, float] = {
    "min_precision": 0.95,
    "min_recall": 0.95,
    "min_map50": 0.90,
    "min_map50_95": 0.85,
    "max_hard_negative_fp": 0,
    "max_p95_regression_ratio": 1.20,
}


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("LATENCY_SAMPLES_EMPTY")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


def measure_latency(
    model: Any,
    images: list[Path],
    *,
    image_size: int,
    confidence: float,
    device: str,
) -> dict[str, Any]:
    """Measure bounded single-image inference latency without storing predictions."""

    sample = images[:IMAGE_SAMPLE_LIMIT]
    if not sample:
        raise ValueError("TEST_SPLIT_EMPTY")
    model.predict(
        source=str(sample[0]),
        imgsz=image_size,
        conf=confidence,
        device=device,
        verbose=False,
    )
    durations: list[float] = []
    for image in sample:
        started = time.perf_counter()
        model.predict(
            source=str(image),
            imgsz=image_size,
            conf=confidence,
            device=device,
            verbose=False,
        )
        durations.append((time.perf_counter() - started) * 1000.0)
    return {
        "device": device,
        "images_measured": len(durations),
        "latency_mean_ms": round(sum(durations) / len(durations), 3),
        "latency_p95_ms": round(_percentile(durations, 0.95), 3),
    }


def _run_model_evaluation(
    *,
    model_id: str,
    weights: Path,
    dataset_yaml: Path,
    test_images: list[Path],
    test_set_sha256: str,
    dataset_yaml_sha256: str,
    hard_negative_manifest: Path,
    device: str,
    image_size: int,
    confidence: float,
) -> dict[str, Any]:
    if not weights.is_file():
        raise ValueError(f"WEIGHTS_MISSING:{model_id}")
    records = load_hard_negative_manifest(hard_negative_manifest)
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError("BENCHMARK_DEPENDENCY_MISSING: install ultralytics") from exc

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
    report: dict[str, Any] = {
        "model_id": model_id,
        "weights_sha256": sha256_file(weights),
        "weights_size_bytes": weights.stat().st_size,
        "dataset_yaml_sha256": dataset_yaml_sha256,
        "test_set_sha256": test_set_sha256,
        "test_images": len(test_images),
        "metrics": metrics,
        "per_class": extract_per_class_metrics(validation, getattr(model, "names", None)),
        "hard_negative_reviewed": True,
        "hard_negatives": hard_negatives,
        "performance": measure_latency(
            model,
            test_images,
            image_size=image_size,
            confidence=confidence,
            device=device,
        ),
        "paths_omitted": True,
        "status": "PASSED",
    }
    report["evaluation_report_sha256"] = canonical_sha256(report)
    return report


def _numeric_metrics(value: dict[str, Any]) -> bool:
    return all(
        isinstance(value.get(key), (int, float))
        and not isinstance(value.get(key), bool)
        and 0 <= float(value[key]) <= 1
        for key in METRIC_NAMES
    )


def build_comparison_report(
    *,
    v1: dict[str, Any],
    v2: dict[str, Any],
    dataset_yaml_sha256: str,
    test_set_sha256: str,
    test_images: int,
    thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    limits = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    checks: list[dict[str, Any]] = []
    for key, minimum in (
        ("precision", limits["min_precision"]),
        ("recall", limits["min_recall"]),
        ("map50", limits["min_map50"]),
        ("map50_95", limits["min_map50_95"]),
    ):
        value = _as_float(v2["metrics"].get(key))
        checks.append(
            {
                "threshold": f"v2.{key} >= {minimum:.2f}",
                "value": value,
                "passed": value is not None and value >= minimum,
            }
        )
    v2_fp = sum(1 for item in v2["hard_negatives"] if item.get("false_positive") is True)
    checks.append(
        {
            "threshold": f"v2.hard_negative_false_positive <= {limits['max_hard_negative_fp']}",
            "value": v2_fp,
            "passed": v2_fp <= limits["max_hard_negative_fp"],
        }
    )
    v1_p95 = _as_float(v1["performance"].get("latency_p95_ms"))
    v2_p95 = _as_float(v2["performance"].get("latency_p95_ms"))
    ratio = None if not v1_p95 else (v2_p95 / v1_p95 if v2_p95 is not None else None)
    checks.append(
        {
            "threshold": f"v2.p95 / v1.p95 <= {limits['max_p95_regression_ratio']:.2f}",
            "value": ratio,
            "passed": ratio is not None and ratio <= limits["max_p95_regression_ratio"],
        }
    )
    passed = (
        v1.get("status") == "PASSED"
        and v2.get("status") == "PASSED"
        and bool(v1.get("hard_negatives"))
        and bool(v2.get("hard_negatives"))
        and _numeric_metrics(v1.get("metrics", {}))
        and _numeric_metrics(v2.get("metrics", {}))
        and all(item["passed"] for item in checks)
    )
    report: dict[str, Any] = {
        "schema_version": "hct-404-comparison-report/v2",
        "comparison_id": str(uuid4()),
        "created_at": datetime.now(UTC).isoformat(),
        "evaluation_scope": "approved_real_fixed_set",
        "same_fixed_set": True,
        "dataset": {
            "dataset_yaml_sha256": dataset_yaml_sha256,
            "test_set_sha256": test_set_sha256,
            "test_images": test_images,
        },
        "fixed_set": {
            "dataset_yaml_sha256": dataset_yaml_sha256,
            "test_set_sha256": test_set_sha256,
            "image_count": test_images,
        },
        "v1": v1,
        "v2": v2,
        "delta": {
            key: round(float(v2["metrics"][key]) - float(v1["metrics"][key]), 6)
            for key in METRIC_NAMES
        },
        "performance_delta": {
            "p95_ratio": ratio,
            "p95_absolute_ms": (
                None if v1_p95 is None or v2_p95 is None else round(v2_p95 - v1_p95, 3)
            ),
        },
        "thresholds": limits,
        "release_assessment": {
            "passes_safety_thresholds": passed,
            "checks": checks,
            "recommendation": "ALLOW_FORMAL_RELEASE" if passed else "BLOCK_MODEL_RELEASE",
        },
        "environment": {
            "python": platform.python_version(),
            "operating_system": platform.platform(),
        },
        "paths_omitted": True,
    }
    report["comparison_report_sha256"] = canonical_sha256(report)
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v1-weights", required=True, type=Path)
    parser.add_argument("--v2-weights", required=True, type=Path)
    parser.add_argument("--v1-model-id", default="hct404-vision-v1")
    parser.add_argument("--v2-model-id", default="hct404-vision-v2")
    parser.add_argument("--dataset-yaml", required=True, type=Path)
    parser.add_argument("--hard-negative-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--device", required=True)
    parser.add_argument("--image-size", type=int, default=640)
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument("--min-precision", type=float, default=DEFAULT_THRESHOLDS["min_precision"])
    parser.add_argument("--min-recall", type=float, default=DEFAULT_THRESHOLDS["min_recall"])
    parser.add_argument("--min-map50", type=float, default=DEFAULT_THRESHOLDS["min_map50"])
    parser.add_argument("--min-map50-95", type=float, default=DEFAULT_THRESHOLDS["min_map50_95"])
    parser.add_argument("--max-hard-negative-fp", type=int, default=0)
    parser.add_argument(
        "--max-p95-regression-ratio",
        type=float,
        default=DEFAULT_THRESHOLDS["max_p95_regression_ratio"],
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    thresholds = {
        "min_precision": args.min_precision,
        "min_recall": args.min_recall,
        "min_map50": args.min_map50,
        "min_map50_95": args.min_map50_95,
        "max_hard_negative_fp": args.max_hard_negative_fp,
        "max_p95_regression_ratio": args.max_p95_regression_ratio,
    }
    try:
        dataset = load_dataset_config(args.dataset_yaml, require_test=True)
        test_images = _resolve_images(args.dataset_yaml, "test")
        if not test_images:
            raise ValueError("TEST_SPLIT_EMPTY")
        test_set_sha = input_set_sha256(test_images)
        v1 = _run_model_evaluation(
            model_id=args.v1_model_id,
            weights=args.v1_weights,
            dataset_yaml=args.dataset_yaml,
            test_images=test_images,
            test_set_sha256=test_set_sha,
            dataset_yaml_sha256=dataset["dataset_yaml_sha256"],
            hard_negative_manifest=args.hard_negative_manifest,
            device=args.device,
            image_size=args.image_size,
            confidence=args.confidence,
        )
        v2 = _run_model_evaluation(
            model_id=args.v2_model_id,
            weights=args.v2_weights,
            dataset_yaml=args.dataset_yaml,
            test_images=test_images,
            test_set_sha256=test_set_sha,
            dataset_yaml_sha256=dataset["dataset_yaml_sha256"],
            hard_negative_manifest=args.hard_negative_manifest,
            device=args.device,
            image_size=args.image_size,
            confidence=args.confidence,
        )
        report = build_comparison_report(
            v1=v1,
            v2=v2,
            dataset_yaml_sha256=dataset["dataset_yaml_sha256"],
            test_set_sha256=test_set_sha,
            test_images=len(test_images),
            thresholds=thresholds,
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        report = {
            "schema_version": "hct-404-comparison-report/v2",
            "status": "FAILED",
            "evaluation_scope": "approved_real_fixed_set",
            "same_fixed_set": False,
            "release_assessment": {
                "passes_safety_thresholds": False,
                "recommendation": "BLOCK_MODEL_RELEASE",
            },
            "findings": [{"code": "INPUT_OR_RUNTIME_ERROR", "message": str(exc)}],
            "paths_omitted": True,
        }
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report.get("release_assessment", {}).get("passes_safety_thresholds") else 1


if __name__ == "__main__":
    raise SystemExit(main())
