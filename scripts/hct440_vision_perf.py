"""HCT-440: synthetic, offline vision pipeline performance probe.

The probe runs the real quality-gate, OCR-first normalizer and candidate
fusion functions with deterministic synthetic evidence.  It produces a
machine-readable report for HCT-409 but never claims production OCR/model
performance or approved fixed-set accuracy.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import cv2
import numpy as np
import psutil

REPO_ROOT = Path(__file__).resolve().parents[1]
for source_path in (REPO_ROOT / "src", REPO_ROOT / "src/api", REPO_ROOT / "scripts"):
    if str(source_path) not in sys.path:
        sys.path.insert(0, str(source_path))

from ai.vision.candidate_fusion import fuse_evidence  # noqa: E402
from ai.vision.evidence_pipeline import (  # noqa: E402
    EvidencePipelineRequest,
    EvidenceRegion,
    FieldProposal,
    LocalMasterData,
    MasterDataRecord,
    OCRToken,
    PackageRegionProposal,
    process_evidence,
)
from ai.vision.quality_gate import QualityThresholds, assess_image  # noqa: E402

from hct409_api_perf import measure_api_performance  # noqa: E402

DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "hct440-vision-perf.json"
DEFAULT_SAMPLES = 20
DEFAULT_WARMUP = 3
DEFAULT_P95_BUDGET_MS = 8_000.0


def _git_sha() -> str:
    ci_sha = os.environ.get("GITHUB_SHA", "").strip()
    if ci_sha:
        return ci_sha
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or "unknown" if result.returncode == 0 else "unknown"


def _percentile(values: list[float], ratio: float) -> float:
    ranked = sorted(values)
    if not ranked:
        raise ValueError("PERF_SAMPLES_EMPTY")
    index = min(len(ranked) - 1, max(0, int(round((len(ranked) - 1) * ratio))))
    return ranked[index]


def _timed(
    operation: Callable[[], object],
    *,
    samples: int,
    warmup: int,
) -> dict[str, float | int]:
    for _ in range(warmup):
        operation()
    latencies: list[float] = []
    errors = 0
    for _ in range(samples):
        started = perf_counter()
        try:
            operation()
        except Exception:
            errors += 1
        latencies.append((perf_counter() - started) * 1000)
    return {
        "samples": samples,
        "p50_ms": round(_percentile(latencies, 0.50), 3),
        "p95_ms": round(_percentile(latencies, 0.95), 3),
        "mean_ms": round(statistics.fmean(latencies), 3),
        "error_rate": round(errors / samples, 4),
        "max_ms": round(max(latencies), 3),
    }


def _synthetic_image() -> np.ndarray:
    """Create a stable high-contrast medicine-box-shaped test image."""
    image = np.full((480, 640, 3), 180, dtype=np.uint8)
    cv2.rectangle(image, (80, 60), (560, 420), (245, 245, 245), thickness=-1)
    cv2.rectangle(image, (80, 60), (560, 420), (25, 80, 120), thickness=8)
    cv2.rectangle(image, (130, 120), (510, 180), (40, 120, 190), thickness=-1)
    cv2.putText(
        image,
        "SYNTHETIC MEDICINE",
        (145, 160),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        image,
        "HCT-440",
        (220, 300),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.6,
        (20, 20, 20),
        4,
        cv2.LINE_AA,
    )
    return image


def _synthetic_request() -> EvidencePipelineRequest:
    region = EvidenceRegion(x=120, y=110, width=400, height=220)
    token = OCRToken(
        id="synthetic-ocr-1",
        raw_value="阿司匹林",
        region=region,
        confidence=0.99,
        engine_version="synthetic-ocr-v1",
        language="zh",
    )
    package = PackageRegionProposal(
        id="synthetic-yolo-1",
        label="medicine_box",
        region=region,
        confidence=0.98,
        model_version="synthetic-yolo-v1",
    )
    return EvidencePipelineRequest(
        ocr_tokens=[token],
        package_regions=[package],
        field_proposals=[
            FieldProposal(
                field_name="drug_name",
                raw_value="阿司匹林",
                evidence_ids=[token.id],
                confidence=0.99,
                parser_version="synthetic-parser-v1",
            )
        ],
        vision_model_version="synthetic-vision-v1",
        ocr_engine_version="synthetic-ocr-v1",
        master_data_version="synthetic-master-v1",
        code_version="hct440-v1",
        adapter_id="hct440-synthetic",
        adapter_version="hct440-synthetic-v1",
        adapter_run_id="hct440-fixed-run",
    )


def _synthetic_master() -> LocalMasterData:
    return LocalMasterData(
        version="synthetic-master-v1",
        available=True,
        records=[
            MasterDataRecord(
                record_id="synthetic-aspirin",
                name_aliases=["阿司匹林"],
                specification="100mg",
                manufacturer="synthetic-only",
                packaging_type="box",
            )
        ],
    )


def _run_pipeline(
    image: np.ndarray,
    request: EvidencePipelineRequest,
    master: LocalMasterData,
) -> None:
    quality = assess_image(
        image,
        source_id="hct440-synthetic-image",
        thresholds=QualityThresholds(),
    )
    if quality["decision"] != "PASS":
        raise RuntimeError("SYNTHETIC_QUALITY_FIXTURE_REJECTED")
    evidence = process_evidence(request, master_data=master, source_sha256="0" * 64)
    fused = fuse_evidence(evidence, master)
    if fused.health_event_allowed or not fused.requires_human_confirmation:
        raise RuntimeError("VISION_SAFETY_CONTRACT_BROKEN")


def measure_vision_performance(
    *,
    samples: int = DEFAULT_SAMPLES,
    warmup: int = DEFAULT_WARMUP,
    max_p95_ms: float = DEFAULT_P95_BUDGET_MS,
) -> dict[str, Any]:
    if samples < 1 or warmup < 0:
        raise ValueError("PERF_SAMPLE_COUNT_INVALID")
    image = _synthetic_image()
    request = _synthetic_request()
    master = _synthetic_master()

    quality = _timed(
        lambda: assess_image(
            image,
            source_id="hct440-synthetic-image",
            thresholds=QualityThresholds(),
        ),
        samples=samples,
        warmup=warmup,
    )
    evidence = _timed(
        lambda: process_evidence(request, master_data=master, source_sha256="0" * 64),
        samples=samples,
        warmup=warmup,
    )
    fusion_input = process_evidence(request, master_data=master, source_sha256="0" * 64)
    fusion = _timed(
        lambda: fuse_evidence(fusion_input, master),
        samples=samples,
        warmup=warmup,
    )
    full_pipeline = _timed(
        lambda: _run_pipeline(image, request, master),
        samples=samples,
        warmup=warmup,
    )
    base_api = measure_api_performance(samples=samples, warmup=warmup)
    api_endpoints = base_api["endpoints"]
    api_perf = {
        "health_p95_ms": api_endpoints["GET /health"]["p95_ms"],
        "db_p95_ms": api_endpoints["GET /api/v1/health/db"]["p95_ms"],
        "household_list_p95_ms": api_endpoints["GET /api/v1/households"]["p95_ms"],
        "vision_full_pipeline_p95_ms": full_pipeline["p95_ms"],
        "error_rate": max(
            full_pipeline["error_rate"],
            *(stats["error_rate"] for stats in api_endpoints.values()),
        ),
    }
    findings: list[str] = []
    if full_pipeline["error_rate"] != 0:
        findings.append("VISION_PIPELINE_ERROR_RATE_NONZERO")
    if float(full_pipeline["p95_ms"]) > max_p95_ms:
        findings.append("VISION_PIPELINE_P95_TOO_HIGH")
    return {
        "schema_version": "hct440-vision-perf-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "commit_sha": _git_sha(),
        "tier": "base",
        "environment": {
            "ci": os.environ.get("CI", "").casefold() == "true",
            "runner_os": os.environ.get("RUNNER_OS") or platform.system(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "process_rss_bytes": psutil.Process().memory_info().rss,
        },
        "data_policy": {
            "classification": "synthetic-only",
            "real_health_data": False,
            "secrets_recorded": False,
            "network_access": False,
        },
        "budgets_ms": {"vision_full_pipeline_p95": max_p95_ms},
        "stages": {
            "quality_gate": quality,
            "evidence_normalization": evidence,
            "candidate_fusion": fusion,
            "vision_full_pipeline": full_pipeline,
        },
        "base_api": base_api,
        "api_perf": api_perf,
        "gate": {
            "passed": not findings,
            "findings": findings,
            "decision": "PASS_SYNTHETIC_GATE" if not findings else "BLOCK_SYNTHETIC_GATE",
        },
        "known_limits": [
            "Synthetic adapter evidence; no OCR, barcode decoder, YOLO or LLM inference.",
            "In-process functions and TestClient; not a multi-host load test.",
            (
                "Does not replace approved fixed-set metrics, deployment CPU P95, "
                "R3 review or sign-off."
            ),
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    parser.add_argument("--warmup", type=int, default=DEFAULT_WARMUP)
    parser.add_argument("--max-p95-ms", type=float, default=DEFAULT_P95_BUDGET_MS)
    args = parser.parse_args()
    try:
        report = measure_vision_performance(
            samples=args.samples,
            warmup=args.warmup,
            max_p95_ms=args.max_p95_ms,
        )
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"schema_version": "hct440-vision-perf-v1", "error": str(exc)}))
        return 2
    print(output)
    return 0 if report["gate"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
