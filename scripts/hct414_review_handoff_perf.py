"""HCT-414 / #246: API-to-database human-review handoff probe.

This probe drives the real FastAPI endpoints with a temporary SQLite store:
quality check -> video task creation -> evidence submission -> fusion.  The
evidence route creates the member-scoped review task and the fusion route
attaches ranked candidates to that same row.  The report verifies one review
row per vision task, version continuity and that no health event is written
before a human confirmation.

All media and master data are synthetic fixtures.  They are created in a
temporary directory and deleted after the run.  This is release evidence for
the handoff contract, not an OCR accuracy or HCT-201 fixed-set result.
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
import time
from collections.abc import Generator
from pathlib import Path
from time import perf_counter
from typing import Any

import psutil
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "src" / "api"))

from ai.vision.evidence_pipeline import EvidencePipelineRequest, issue_adapter_receipt  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, HealthEvent  # noqa: E402
from app.review import ReviewTask  # noqa: E402
from hct414_video_perf import _write_video  # noqa: E402

REPORT_SCHEMA = "hct414-review-handoff-perf-v1"
DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "hct414-review-handoff-perf.json"
DEFAULT_SAMPLES = 10
DEFAULT_WARMUP = 1
HANDOFF_P95_BUDGET_MS = 2_000.0
MASTER_VERSION = "hct414-review-perf-master-v1"
OWNER = "hct414-review-perf-owner"


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


def _write_master_snapshot(root: Path) -> None:
    snapshot: dict[str, Any] = {
        "schema_version": "hct-master-data/v1",
        "version": MASTER_VERSION,
        "approval_status": "APPROVED",
        "approval_ref": "hct414-synthetic-review-probe",
        "revocation_status": "ACTIVE",
        "records": [
            {
                "record_id": "synthetic-medication-1",
                "product_barcode": "4006381333931",
                "name_aliases": ["Synthetic Medicine"],
                "specification": "10mg",
                "manufacturer": "Synthetic Labs",
                "packaging_type": "medicine_box",
            }
        ],
    }
    canonical = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    snapshot["sha256"] = hashlib.sha256(canonical).hexdigest()
    (root / f"{MASTER_VERSION}.json").write_text(
        json.dumps(snapshot, ensure_ascii=False), encoding="utf-8"
    )


def _evidence_payload(sample: int) -> EvidencePipelineRequest:
    raw_fields = {
        "drug_name": ("Synthetic Medicine", f"ocr-name-{sample}"),
        "specification": ("10mg", f"ocr-specification-{sample}"),
        "manufacturer": ("Synthetic Labs", f"ocr-manufacturer-{sample}"),
        "batch_number": ("SYN-BATCH-1", f"ocr-batch-{sample}"),
        "expiry_date": ("2030-01", f"ocr-expiry-{sample}"),
        "packaging_type": ("medicine_box", f"ocr-packaging-{sample}"),
    }
    ocr_tokens = [
        {
            "id": evidence_id,
            "raw_value": value,
            "confidence": 0.97,
            "engine_version": "synthetic-ocr-v1",
        }
        for value, evidence_id in raw_fields.values()
    ]
    field_proposals = [
        {
            "field_name": field_name,
            "raw_value": value,
            "evidence_ids": [evidence_id],
            "confidence": 0.95,
            "parser_version": "synthetic-parser-v1",
        }
        for field_name, (value, evidence_id) in raw_fields.items()
    ]
    field_proposals.append(
        {
            "field_name": "product_barcode",
            "raw_value": "4006381333931",
            "evidence_ids": [f"barcode-{sample}"],
            "confidence": 0.99,
            "parser_version": "synthetic-parser-v1",
        }
    )
    return EvidencePipelineRequest(
        ocr_tokens=ocr_tokens,
        barcodes=[
            {
                "id": f"barcode-{sample}",
                "raw_value": "4006381333931",
                "format": "EAN-13",
                "confidence": 0.99,
                "decoder_version": "synthetic-barcode-v1",
                "decode_valid": True,
                "checksum_valid": True,
            }
        ],
        field_proposals=field_proposals,
        vision_model_version="synthetic-vision-v1",
        ocr_engine_version="synthetic-ocr-v1",
        barcode_decoder_version="synthetic-barcode-v1",
        master_data_version=MASTER_VERSION,
        code_version="hct414-review-perf-v1",
        adapter_version="hct414-review-adapter-v1",
        adapter_run_id=f"hct414-review-run-{sample}",
    )


def _create_household_and_member(client: TestClient, sample: int) -> tuple[str, str]:
    household = client.post(
        "/api/v1/households",
        headers={"X-Actor-ID": OWNER},
        json={"name": f"HCT-414 synthetic review household {sample}"},
    )
    if household.status_code != 201:
        raise RuntimeError(f"HOUSEHOLD_CREATE_FAILED:{household.status_code}")
    household_id = household.json()["id"]
    member = client.post(
        f"/api/v1/households/{household_id}/members",
        headers={"X-Actor-ID": OWNER},
        json={"display_name": f"Synthetic review member {sample}", "role": "SELF"},
    )
    if member.status_code != 201:
        raise RuntimeError(f"MEMBER_CREATE_FAILED:{member.status_code}")
    return household_id, member.json()["id"]


def _prepare_task(
    client: TestClient,
    *,
    file_id: str,
    quality_receipt: str,
    sample: int,
) -> tuple[str, str, dict[str, Any]]:
    _, member_id = _create_household_and_member(client, sample)
    task = client.post(
        "/api/v1/vision-tasks",
        headers={"X-Actor-ID": OWNER},
        json={
            "file_id": file_id,
            "media_type": "video",
            "member_id": member_id,
            "quality_receipt": quality_receipt,
            "idempotency_key": f"hct414-review-task-{sample}",
        },
    )
    if task.status_code != 201:
        raise RuntimeError(f"VISION_TASK_CREATE_FAILED:{task.status_code}")
    task_body = task.json()
    request = _evidence_payload(sample)
    receipt = issue_adapter_receipt(
        task_body["id"],
        task_body["input_digest"],
        request,
        get_settings().vision_adapter_signing_key,
    )
    payload = request.model_dump(mode="json")
    payload["adapter_receipt"] = receipt
    return task_body["id"], member_id, payload


def _override_session_factory() -> tuple[Any, Any]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return engine, factory


def _run_scenario(samples: int, warmup: int) -> dict[str, Any]:
    engine, session_factory = _override_session_factory()
    settings = get_settings()
    previous = {
        "file_root": settings.file_root,
        "master_data_root": settings.master_data_root,
        "master_data_approved_versions": settings.master_data_approved_versions,
        "vision_quality_enforce_retake": settings.vision_quality_enforce_retake,
        # This probe drives the API with synthetic ``X-Actor-ID`` identities, so
        # it must enable that path itself.  It previously inherited the flag from
        # whatever ``.env`` the current machine happened to have, which made the
        # probe pass locally and fail wherever the flag was absent.
        "allow_dev_actor_header": settings.allow_dev_actor_header,
    }
    process = psutil.Process()
    rss_before = process.memory_info().rss
    try:
        with tempfile.TemporaryDirectory(prefix="hct414-review-handoff-") as raw_directory:
            root = Path(raw_directory)
            file_root = root / "files"
            master_root = root / "master"
            file_root.mkdir()
            master_root.mkdir()
            fixture = file_root / "synthetic-review.mp4"
            _write_video(fixture, duration_seconds=1, sharp=True, moving=True, distinct=True)
            _write_master_snapshot(master_root)
            settings.file_root = str(file_root)
            settings.master_data_root = str(master_root)
            settings.master_data_approved_versions = MASTER_VERSION
            settings.vision_quality_enforce_retake = True
            settings.allow_dev_actor_header = True

            def override_get_session() -> Generator[Session, None, None]:
                session = session_factory()
                try:
                    yield session
                finally:
                    session.close()

            app.dependency_overrides[get_session] = override_get_session
            evidence_latencies: list[float] = []
            fusion_latencies: list[float] = []
            failures: list[dict[str, object]] = []
            review_ids: list[str] = []
            fusion_replay_checks = 0
            task_inputs: list[tuple[str, dict[str, Any]]] = []
            with TestClient(app) as client:
                quality = client.post(
                    "/api/v1/vision-quality/check",
                    headers={"X-Actor-ID": OWNER},
                    files={"file": (fixture.name, fixture.read_bytes(), "video/mp4")},
                    data={"media_type": "video"},
                )
                if quality.status_code != 200 or quality.json().get("decision") != "PASS":
                    raise RuntimeError(f"QUALITY_CHECK_FAILED:{quality.status_code}")
                quality_receipt = quality.json()["quality_receipt"]
                for sample in range(samples + warmup):
                    task_id, _, payload = _prepare_task(
                        client,
                        file_id=fixture.name,
                        quality_receipt=quality_receipt,
                        sample=sample,
                    )
                    task_inputs.append((task_id, payload))

                for index, (task_id, payload) in enumerate(task_inputs):
                    started = perf_counter()
                    evidence = client.post(
                        f"/api/v1/vision-tasks/{task_id}/evidence",
                        headers={"X-Actor-ID": OWNER},
                        json=payload,
                    )
                    elapsed = (perf_counter() - started) * 1000
                    if evidence.status_code != 200:
                        failures.append(
                            {"stage": "evidence_to_review", "status": evidence.status_code}
                        )
                        continue
                    if index >= warmup:
                        evidence_latencies.append(elapsed)

                    started = perf_counter()
                    fusion = client.post(
                        f"/api/v1/vision-tasks/{task_id}/fusion",
                        headers={"X-Actor-ID": OWNER},
                        json={},
                    )
                    elapsed = (perf_counter() - started) * 1000
                    if fusion.status_code != 200:
                        failures.append(
                            {"stage": "fusion_review_finalize", "status": fusion.status_code}
                        )
                        continue
                    if index >= warmup:
                        fusion_latencies.append(elapsed)
                    body = fusion.json()
                    review_id = body.get("review_task_id")
                    if not isinstance(review_id, str) or not review_id:
                        failures.append(
                            {"stage": "fusion_review_finalize", "status": "REVIEW_ID_MISSING"}
                        )
                        continue
                    review_ids.append(review_id)
                    repeated_fusion = client.post(
                        f"/api/v1/vision-tasks/{task_id}/fusion",
                        headers={"X-Actor-ID": OWNER},
                        json={},
                    )
                    repeated_id = repeated_fusion.json().get("review_task_id")
                    if repeated_fusion.status_code != 200 or repeated_id != review_id:
                        failures.append(
                            {
                                "stage": "fusion_review_idempotency",
                                "status": repeated_fusion.status_code,
                            }
                        )
                    else:
                        fusion_replay_checks += 1

            session = session_factory()
            try:
                review_count = session.scalar(select(func.count()).select_from(ReviewTask)) or 0
                pending_count = (
                    session.scalar(
                        select(func.count())
                        .select_from(ReviewTask)
                        .where(ReviewTask.status == "PENDING_REVIEW")
                    )
                    or 0
                )
                health_event_count = (
                    session.scalar(select(func.count()).select_from(HealthEvent)) or 0
                )
                versions = list(session.scalars(select(ReviewTask.version)).all())
            finally:
                session.close()

            expected_reviews = samples + warmup
            fixture_info = {
                "file_name": fixture.name,
                "size_bytes": fixture.stat().st_size,
                "sha256": _sha256(fixture),
                "duration_seconds": 1,
            }
    finally:
        app.dependency_overrides.clear()
        for name, value in previous.items():
            setattr(settings, name, value)
        Base.metadata.drop_all(engine)
        engine.dispose()

    rss_after = process.memory_info().rss
    if failures or len(evidence_latencies) != samples or len(fusion_latencies) != samples:
        raise RuntimeError("REVIEW_HANDOFF_SCENARIO_FAILED")

    return {
        "schema_version": REPORT_SCHEMA,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "issue": "#246 剩余项第 2 条（人工复核交接 API + DB 性能）",
        "commit_sha": _git_sha(),
        "release_status": "DEMO_ONLY",
        "environment": {
            "ci": os.environ.get("CI", "").casefold() == "true",
            "runner_os": os.environ.get("RUNNER_OS") or platform.system(),
            "platform": platform.platform(),
            "machine": platform.machine(),
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
        "process_memory": {
            "rss_before_bytes": rss_before,
            "rss_after_bytes": rss_after,
            "rss_delta_bytes": rss_after - rss_before,
        },
        "samples": samples,
        "warmup": warmup,
        "stages": {
            "evidence_to_review": {
                **_stats(evidence_latencies),
                "api": "POST /api/v1/vision-tasks/{task_id}/evidence",
            },
            "fusion_review_finalize": {
                **_stats(fusion_latencies),
                "api": "POST /api/v1/vision-tasks/{task_id}/fusion",
            },
        },
        "budgets_ms": {"review_handoff_p95": HANDOFF_P95_BUDGET_MS},
        "worst_handoff_p95_ms": round(
            max(
                _percentile(evidence_latencies, 0.95),
                _percentile(fusion_latencies, 0.95),
            ),
            3,
        ),
        "within_budget": (
            max(
                _percentile(evidence_latencies, 0.95),
                _percentile(fusion_latencies, 0.95),
            )
            <= HANDOFF_P95_BUDGET_MS
        ),
        "review_assertions": {
            "expected_review_rows": expected_reviews,
            "review_rows": review_count,
            "pending_review_rows": pending_count,
            "unique_review_ids_returned": len(set(review_ids)) == len(review_ids),
            "review_versions": sorted(set(int(version) for version in versions)),
            "health_events_before_human_confirmation": health_event_count,
        },
        "idempotency": {
            "expected_fusion_replays": expected_reviews,
            "successful_fusion_replays": fusion_replay_checks,
            "all_fusion_replays_idempotent": fusion_replay_checks == expected_reviews,
        },
        "failures": failures,
        "release_blockers": [
            "本探针只验证 API + SQLite 的复核交接，不代表生产 MySQL/多主机容量",
            "OCR 推理、HCT-201 授权固定集准确率和 Android 真机 HEVC 链路仍未验证",
        ],
        "stages_not_measured": [
            "真实 OCR 推理成本（本探针注入合成证据）",
            "人工实际点击确认后的健康事件写入耗时",
            "生产 MySQL、多主机 worker、队列和网络容量",
        ],
    }


def measure_review_handoff_performance(
    *, samples: int = DEFAULT_SAMPLES, warmup: int = DEFAULT_WARMUP
) -> dict[str, Any]:
    if samples < 1:
        raise ValueError("SAMPLES_INVALID")
    if warmup < 0:
        raise ValueError("WARMUP_INVALID")
    return _run_scenario(samples, warmup)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    parser.add_argument("--warmup", type=int, default=DEFAULT_WARMUP)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--no-enforce", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = measure_review_handoff_performance(samples=args.samples, warmup=args.warmup)
    except (RuntimeError, ValueError) as error:
        parser.error(str(error))

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    print(
        f"worst review handoff p95: {report['worst_handoff_p95_ms']} ms "
        f"(budget {HANDOFF_P95_BUDGET_MS:.0f} ms) release_status={report['release_status']}"
    )
    assertions = report["review_assertions"]
    print(
        f"review_rows={assertions['review_rows']} pending={assertions['pending_review_rows']} "
        f"unique_ids={assertions['unique_review_ids_returned']} "
        f"health_events_before_confirmation={assertions['health_events_before_human_confirmation']}"
    )

    problems: list[str] = []
    if not report["within_budget"]:
        problems.append("REVIEW_HANDOFF_P95_BUDGET_EXCEEDED")
    problems.extend(f"FAILURE:{item['stage']}:{item['status']}" for item in report["failures"])
    if assertions["review_rows"] != assertions["expected_review_rows"]:
        problems.append("REVIEW_ROW_COUNT_MISMATCH")
    if assertions["pending_review_rows"] != assertions["expected_review_rows"]:
        problems.append("PENDING_REVIEW_ROW_COUNT_MISMATCH")
    if not assertions["unique_review_ids_returned"]:
        problems.append("REVIEW_ID_DUPLICATION")
    idempotency = report["idempotency"]
    if not idempotency["all_fusion_replays_idempotent"]:
        problems.append("FUSION_REPLAY_NOT_IDEMPOTENT")
    if assertions["health_events_before_human_confirmation"] != 0:
        problems.append("HEALTH_EVENT_WRITTEN_BEFORE_CONFIRMATION")
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        if not args.no_enforce:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
