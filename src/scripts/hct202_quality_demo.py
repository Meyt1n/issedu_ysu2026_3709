"""Run the HCT-202 quality gate on generated, non-sensitive demo images."""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import psutil

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from ai.vision.quality_gate import QualityThresholds, assess_image  # noqa: E402


def _fixtures() -> dict[str, np.ndarray]:
    clear = np.full((480, 640, 3), 110, dtype=np.uint8)
    cv2.rectangle(clear, (140, 90), (500, 390), (225, 225, 225), -1)
    cv2.rectangle(clear, (140, 90), (500, 390), (20, 20, 20), 6)
    cv2.putText(
        clear,
        "DEMO BOX",
        (185, 245),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.4,
        (20, 20, 20),
        4,
    )
    return {
        "clear": clear,
        "blurred": cv2.GaussianBlur(clear, (51, 51), 0),
        "dark": np.full_like(clear, 5),
        "overexposed": np.full_like(clear, 255),
        "too_small": cv2.resize(clear, (160, 120)),
    }


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * percentile))
    return ordered[index]


def run(iterations: int) -> dict[str, Any]:
    if iterations < 1:
        raise ValueError("iterations must be positive")
    thresholds = QualityThresholds()
    fixtures = _fixtures()
    results = {
        name: assess_image(image, source_id=f"synthetic:{name}", thresholds=thresholds)
        for name, image in fixtures.items()
    }
    process = psutil.Process()
    rss_before = process.memory_info().rss
    durations: list[float] = []
    for index in range(iterations):
        started = time.perf_counter()
        assess_image(fixtures["clear"], source_id=f"benchmark:{index}", thresholds=thresholds)
        durations.append((time.perf_counter() - started) * 1000)
    rss_after = process.memory_info().rss

    return {
        "schema_version": "hct202-demo-report-v1",
        "config_version": thresholds.config_version,
        "input": "programmatically_generated_non_sensitive_images",
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "opencv": cv2.__version__,
            "processor": platform.processor() or "unavailable",
        },
        "cases": {
            name: {"decision": result["decision"], "reasons": result["reasons"]}
            for name, result in results.items()
        },
        "performance": {
            "iterations": iterations,
            "p50_ms": round(_percentile(durations, 0.50), 3),
            "p95_ms": round(_percentile(durations, 0.95), 3),
            "max_ms": round(max(durations), 3),
            "rss_delta_bytes": rss_after - rss_before,
        },
        "limitations": [
            "synthetic fixtures are pipeline evidence, not real-world threshold calibration",
            "formal false-reject and missed-reject rates require the approved HCT-201 fixed set",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=50)
    args = parser.parse_args()
    print(json.dumps(run(args.iterations), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
