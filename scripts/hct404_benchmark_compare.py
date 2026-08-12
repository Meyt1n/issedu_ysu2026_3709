#!/usr/bin/env python3
"""HCT-404: V1 vs V2 benchmark comparison on the same fixed test set.

Outputs a JSON comparison report conforming to schema:
  hct-404-comparison-report/v1

Usage:
  python scripts/hct404_benchmark_compare.py \
    --v1-weights /path/to/v1.pt \
    --v2-weights /path/to/v2.pt \
    --images-dir /path/to/fixed/test/images \
    --output report.json \
    [--device cuda] \
    [--image-size 640] \
    [--confidence 0.25]
"""

import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="HCT-404 V1/V2 benchmark comparison")
    p.add_argument("--v1-weights", required=True, type=Path, help="V1 model weights file")
    p.add_argument("--v2-weights", required=True, type=Path, help="V2 model weights file")
    p.add_argument("--images-dir", required=True, type=Path, help="Fixed test set directory")
    p.add_argument("--output", required=True, type=Path, help="Output JSON report path")
    p.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    p.add_argument("--image-size", type=int, default=640)
    p.add_argument("--confidence", type=float, default=0.25)
    p.add_argument("--hard-negative-dir", type=Path, default=None,
                   help="Separate unknown/hard-negative directory")
    return p.parse_args()


def _file_sha256(path: Path) -> str:
    """Compute SHA-256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _dir_sha256(dir_path: Path) -> str:
    """Compute a deterministic hash over all image files in a directory."""
    h = hashlib.sha256()
    for f in sorted(dir_path.glob("*")):
        if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"}:
            h.update(f.name.encode())
            h.update(_file_sha256(f).encode())
    return h.hexdigest()


def _build_placeholder_report(
    v1_weights: Path, v2_weights: Path, images_dir: Path, args: argparse.Namespace,
) -> dict[str, Any]:
    """Build a comparison report with placeholder metrics.

    In production, this would run actual YOLO inference.
    For the P0 teaching demonstration, structured placeholders document
    the expected report schema and release gate fields.
    """
    comparison_id = str(uuid4())
    now = datetime.now(UTC).isoformat()

    v1_sha = _file_sha256(v1_weights) if v1_weights.exists() else "unavailable"
    v2_sha = _file_sha256(v2_weights) if v2_weights.exists() else "unavailable"
    fixed_set_sha = _dir_sha256(images_dir) if images_dir.exists() else "unavailable"

    return {
        "schema_version": "hct-404-comparison-report/v1",
        "comparison_id": comparison_id,
        "created_at": now,
        "v1": {
            "model_id": "hct-yolo11n-box-assist-experimental-v1.2",
            "weights_sha256": v1_sha,
            "metrics": {
                "precision": "PLACEHOLDER",
                "recall": "PLACEHOLDER",
                "map50": "PLACEHOLDER",
                "map50_95": "PLACEHOLDER",
            },
            "per_class": {},
            "hard_negative_results": [],
            "performance": {
                "cpu": {"latency_mean_ms": "PLACEHOLDER", "latency_p95_ms": "PLACEHOLDER"},
                "gpu": {"latency_mean_ms": "PLACEHOLDER", "latency_p95_ms": "PLACEHOLDER"},
            },
        },
        "v2": {
            "model_id": "hct-yolo11n-box-assist-experimental-v1.3",
            "weights_sha256": v2_sha,
            "metrics": {
                "precision": "PLACEHOLDER",
                "recall": "PLACEHOLDER",
                "map50": "PLACEHOLDER",
                "map50_95": "PLACEHOLDER",
            },
            "per_class": {},
            "hard_negative_results": [],
            "performance": {
                "cpu": {"latency_mean_ms": "PLACEHOLDER", "latency_p95_ms": "PLACEHOLDER"},
                "gpu": {"latency_mean_ms": "PLACEHOLDER", "latency_p95_ms": "PLACEHOLDER"},
            },
        },
        "delta": {
            "map50_absolute": "PLACEHOLDER",
            "map50_95_absolute": "PLACEHOLDER",
            "hard_negative_improvement": "PLACEHOLDER",
            "performance_regression_p95_ms": "PLACEHOLDER",
        },
        "fixed_set": {
            "input_set_sha256": fixed_set_sha,
            "image_count": len(list(images_dir.glob("*"))) if images_dir.exists() else 0,
        },
        "release_assessment": {
            "passes_safety_thresholds": False,
            "safety_threshold_checks": [
                {"threshold": "min_map50 >= 0.90", "passed": False, "reason": "PLACEHOLDER"},
                {"threshold": "min_map50_95 >= 0.85", "passed": False, "reason": "PLACEHOLDER"},
                {"threshold": "max_hard_negative_fp == 0", "passed": False, "reason": "PLACEHOLDER"},
                {"threshold": "comparison_report exists", "passed": True, "reason": ""},
            ],
            "recommendation": "BLOCKED_UNTIL_REAL_WEIGHTS_AVAILABLE",
        },
    }


def main() -> None:
    args = _parse_args()

    if not args.images_dir.exists():
        print(f"ERROR: images directory not found: {args.images_dir}", file=sys.stderr)
        sys.exit(1)

    report = _build_placeholder_report(args.v1_weights, args.v2_weights, args.images_dir, args)
    report["invocation"] = {
        "argv": sys.argv,
        "cwd": str(Path.cwd()),
        "device": args.device,
        "image_size": args.image_size,
        "confidence": args.confidence,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    report_hash = hashlib.sha256(
        json.dumps(report, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"Comparison report written to {args.output}")
    print(f"Report SHA-256: {report_hash}")


if __name__ == "__main__":
    main()
