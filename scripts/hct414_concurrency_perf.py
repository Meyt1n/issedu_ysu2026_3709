"""HCT-414 / #246: single-host concurrent video-task performance probe.

The video quality gate is request-local: each worker opens the same synthetic
fixture independently and must return a result carrying its own ``source_id``.
This probe exercises that property with a bounded thread pool and records
per-request latency, throughput, errors and the process RSS high-water mark.

It is deliberately *not* a distributed or multi-host load test.  A real
multi-host run needs deployed workers, a controlled queue and an approved
dataset; those remain release blockers and are disclosed in every report.
Fixtures are generated locally and removed before the command exits.
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
import threading
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import perf_counter

import psutil

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from ai.vision.quality_gate import assess_video_file  # noqa: E402

from hct414_video_perf import (  # noqa: E402
    FRAME_HEIGHT,
    FRAME_RATE,
    FRAME_WIDTH,
    _write_video,
)

REPORT_SCHEMA = "hct414-concurrency-perf-v1"
DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "hct414-concurrency-perf.json"
DEFAULT_CONCURRENCIES = (1, 2, 4)
DEFAULT_REQUESTS_PER_LEVEL = 4
DEFAULT_WARMUP = 1
CONCURRENCY_P95_BUDGET_MS = 8_000.0
MAX_CONCURRENCY = 8


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
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        raise ValueError("PERF_SAMPLES_EMPTY")
    ranked = sorted(values)
    index = min(len(ranked) - 1, max(0, int(round((len(ranked) - 1) * ratio))))
    return ranked[index]


def _stats(values: list[float]) -> dict[str, float | int]:
    return {
        "count": len(values),
        "p50_ms": round(_percentile(values, 0.50), 3),
        "p95_ms": round(_percentile(values, 0.95), 3),
        "mean_ms": round(statistics.fmean(values), 3),
        "max_ms": round(max(values), 3),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rss_peak_during(operation):
    """Run *operation* while sampling this process' RSS in a small monitor."""
    process = psutil.Process()
    samples = [process.memory_info().rss]
    stop = threading.Event()

    def sample() -> None:
        while not stop.is_set():
            try:
                samples.append(process.memory_info().rss)
            except psutil.Error:
                return
            stop.wait(0.01)

    monitor = threading.Thread(target=sample, name="hct414-rss-monitor", daemon=True)
    monitor.start()
    try:
        result = operation()
    finally:
        stop.set()
        monitor.join(timeout=1)
        samples.append(process.memory_info().rss)
    return result, max(samples)


def _validate_concurrencies(concurrencies: Iterable[int]) -> tuple[int, ...]:
    values = tuple(dict.fromkeys(concurrencies))
    if not values or any(value < 1 or value > MAX_CONCURRENCY for value in values):
        raise ValueError(f"CONCURRENCY_OUT_OF_RANGE: 1..{MAX_CONCURRENCY}")
    return values


def _run_request(path: Path, request_number: int) -> dict[str, object]:
    source_id = f"hct414-concurrency-{request_number:04d}"
    started = perf_counter()
    try:
        outcome = assess_video_file(
            path,
            source_id=source_id,
            sample_interval_ms=500,
            max_selected_frames=12,
            max_duration_ms=30_000,
        )
    except Exception as error:  # noqa: BLE001 - report every worker failure
        return {
            "request_number": request_number,
            "source_id": source_id,
            "latency_ms": round((perf_counter() - started) * 1000, 3),
            "error": f"{type(error).__name__}: {error}",
        }

    reported_source = outcome.get("source")
    reported_source_id = (
        reported_source.get("source_id") if isinstance(reported_source, dict) else None
    )
    return {
        "request_number": request_number,
        "source_id": source_id,
        "reported_source_id": reported_source_id,
        "latency_ms": round((perf_counter() - started) * 1000, 3),
        "decision": outcome.get("decision"),
        "allow_downstream": outcome.get("allow_downstream"),
        "error": None,
    }


def _run_level(path: Path, concurrency: int, request_count: int) -> tuple[dict[str, object], int]:
    request_numbers = range(request_count)

    def run() -> dict[str, object]:
        started = perf_counter()
        with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="hct414") as pool:
            results = list(pool.map(lambda number: _run_request(path, number), request_numbers))
        wall_ms = (perf_counter() - started) * 1000
        latencies = [float(result["latency_ms"]) for result in results]
        errors = [result for result in results if result.get("error")]
        ids_are_isolated = all(
            result["source_id"] == result.get("reported_source_id")
            for result in results
            if not result.get("error")
        )
        unique_ids = len({result["source_id"] for result in results}) == len(results)
        return {
            "concurrency": concurrency,
            "requests": request_count,
            "latency": _stats(latencies),
            "wall_time_ms": round(wall_ms, 3),
            "throughput_requests_per_second": round(request_count / (wall_ms / 1000), 3)
            if wall_ms
            else 0.0,
            "error_count": len(errors),
            "errors": errors,
            "source_ids_isolated": ids_are_isolated and unique_ids,
            "decisions": sorted(
                {
                    str(result.get("decision"))
                    for result in results
                    if not result.get("error")
                }
            ),
        }

    report, peak_rss = _rss_peak_during(run)
    return report, peak_rss


