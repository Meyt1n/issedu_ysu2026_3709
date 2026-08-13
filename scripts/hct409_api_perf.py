"""HCT-409: in-process API latency probe for the base-tier release gate.

This measures FastAPI TestClient latency with a temporary SQLite store. It is
not a vision full-pipeline, OCR, or multi-host load test.
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

import psutil
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "src" / "api"))

from app.db import get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402

DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "hct409-api-perf.json"
OWNER_HEADERS = {"X-Actor-Id": "hct409-perf-owner"}
SAMPLE_COUNT = 40
WARMUP_COUNT = 5
HEALTH_P95_BUDGET_MS = 2000.0
HOUSEHOLD_P95_BUDGET_MS = 5000.0


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


def _timed(operation: Callable[[], int], samples: int, warmup: int) -> dict[str, float | int]:
    for _ in range(warmup):
        status = operation()
        if status >= 400:
            raise RuntimeError(f"PERF_WARMUP_FAILED status={status}")
    latencies: list[float] = []
    errors = 0
    for _ in range(samples):
        started = perf_counter()
        status = operation()
        elapsed_ms = (perf_counter() - started) * 1000
        latencies.append(elapsed_ms)
        if status >= 400:
            errors += 1
    return {
        "samples": samples,
        "p50_ms": round(_percentile(latencies, 0.50), 3),
        "p95_ms": round(_percentile(latencies, 0.95), 3),
        "mean_ms": round(statistics.fmean(latencies), 3),
        "error_rate": round(errors / samples, 4),
        "max_ms": round(max(latencies), 3),
    }


def measure_api_performance(
    *,
    samples: int = SAMPLE_COUNT,
    warmup: int = WARMUP_COUNT,
) -> dict[str, object]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_session():
        session: Session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    process = psutil.Process()
    try:
        with TestClient(app) as client:
            health = _timed(lambda: client.get("/health").status_code, samples, warmup)
            db_health = _timed(
                lambda: client.get("/api/v1/health/db").status_code,
                samples,
                warmup,
            )
            created = {"n": 0}

            def create_household() -> int:
                created["n"] += 1
                response = client.post(
                    "/api/v1/households",
                    headers=OWNER_HEADERS,
                    json={"name": f"HCT-409 synthetic household {created['n']}"},
                )
                return response.status_code

            household_write = _timed(create_household, samples, warmup)
            household_list = _timed(
                lambda: client.get("/api/v1/households", headers=OWNER_HEADERS).status_code,
                samples,
                warmup,
            )
        rss = process.memory_info().rss
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    return {
        "schema_version": "hct409-api-perf-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "commit_sha": _git_sha(),
        "tier": "base",
        "environment": {
            "ci": os.environ.get("CI", "").casefold() == "true",
            "runner_os": os.environ.get("RUNNER_OS") or platform.system(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "process_rss_bytes": rss,
        },
        "data_policy": {
            "classification": "synthetic-only",
            "real_health_data": False,
            "secrets_recorded": False,
        },
        "budgets_ms": {
            "GET /health p95": HEALTH_P95_BUDGET_MS,
            "POST /api/v1/households p95": HOUSEHOLD_P95_BUDGET_MS,
        },
        "endpoints": {
            "GET /health": health,
            "GET /api/v1/health/db": db_health,
            "POST /api/v1/households": household_write,
            "GET /api/v1/households": household_list,
        },
        "known_limits": [
            "In-process TestClient latency, not a multi-host load test.",
            "Does not measure vision OCR/barcode/fusion full-pipeline P95.",
            "Vision full-pipeline CPU P95 <= 8s remains blocked on HCT-201.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--samples", type=int, default=SAMPLE_COUNT)
    args = parser.parse_args()
    report = measure_api_performance(samples=args.samples)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
