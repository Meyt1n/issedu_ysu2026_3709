"""HCT-414: CPU performance and evidence probe for the video vision-task path.

Measures the deterministic server-side video pipeline that HCT-414-D1/D2 landed:
container decode, frame sampling, near-duplicate rejection and per-frame quality
gating. Fixtures are generated locally from synthetic patterns, so this probe
carries no real medicine packaging, no real health data and no approved dataset.

The approved fixed set is still gated on HCT-201, so every report produced here
is DEMO_ONLY and must not be used to claim release readiness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np
import psutil

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "src" / "api"))

from ai.vision.quality_gate import assess_video_file  # noqa: E402

DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "hct414-video-perf.json"
SCHEMA_VERSION = "hct414-video-perf-v1"
SAMPLE_COUNT = 12
WARMUP_COUNT = 2
# The base tier budget for the whole local vision pipeline. Video decode plus
# sampling must stay well inside it because OCR and fusion still run afterwards.
PIPELINE_P95_BUDGET_MS = 8000.0
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
FRAME_RATE = 15


@dataclass(frozen=True)
class VideoFixture:
    """One locally generated video plus the sampling arguments it exercises."""

    name: str
    path: Path
    duration_seconds: float
    description: str
    sample_interval_ms: int = 1000
    max_selected_frames: int = 60
    max_duration_ms: int | None = None


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
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip() or "unknown"


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        raise ValueError("PERF_SAMPLES_EMPTY")
    ranked = sorted(values)
    index = min(len(ranked) - 1, max(0, int(round((len(ranked) - 1) * ratio))))
    return ranked[index]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pattern_frame(index: int, *, sharp: bool, moving: bool, distinct: bool = False) -> np.ndarray:
    """Build one deterministic synthetic frame.

    The layout imitates the geometry the quality gate expects — a bright
    rectangular object inset on a darker surface — because a full-frame test
    pattern trips the glare and border-touch guards and would only ever measure
    the RETAKE branch. `distinct` varies the content enough to survive
    near-duplicate rejection, which is what a handheld capture looks like.
    Nothing here resembles real medicine packaging.
    """
    frame = np.full((FRAME_HEIGHT, FRAME_WIDTH, 3), 70, dtype=np.uint8)
    # Faint deterministic texture on the surface keeps edge density realistic.
    frame[::16, :] = 58
    frame[:, ::16] = 58

    shift = (index * 3) % 24 if moving else 0
    grow = (index * 5) % 40 if distinct else 0
    left, top = 150 + shift, 110
    right, bottom = FRAME_WIDTH - 150 + shift - grow, FRAME_HEIGHT - 110
    cv2.rectangle(frame, (left, top), (right, bottom), (198, 198, 198), -1)
    cv2.rectangle(frame, (left, top), (right, bottom), (40, 40, 40), 2)

    cv2.putText(
        frame,
        "HCT-414",
        (left + 18, top + 55),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (25, 25, 25),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        frame,
        f"SYNTHETIC {index:03d}",
        (left + 18, top + 100),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (35, 35, 35),
        1,
        cv2.LINE_AA,
    )
    for offset in range(0, 5):
        y = top + 130 + offset * 12
        end = right - 18 - (offset * 9 * (index % 4) if distinct else 0)
        cv2.line(frame, (left + 18, y), (max(left + 30, end), y), (60, 60, 60), 1)

    if not sharp:
        frame = cv2.GaussianBlur(frame, (31, 31), 0)
    return frame


def _write_video(
    path: Path,
    *,
    duration_seconds: float,
    sharp: bool = True,
    moving: bool = True,
    distinct: bool = False,
) -> None:
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        FRAME_RATE,
        (FRAME_WIDTH, FRAME_HEIGHT),
    )
    if not writer.isOpened():
        raise RuntimeError("VIDEO_FIXTURE_WRITER_UNAVAILABLE")
    try:
        for index in range(int(round(duration_seconds * FRAME_RATE))):
            writer.write(_pattern_frame(index, sharp=sharp, moving=moving, distinct=distinct))
    finally:
        writer.release()


def build_fixtures(directory: Path) -> list[VideoFixture]:
    """Generate the synthetic fixtures this probe measures."""
    fixtures: list[VideoFixture] = []

    short = directory / "hct414-sharp-05s.mp4"
    _write_video(short, duration_seconds=5)
    fixtures.append(VideoFixture(
        name="sharp_5s_1fps_sampling",
        path=short,
        duration_seconds=5,
        description="5s moving high-detail clip, 1 frame per second sampling",
    ))

    limit = directory / "hct414-sharp-30s.mp4"
    _write_video(limit, duration_seconds=30, distinct=True)
    fixtures.append(VideoFixture(
        name="varied_30s_at_duration_limit",
        path=limit,
        duration_seconds=30,
        description=(
            "30s clip at the configured VISION_VIDEO_MAX_DURATION_SECONDS bound, "
            "with per-frame variation so most sampled frames survive dedup"
        ),
        max_duration_ms=30_000,
    ))

    dense = directory / "hct414-sharp-10s-dense.mp4"
    _write_video(dense, duration_seconds=10)
    fixtures.append(VideoFixture(
        name="sharp_10s_dense_sampling",
        path=dense,
        duration_seconds=10,
        description="10s clip sampled every 200ms to stress per-frame quality scoring",
        sample_interval_ms=200,
    ))

    still = directory / "hct414-static-10s.mp4"
    _write_video(still, duration_seconds=10, moving=False)
    fixtures.append(VideoFixture(
        name="static_10s_duplicate_heavy",
        path=still,
        duration_seconds=10,
        description="10s static clip; near-duplicate rejection should keep very few frames",
        sample_interval_ms=200,
    ))

    return fixtures


def _timed(operation: Callable[[], None], samples: int, warmup: int) -> dict[str, float | int]:
    for _ in range(warmup):
        operation()
    latencies: list[float] = []
    for _ in range(samples):
        started = perf_counter()
        operation()
        latencies.append((perf_counter() - started) * 1000)
    return {
        "samples": samples,
        "p50_ms": round(_percentile(latencies, 0.50), 3),
        "p95_ms": round(_percentile(latencies, 0.95), 3),
        "mean_ms": round(statistics.fmean(latencies), 3),
        "max_ms": round(max(latencies), 3),
    }


def _measure_fixture(fixture: VideoFixture, *, samples: int, warmup: int) -> dict[str, object]:
    def run() -> dict[str, object]:
        return assess_video_file(
            fixture.path,
            source_id=fixture.name,
            sample_interval_ms=fixture.sample_interval_ms,
            max_selected_frames=fixture.max_selected_frames,
            max_duration_ms=fixture.max_duration_ms,
        )

    outcome = run()
    timing = _timed(lambda: run() and None, samples, warmup)
    frames = outcome.get("frames")
    selected = len(frames) if isinstance(frames, list) else 0
    usable = 0
    if isinstance(frames, list):
        usable = sum(1 for frame in frames if frame.get("allow_downstream"))
    metrics = outcome.get("metrics") if isinstance(outcome.get("metrics"), dict) else {}
    return {
        "description": fixture.description,
        "fixture_bytes": fixture.path.stat().st_size,
        "fixture_sha256": _sha256(fixture.path),
        "duration_seconds": fixture.duration_seconds,
        "sample_interval_ms": fixture.sample_interval_ms,
        "decision": outcome.get("decision"),
        "allow_downstream": outcome.get("allow_downstream"),
        "reasons": outcome.get("reasons"),
        "frame_reasons": sorted({
            reason
            for frame in (frames if isinstance(frames, list) else [])
            for reason in (frame.get("reasons") or [])
        }),
        # decoded / sampled / selected shows how much work each stage really did:
        # dedup can collapse many sampled frames into very few scored frames.
        "decoded_frames": metrics.get("decoded_frames"),
        "sampled_frames": metrics.get("sampled_frames"),
        "selected_frames": selected,
        "usable_frames": usable,
        "schema_version": outcome.get("schema_version"),
        "config_version": outcome.get("config_version"),
        "latency": timing,
    }


def _failure_samples(directory: Path) -> list[dict[str, object]]:
    """Exercise the controlled rejection paths so the report shows them explicitly."""
    results: list[dict[str, object]] = []

    corrupt = directory / "hct414-corrupt.mp4"
    corrupt.write_bytes(b"not-a-container" * 64)
    results.append(_expect_error(
        "undecodable_container",
        corrupt,
        expected="VIDEO_DECODE_FAILED",
        description="Bytes that are not a media container must be rejected before sampling",
    ))

    empty = directory / "hct414-empty.mp4"
    empty.write_bytes(b"")
    results.append(_expect_error(
        "empty_file",
        empty,
        expected="VIDEO_DECODE_FAILED",
        description="Zero-byte upload must be rejected",
    ))

    long_clip = directory / "hct414-overlong.mp4"
    _write_video(long_clip, duration_seconds=8)
    results.append(_expect_error(
        "duration_exceeded",
        long_clip,
        expected="VIDEO_DURATION_EXCEEDED",
        description="Clip longer than the configured bound must be rejected",
        max_duration_ms=3_000,
    ))

    blurred = directory / "hct414-blurred.mp4"
    _write_video(blurred, duration_seconds=4, sharp=False, moving=False)
    outcome = assess_video_file(
        blurred,
        source_id="blurred_low_detail",
        sample_interval_ms=500,
    )
    results.append({
        "name": "blurred_low_detail",
        "description": "Out-of-focus clip must land on RETAKE and never reach recognition",
        "fixture_sha256": _sha256(blurred),
        "outcome": "rejected" if not outcome.get("allow_downstream") else "unexpectedly_allowed",
        "decision": outcome.get("decision"),
        "reasons": outcome.get("reasons"),
    })
    return results


def _expect_error(
    name: str,
    path: Path,
    *,
    expected: str,
    description: str,
    max_duration_ms: int | None = None,
) -> dict[str, object]:
    try:
        assess_video_file(
            path,
            source_id=name,
            sample_interval_ms=500,
            max_duration_ms=max_duration_ms,
        )
    except ValueError as error:
        actual = str(error)
        return {
            "name": name,
            "description": description,
            "expected_error": expected,
            "actual_error": actual,
            "outcome": "rejected" if actual == expected else "unexpected_error",
            "fixture_sha256": _sha256(path),
        }
    return {
        "name": name,
        "description": description,
        "expected_error": expected,
        "actual_error": None,
        "outcome": "unexpectedly_accepted",
        "fixture_sha256": _sha256(path),
    }


def measure_video_performance(
    *,
    samples: int = SAMPLE_COUNT,
    warmup: int = WARMUP_COUNT,
) -> dict[str, object]:
    process = psutil.Process()
    rss_before = process.memory_info().rss
    with tempfile.TemporaryDirectory(prefix="hct414-video-perf-") as raw_directory:
        directory = Path(raw_directory)
        fixtures = build_fixtures(directory)
        measured = {
            fixture.name: _measure_fixture(fixture, samples=samples, warmup=warmup)
            for fixture in fixtures
        }
        failures = _failure_samples(directory)
        fixture_bytes = sum(path.stat().st_size for path in directory.iterdir() if path.is_file())
        rss_after = process.memory_info().rss

    latencies = [
        float(entry["latency"]["p95_ms"])  # type: ignore[index]
        for entry in measured.values()
    ]
    worst_p95 = max(latencies) if latencies else 0.0
    unexpected = [entry for entry in failures if entry["outcome"] != "rejected"]

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "commit_sha": _git_sha(),
        "release_status": "DEMO_ONLY",
        "release_blockers": [
            "HCT-201 approved fixed set is not released, so no accuracy claim is made here.",
            "Synthetic fixtures only; no real medicine packaging or health data.",
        ],
        "environment": {
            "ci": os.environ.get("CI", "").casefold() == "true",
            "runner_os": os.environ.get("RUNNER_OS") or platform.system(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor() or "unknown",
            "logical_cpus": psutil.cpu_count(logical=True),
            "physical_cpus": psutil.cpu_count(logical=False),
            "total_memory_bytes": psutil.virtual_memory().total,
            "python": platform.python_version(),
            "opencv": cv2.__version__,
        },
        "data_policy": {
            "classification": "synthetic-only",
            "real_health_data": False,
            "real_packaging_images": False,
            "secrets_recorded": False,
            "fixtures_persisted": False,
        },
        "resources": {
            "fixture_disk_bytes": fixture_bytes,
            "process_rss_before_bytes": rss_before,
            "process_rss_after_bytes": rss_after,
            "process_rss_delta_bytes": rss_after - rss_before,
        },
        "budgets_ms": {"video_pipeline_p95": PIPELINE_P95_BUDGET_MS},
        "stages_measured": [
            "container decode (cv2.VideoCapture)",
            "interval frame sampling",
            "near-duplicate rejection",
            "per-frame quality gating",
        ],
        "stages_not_measured": [
            "OCR / barcode extraction",
            "candidate fusion and master-data matching",
            "manual review hand-off",
        ],
        "fixtures": measured,
        "failure_samples": failures,
        "worst_pipeline_p95_ms": round(worst_p95, 3),
        "within_budget": worst_p95 <= PIPELINE_P95_BUDGET_MS,
        "unexpected_failure_outcomes": [entry["name"] for entry in unexpected],
        "known_limits": [
            "In-process probe on one host; not a multi-host or concurrent load test.",
            "Locally generated mp4v fixtures; real device captures may decode slower.",
            "Frame content is synthetic, so quality scores are not an accuracy signal.",
            (
                "Synthetic frames are highly self-similar, so near-duplicate rejection "
                "collapses most sampled frames. Compare decoded_frames / sampled_frames / "
                "selected_frames per fixture: decode dominates the measured cost here, "
                "while a real handheld capture would score more frames."
            ),
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--samples", type=int, default=SAMPLE_COUNT)
    parser.add_argument(
        "--no-enforce",
        action="store_true",
        help="Write the report without failing on a budget breach or unexpected acceptance.",
    )
    args = parser.parse_args()

    report = measure_video_performance(samples=args.samples)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output)
    print(
        f"worst video pipeline p95: {report['worst_pipeline_p95_ms']} ms "
        f"(budget {PIPELINE_P95_BUDGET_MS} ms) release_status={report['release_status']}"
    )

    problems: list[str] = []
    if not report["within_budget"]:
        problems.append("VIDEO_PIPELINE_P95_BUDGET_EXCEEDED")
    unexpected = report["unexpected_failure_outcomes"]
    if unexpected:
        problems.append(f"UNEXPECTED_FAILURE_OUTCOMES={unexpected}")
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        if not args.no_enforce:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())