def measure_concurrency_performance(
    *,
    concurrencies: Iterable[int] = DEFAULT_CONCURRENCIES,
    requests_per_level: int = DEFAULT_REQUESTS_PER_LEVEL,
    warmup: int = DEFAULT_WARMUP,
    fixture_duration_seconds: float = 5.0,
) -> dict[str, object]:
    """Measure bounded same-host concurrency using synthetic video only."""
    levels = _validate_concurrencies(concurrencies)
    if requests_per_level < 1:
        raise ValueError("REQUEST_COUNT_INVALID")
    if warmup < 0:
        raise ValueError("WARMUP_INVALID")
    if fixture_duration_seconds <= 0 or fixture_duration_seconds > 30:
        raise ValueError("FIXTURE_DURATION_OUT_OF_RANGE")

    process = psutil.Process()
    rss_before = process.memory_info().rss
    with tempfile.TemporaryDirectory(prefix="hct414-concurrency-perf-") as raw_directory:
        fixture = Path(raw_directory) / "hct414-concurrency-synthetic.mp4"
        _write_video(
            fixture,
            duration_seconds=fixture_duration_seconds,
            sharp=True,
            moving=True,
            distinct=True,
        )
        fixture_info = {
            "file_name": fixture.name,
            "size_bytes": fixture.stat().st_size,
            "sha256": _sha256(fixture),
            "duration_seconds": fixture_duration_seconds,
            "frame_rate": FRAME_RATE,
            "frame_size": [FRAME_WIDTH, FRAME_HEIGHT],
        }

        for request_number in range(warmup):
            warmup_result = _run_request(fixture, -request_number - 1)
            if warmup_result.get("error"):
                raise RuntimeError(f"PERF_WARMUP_FAILED: {warmup_result['error']}")

        levels_report: dict[str, object] = {}
        peak_rss = rss_before
        for concurrency in levels:
            level, level_peak = _run_level(fixture, concurrency, requests_per_level)
            levels_report[str(concurrency)] = level
            peak_rss = max(peak_rss, level_peak)

    rss_after = process.memory_info().rss
    all_levels = list(levels_report.values())
    unexpected_errors = [
        f"concurrency={level['concurrency']} errors={level['error_count']}"
        for level in all_levels
        if level["error_count"]
    ]
    isolation_failures = [
        str(level["concurrency"])
        for level in all_levels
        if not level["source_ids_isolated"]
    ]
    worst_p95 = max(float(level["latency"]["p95_ms"]) for level in all_levels)

    return {
        "schema_version": REPORT_SCHEMA,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "issue": "#246 剩余项第 4 条（单主机并发探针）",
        "commit_sha": _git_sha(),
        "release_status": "DEMO_ONLY",
        "load_model": {
            "kind": "single-host-thread-pool",
            "host_count": 1,
            "worker_processes": 1,
            "multi_host_measured": False,
        },
        "environment": {
            "ci": os.environ.get("CI", "").casefold() == "true",
            "runner_os": os.environ.get("RUNNER_OS") or platform.system(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor() or "unknown",
            "logical_cpus": psutil.cpu_count(logical=True),
            "python": platform.python_version(),
        },
        "data_policy": {
            "classification": "synthetic-only",
            "real_health_data": False,
            "real_packaging_images": False,
            "secrets_recorded": False,
            "fixtures_persisted": False,
        },
        "fixture": fixture_info,
        "levels": levels_report,
        "budgets_ms": {"per_request_p95": CONCURRENCY_P95_BUDGET_MS},
        "worst_per_request_p95_ms": round(worst_p95, 3),
        "within_budget": worst_p95 <= CONCURRENCY_P95_BUDGET_MS,
        "peak_rss_bytes": peak_rss,
        "rss_before_bytes": rss_before,
        "rss_after_bytes": rss_after,
        "rss_delta_bytes": rss_after - rss_before,
        "unexpected_errors": unexpected_errors,
        "source_isolation_failures": isolation_failures,
        "stages_not_measured": [
            "多主机/分布式 worker 与队列压测",
            "OCR、人工复核交接和 HCT-201 授权固定集准确率",
            "Android 真机端到端上传与 HEVC worker 链路",
        ],
        "release_blockers": [
            "本探针只覆盖单主机线程池，不代表多主机部署容量",
            "HCT-201（#48）授权固定集与模型发布门禁仍未满足",
            "OCR 与人工复核交接仍缺真实依赖/端到端证据",
        ],
        "known_limits": [
            "线程池共享一个 Python 进程与本地文件系统，不能推断跨主机队列行为",
            "合成 mp4v 只用于并发安全与资源边界，不是准确率或真机编码代表",
            "结果只保留哈希、时延和状态，不写入视频正文或健康事件",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--concurrency", type=int, nargs="+", default=list(DEFAULT_CONCURRENCIES))
    parser.add_argument("--requests-per-level", type=int, default=DEFAULT_REQUESTS_PER_LEVEL)
    parser.add_argument("--warmup", type=int, default=DEFAULT_WARMUP)
    parser.add_argument("--fixture-duration", type=float, default=5.0)
    parser.add_argument("--no-enforce", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = measure_concurrency_performance(
            concurrencies=args.concurrency,
            requests_per_level=args.requests_per_level,
            warmup=args.warmup,
            fixture_duration_seconds=args.fixture_duration,
        )
    except (RuntimeError, ValueError) as error:
        parser.error(str(error))

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    print(
        f"worst per-request p95: {report['worst_per_request_p95_ms']} ms "
        f"(budget {CONCURRENCY_P95_BUDGET_MS:.0f} ms) "
        f"release_status={report['release_status']}"
    )
    for level in report["levels"].values():
        print(
            f"  concurrency={level['concurrency']} requests={level['requests']} "
            f"p95={level['latency']['p95_ms']}ms "
            f"throughput={level['throughput_requests_per_second']} req/s "
            f"errors={level['error_count']} isolated={level['source_ids_isolated']}"
        )

    problems = []
    if not report["within_budget"]:
        problems.append("CONCURRENCY_P95_BUDGET_EXCEEDED")
    problems.extend(report["unexpected_errors"])
    problems.extend(
        f"SOURCE_ISOLATION_FAILED:{level}" for level in report["source_isolation_failures"]
    )
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        if not args.no_enforce:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
