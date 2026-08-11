"""Benchmark an external YOLO model without copying images or weights into Git."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import statistics
import time
from importlib.metadata import version
from pathlib import Path
from typing import Any

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def percentile_nearest_rank(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("values must not be empty")
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def input_set_sha256(images: list[Path]) -> str:
    digest = hashlib.sha256()
    for image in images:
        digest.update(image.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(image).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def run_benchmark(
    weights: Path,
    images_dir: Path,
    device: str,
    image_size: int,
    confidence: float,
    warmup: int,
) -> dict[str, Any]:
    import psutil
    import torch
    from ultralytics import YOLO

    images = sorted(
        path
        for path in images_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )
    if not images:
        raise ValueError("images directory contains no supported images")
    if device != "cpu" and not torch.cuda.is_available():
        raise RuntimeError("CUDA device requested but torch.cuda.is_available() is false")

    load_started = time.perf_counter()
    model = YOLO(str(weights))
    load_ms = (time.perf_counter() - load_started) * 1000
    for index in range(warmup):
        model.predict(
            source=str(images[index % len(images)]),
            imgsz=image_size,
            conf=confidence,
            device=device,
            verbose=False,
        )
    if device != "cpu":
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()

    process = psutil.Process()
    peak_rss = process.memory_info().rss
    latencies_ms: list[float] = []
    detection_count = 0
    total_started = time.perf_counter()
    for image in images:
        if device != "cpu":
            torch.cuda.synchronize()
        started = time.perf_counter()
        results = model.predict(
            source=str(image),
            imgsz=image_size,
            conf=confidence,
            device=device,
            verbose=False,
        )
        if device != "cpu":
            torch.cuda.synchronize()
        latencies_ms.append((time.perf_counter() - started) * 1000)
        detection_count += sum(len(result.boxes) for result in results)
        peak_rss = max(peak_rss, process.memory_info().rss)
    total_seconds = time.perf_counter() - total_started
    gpu_peak = int(torch.cuda.max_memory_allocated()) if device != "cpu" else None
    peak_memory = max(peak_rss, gpu_peak or 0)

    return {
        "schema_version": "hct-vision-benchmark/v1",
        "status": "EXPERIMENTAL_CANDIDATE",
        "device": device,
        "images": len(images),
        "input_set_sha256": input_set_sha256(images),
        "weights_sha256": sha256_file(weights),
        "weights_size_bytes": weights.stat().st_size,
        "image_size": image_size,
        "confidence": confidence,
        "warmup_iterations": warmup,
        "model_load_ms": round(load_ms, 3),
        "latency_mean_ms": round(statistics.fmean(latencies_ms), 3),
        "latency_p50_ms": round(percentile_nearest_rank(latencies_ms, 0.50), 3),
        "latency_p95_ms": round(percentile_nearest_rank(latencies_ms, 0.95), 3),
        "throughput_images_per_second": round(len(images) / total_seconds, 3),
        "peak_memory_bytes": peak_memory,
        "process_rss_peak_observed_bytes": peak_rss,
        "cuda_peak_allocated_bytes": gpu_peak,
        "detection_count": detection_count,
        "environment": {
            "python": platform.python_version(),
            "operating_system": platform.platform(),
            "ultralytics": version("ultralytics"),
            "torch": version("torch"),
        },
        "path_disclosure": "paths intentionally omitted",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", required=True, type=Path)
    parser.add_argument("--images-dir", required=True, type=Path)
    parser.add_argument("--device", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--image-size", type=int, default=640)
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument("--warmup", type=int, default=5)
    args = parser.parse_args()
    report = run_benchmark(
        args.weights,
        args.images_dir,
        args.device,
        args.image_size,
        args.confidence,
        args.warmup,
    )
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
