"""HCT-405 API E2E scenarios for vision, review, deletion, and rollback."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import Any

import cv2
import numpy as np
import pytest
from ai.vision.evidence_pipeline import EvidencePipelineRequest, issue_adapter_receipt
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import Base, HealthEvent, Household, Member, OutboxMessage, VisionTask
from app.review import FusionStatus, ReviewStatus, ReviewTask, create_review_task

OWNER_HEADERS = {"X-Actor-Id": "e2e-owner"}
MASTER_VERSION = "hct405-master-v1"


def _create_household_and_member(client: TestClient) -> tuple[str, str]:
    household = client.post(
        "/api/v1/households",
        headers=OWNER_HEADERS,
        json={"name": "HCT-405 synthetic household"},
    )
    assert household.status_code == 201, household.text
    household_id = household.json()["id"]

    member = client.post(
        f"/api/v1/households/{household_id}/members",
        headers=OWNER_HEADERS,
        json={"display_name": "Synthetic member", "role": "SELF"},
    )
    assert member.status_code == 201, member.text
    return household_id, member.json()["id"]


def _encode_demo_image() -> bytes:
    image = np.full((480, 640, 3), 110, dtype=np.uint8)
    cv2.rectangle(image, (140, 90), (500, 390), (225, 225, 225), -1)
    cv2.rectangle(image, (140, 90), (500, 390), (20, 20, 20), 6)
    cv2.putText(
        image,
        "SYNTHETIC",
        (170, 245),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        (20, 20, 20),
        4,
    )
    encoded_ok, encoded = cv2.imencode(".png", image)
    assert encoded_ok
    return encoded.tobytes()


def _write_master_snapshot(root: Path) -> None:
    snapshot: dict[str, Any] = {
        "schema_version": "hct-master-data/v1",
        "version": MASTER_VERSION,
        "approval_status": "APPROVED",
        "approval_ref": "hct405-synthetic-approval",
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
        json.dumps(snapshot, ensure_ascii=False),
        encoding="utf-8",
    )


def _matched_payload() -> dict[str, Any]:
    raw_fields = {
        "drug_name": ("Synthetic Medicine", "ocr-name"),
        "specification": ("10mg", "ocr-specification"),
        "manufacturer": ("Synthetic Labs", "ocr-manufacturer"),
        "batch_number": ("SYN-BATCH-1", "ocr-batch"),
        "expiry_date": ("2030-01", "ocr-expiry"),
        "packaging_type": ("medicine_box", "ocr-packaging"),
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
            "evidence_ids": ["barcode-1"],
            "confidence": 0.99,
            "parser_version": "synthetic-parser-v1",
        }
    )
    return {
        "ocr_tokens": ocr_tokens,
        "barcodes": [
            {
                "id": "barcode-1",
                "raw_value": "4006381333931",
                "format": "EAN-13",
                "confidence": 0.99,
                "decoder_version": "synthetic-barcode-v1",
            }
        ],
        "field_proposals": field_proposals,
        "vision_model_version": "synthetic-vision-v1",
        "ocr_engine_version": "synthetic-ocr-v1",
        "barcode_decoder_version": "synthetic-barcode-v1",
        "master_data_version": MASTER_VERSION,
        "code_version": "hct405-e2e-v1",
        "adapter_version": "hct405-adapter-v1",
        "adapter_run_id": "hct405-matched-run",
    }


def _conflict_payload() -> dict[str, Any]:
    return {
        "ocr_tokens": [
            {
                "id": "ocr-name-a",
                "raw_value": "Synthetic Medicine",
                "confidence": 0.95,
                "engine_version": "synthetic-ocr-v1",
            },
            {
                "id": "ocr-name-b",
                "raw_value": "Conflicting Medicine",
                "confidence": 0.95,
                "engine_version": "synthetic-ocr-v1",
            },
        ],
        "field_proposals": [
            {
                "field_name": "drug_name",
                "raw_value": "Synthetic Medicine",
                "evidence_ids": ["ocr-name-a"],
                "confidence": 0.95,
                "parser_version": "synthetic-parser-v1",
            },
            {
                "field_name": "drug_name",
                "raw_value": "Conflicting Medicine",
                "evidence_ids": ["ocr-name-b"],
                "confidence": 0.95,
                "parser_version": "synthetic-parser-v1",
            },
        ],
        "master_data_version": MASTER_VERSION,
        "code_version": "hct405-e2e-v1",
        "adapter_version": "hct405-adapter-v1",
        "adapter_run_id": "hct405-conflict-run",
    }


def _run_vision_flow(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    payload: dict[str, Any],
    with_master: bool,
) -> tuple[dict[str, Any], str, str, str]:
    household_id, member_id = _create_household_and_member(client)
    content = _encode_demo_image()
    quality = client.post(
        "/api/v1/vision-quality/check",
        headers=OWNER_HEADERS,
        files={"file": ("synthetic.png", content, "image/png")},
        data={"media_type": "image"},
    )
    assert quality.status_code == 200, quality.text
    assert quality.json()["decision"] == "PASS"

    file_id = "hct405-synthetic.png"
    (tmp_path / file_id).write_bytes(content)
    monkeypatch.setattr("app.routes.settings.file_root", str(tmp_path))
    if with_master:
        _write_master_snapshot(tmp_path)
        monkeypatch.setattr("app.routes.settings.master_data_root", str(tmp_path))
        monkeypatch.setattr(
            "app.routes.settings.master_data_approved_versions",
            MASTER_VERSION,
        )

    task = client.post(
        "/api/v1/vision-tasks",
        headers=OWNER_HEADERS,
        json={
            "file_id": file_id,
            "member_id": member_id,
            "quality_receipt": quality.json()["quality_receipt"],
        },
    )
    assert task.status_code == 201, task.text
    task_body = task.json()

    request = EvidencePipelineRequest.model_validate(payload)
    receipt = issue_adapter_receipt(
        task_body["id"],
        task_body["input_digest"],
        request,
        get_settings().vision_adapter_signing_key,
    )
    evidence = client.post(
        f"/api/v1/vision-tasks/{task_body['id']}/evidence",
        headers=OWNER_HEADERS,
        json={**payload, "adapter_receipt": receipt},
    )
    assert evidence.status_code == 200, evidence.text
    assert all(field["confirmation_status"] == "UNCONFIRMED" for field in evidence.json()["fields"])

    fusion = client.post(
        f"/api/v1/vision-tasks/{task_body['id']}/fusion",
        headers=OWNER_HEADERS,
        json={},
    )
    assert fusion.status_code == 200, fusion.text

    timeline = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/timeline",
        headers=OWNER_HEADERS,
    )
    assert timeline.status_code == 200, timeline.text
    assert timeline.json() == []
    return fusion.json(), household_id, member_id, task_body["id"]


def test_matched_vision_result_still_requires_manual_confirmation(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fusion, household_id, member_id, vision_task_id = _run_vision_flow(
        client,
        tmp_path,
        monkeypatch,
        payload=_matched_payload(),
        with_master=True,
    )

    assert fusion["status"] == "MATCHED"
    assert fusion["selected_candidate_id"] == "synthetic-medication-1"
    assert fusion["requires_human_confirmation"] is True
    assert fusion["health_event_allowed"] is False
    assert fusion["versions"]["master_data_version"] == MASTER_VERSION
    assert fusion["review_task_version"] == 1

    repeated = client.post(
        f"/api/v1/vision-tasks/{vision_task_id}/fusion",
        headers=OWNER_HEADERS,
        json={},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["review_task_id"] == fusion["review_task_id"]

    changed_thresholds = client.post(
        f"/api/v1/vision-tasks/{vision_task_id}/fusion",
        headers=OWNER_HEADERS,
        json={"matched_score": 0.81},
    )
    assert changed_thresholds.status_code == 409
    assert changed_thresholds.json()["detail"] == "REVIEW_TASK_FUSION_CONFLICT"

    pending = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/review-tasks",
        headers=OWNER_HEADERS,
    )
    assert pending.status_code == 200, pending.text
    assert [task["id"] for task in pending.json()] == [fusion["review_task_id"]]


def test_conflicting_vision_result_does_not_create_health_fact(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fusion, _, _, _ = _run_vision_flow(
        client,
        tmp_path,
        monkeypatch,
        payload=_conflict_payload(),
        with_master=True,
    )

    assert fusion["status"] == "CONFLICT"
    assert "EVIDENCE_CONFLICT" in fusion["reasons"]
    assert fusion["health_event_allowed"] is False


def test_unknown_vision_result_does_not_create_health_fact(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fusion, _, _, _ = _run_vision_flow(
        client,
        tmp_path,
        monkeypatch,
        payload={
            "master_data_version": "missing-synthetic-master",
            "code_version": "hct405-e2e-v1",
            "adapter_version": "hct405-adapter-v1",
            "adapter_run_id": "hct405-unknown-run",
        },
        with_master=False,
    )

    assert fusion["status"] == "UNKNOWN"
    assert "NO_MASTER_CANDIDATE" in fusion["reasons"]
    assert fusion["health_event_allowed"] is False


def test_write_only_caregiver_cannot_read_fusion_result(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, household_id, member_id, vision_task_id = _run_vision_flow(
        client,
        tmp_path,
        monkeypatch,
        payload=_matched_payload(),
        with_master=True,
    )
    authorization = client.post(
        f"/api/v1/households/{household_id}/authorizations",
        headers=OWNER_HEADERS,
        json={
            "member_id": member_id,
            "grantee_actor_id": "write-only-caregiver",
            "data_fields": ["health_events"],
            "actions": ["WRITE_EVENTS"],
            "purpose": "vision-entry",
            "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    assert authorization.status_code == 201, authorization.text

    denied = client.post(
        f"/api/v1/vision-tasks/{vision_task_id}/fusion",
        headers={
            "X-Actor-ID": "write-only-caregiver",
            "X-Access-Purpose": "vision-entry",
        },
        json={},
    )
    assert denied.status_code == 404
    assert denied.json()["detail"] == "VISION_TASK_NOT_FOUND"


def test_revoked_caregiver_cannot_access_or_mutate_vision_task(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    household_id, member_id = _create_household_and_member(client)
    authorization = client.post(
        f"/api/v1/households/{household_id}/authorizations",
        headers=OWNER_HEADERS,
        json={
            "member_id": member_id,
            "grantee_actor_id": "vision-caregiver",
            "data_fields": ["health_events"],
            "actions": ["READ_EVENTS", "WRITE_EVENTS"],
            "purpose": "vision-entry",
            "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    assert authorization.status_code == 201, authorization.text
    caregiver_headers = {
        "X-Actor-ID": "vision-caregiver",
        "X-Access-Purpose": "vision-entry",
    }
    content = _encode_demo_image()
    quality = client.post(
        "/api/v1/vision-quality/check",
        headers={"X-Actor-ID": "vision-caregiver"},
        files={"file": ("caregiver.png", content, "image/png")},
        data={"media_type": "image"},
    )
    assert quality.status_code == 200, quality.text
    file_id = "caregiver-vision.png"
    (tmp_path / file_id).write_bytes(content)
    monkeypatch.setattr("app.routes.settings.file_root", str(tmp_path))
    created = client.post(
        "/api/v1/vision-tasks",
        headers=caregiver_headers,
        json={
            "file_id": file_id,
            "member_id": member_id,
            "quality_receipt": quality.json()["quality_receipt"],
        },
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]
    assert (
        client.get(
            f"/api/v1/vision-tasks/{task_id}",
            headers=caregiver_headers,
        ).status_code
        == 200
    )
    listed = client.get(
        f"/api/v1/households/{household_id}/vision-tasks",
        headers=caregiver_headers,
        params={"member_id": member_id},
    )
    assert listed.status_code == 200, listed.text
    assert [task["id"] for task in listed.json()] == [task_id]

    revoked = client.post(
        (
            f"/api/v1/households/{household_id}/authorizations/"
            f"{authorization.json()['id']}/revoke"
        ),
        headers=OWNER_HEADERS,
        json={"expected_version": authorization.json()["version"]},
    )
    assert revoked.status_code == 200, revoked.text

    denied_responses = [
        client.get(
            f"/api/v1/vision-tasks/{task_id}",
            headers=caregiver_headers,
        ),
        client.post(
            f"/api/v1/vision-tasks/{task_id}/fusion",
            headers=caregiver_headers,
            json={},
        ),
        client.post(
            f"/api/v1/vision-tasks/{task_id}/cancel",
            headers=caregiver_headers,
        ),
        client.get(
            f"/api/v1/households/{household_id}/vision-tasks",
            headers=caregiver_headers,
            params={"member_id": member_id},
        ),
    ]
    assert all(response.status_code == 404 for response in denied_responses)
    assert all(
        response.json()["detail"] in {"VISION_TASK_NOT_FOUND", "HOUSEHOLD_NOT_FOUND"}
        for response in denied_responses
    )
    stored = db_session.get(VisionTask, task_id)
    assert stored is not None
    assert stored.status == "queued"


def test_manual_review_correction_creates_one_confirmed_event(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fusion, household_id, member_id, vision_task_id = _run_vision_flow(
        client,
        tmp_path,
        monkeypatch,
        payload=_conflict_payload(),
        with_master=True,
    )

    corrected = client.post(
        (
            f"/api/v1/households/{household_id}/review-tasks/"
            f"{fusion['review_task_id']}/correct"
        ),
        headers={**OWNER_HEADERS, "Idempotency-Key": "hct405-correction-1"},
        json={
            "expected_version": fusion["review_task_version"],
            "manual_payload": {"drug_name": "Corrected synthetic medication"},
            "correction_note": "Synthetic OCR correction",
        },
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["status"] == "CORRECTED"
    assert corrected.json()["manual_payload"] == {
        "drug_name": "Corrected synthetic medication"
    }

    timeline = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/timeline",
        headers=OWNER_HEADERS,
    )
    assert timeline.status_code == 200, timeline.text
    assert len(timeline.json()) == 1
    event = timeline.json()[0]
    assert event["event_type"] == "medication_corrected"
    assert event["confirmation_status"] == "CONFIRMED"
    assert event["payload"]["drug_name"] == "Corrected synthetic medication"
    assert event["evidence"]["review_task_id"] == fusion["review_task_id"]
    assert event["evidence"]["fusion_context"]["thresholds"]["matched_score"] == 0.5

    repeated_fusion = client.post(
        f"/api/v1/vision-tasks/{vision_task_id}/fusion",
        headers=OWNER_HEADERS,
        json={},
    )
    assert repeated_fusion.status_code == 200, repeated_fusion.text
    assert repeated_fusion.json()["review_task_id"] == fusion["review_task_id"]
    assert repeated_fusion.json()["review_task_version"] == 2


def test_review_confirmation_enforces_member_read_write_authorization(
    client: TestClient,
    db_session: Session,
) -> None:
    household_id, member_id = _create_household_and_member(client)
    review = create_review_task(
        db_session,
        vision_task_id="authorized-vision-task",
        household_id=household_id,
        member_id=member_id,
        candidates=[{"drug_name": "Synthetic candidate"}],
        fusion_status=FusionStatus.MATCHED,
    )
    db_session.commit()

    missing_version = client.post(
        f"/api/v1/households/{household_id}/review-tasks/{review.id}/confirm",
        headers={**OWNER_HEADERS, "Idempotency-Key": "missing-version"},
        json={"selected_index": 0},
    )
    assert missing_version.status_code == 422

    denied = client.post(
        f"/api/v1/households/{household_id}/review-tasks/{review.id}/confirm",
        headers={
            "X-Actor-ID": "unauthorized-caregiver",
            "X-Access-Purpose": "family-care",
            "Idempotency-Key": "denied-confirm",
        },
        json={"expected_version": 1, "selected_index": 0},
    )
    assert denied.status_code == 404

    write_only_authorization = client.post(
        f"/api/v1/households/{household_id}/authorizations",
        headers=OWNER_HEADERS,
        json={
            "member_id": member_id,
            "grantee_actor_id": "write-only-reviewer",
            "data_fields": ["health_events"],
            "actions": ["WRITE_EVENTS"],
            "purpose": "family-care",
            "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    assert write_only_authorization.status_code == 201, write_only_authorization.text
    denied_write_only = client.post(
        f"/api/v1/households/{household_id}/review-tasks/{review.id}/confirm",
        headers={
            "X-Actor-ID": "write-only-reviewer",
            "X-Access-Purpose": "family-care",
            "Idempotency-Key": "write-only-confirm",
        },
        json={"expected_version": 1, "selected_index": 0},
    )
    assert denied_write_only.status_code == 404

    authorization = client.post(
        f"/api/v1/households/{household_id}/authorizations",
        headers=OWNER_HEADERS,
        json={
            "member_id": member_id,
            "grantee_actor_id": "authorized-caregiver",
            "data_fields": ["health_events"],
            "actions": ["READ_EVENTS", "WRITE_EVENTS"],
            "purpose": "family-care",
            "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    assert authorization.status_code == 201, authorization.text

    confirmed = client.post(
        f"/api/v1/households/{household_id}/review-tasks/{review.id}/confirm",
        headers={
            "X-Actor-ID": "authorized-caregiver",
            "X-Access-Purpose": "family-care",
            "Idempotency-Key": "authorized-confirm",
        },
        json={"expected_version": 1, "selected_index": 0},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "CONFIRMED"
    assert confirmed.json()["confirmed_by"] == "authorized-caregiver"


def test_concurrent_review_confirm_and_correct_create_one_event_and_outbox(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'review-race.db').as_posix()}"
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False, "timeout": 10},
        poolclass=NullPool,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    with session_factory() as setup_session:
        household = Household(name="Concurrent household", created_by="concurrent-owner")
        setup_session.add(household)
        setup_session.flush()
        member = Member(
            household_id=household.id,
            display_name="Concurrent member",
            role="SELF",
        )
        setup_session.add(member)
        setup_session.flush()
        review = create_review_task(
            setup_session,
            vision_task_id="concurrent-vision-task",
            household_id=household.id,
            member_id=member.id,
            candidates=[{"drug_name": "Synthetic candidate"}],
            fusion_status=FusionStatus.MATCHED,
        )
        setup_session.commit()
        household_id = household.id
        review_id = review.id

    def override_get_session() -> Generator[Session, None, None]:
        request_session = session_factory()
        try:
            yield request_session
        finally:
            request_session.close()

    start = Barrier(2)

    def transition(
        operation: str,
        idempotency_key: str,
        concurrent_client: TestClient,
    ) -> tuple[int, dict]:
        start.wait(timeout=5)
        response = concurrent_client.post(
            (
                f"/api/v1/households/{household_id}/review-tasks/"
                f"{review_id}/{operation}"
            ),
            headers={
                "X-Actor-ID": "concurrent-owner",
                "Idempotency-Key": idempotency_key,
            },
            json=(
                {"expected_version": 1, "selected_index": 0}
                if operation == "confirm"
                else {
                    "expected_version": 1,
                    "manual_payload": {"drug_name": "Concurrent correction"},
                }
            ),
        )
        return response.status_code, response.json()

    app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(app) as concurrent_client:
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(
                    executor.map(
                        lambda request: transition(*request, concurrent_client),
                        [
                            ("confirm", "concurrent-confirm"),
                            ("correct", "concurrent-correct"),
                        ],
                    )
                )
        assert sorted(status_code for status_code, _ in results) == [200, 409]
        conflict = next(body for status_code, body in results if status_code == 409)
        assert conflict["detail"] in {
            "REVIEW_ALREADY_CONFIRMED",
            "REVIEW_ALREADY_CORRECTED",
            "REVIEW_VERSION_CONFLICT",
        }

        with session_factory() as verification_session:
            stored_review = verification_session.get(ReviewTask, review_id)
            assert stored_review is not None
            assert stored_review.status in {
                ReviewStatus.CONFIRMED,
                ReviewStatus.CORRECTED,
            }
            assert stored_review.version == 2
            assert (
                verification_session.scalar(
                    select(func.count()).select_from(HealthEvent)
                )
                == 1
            )
            assert (
                verification_session.scalar(
                    select(func.count()).select_from(OutboxMessage)
                )
                == 1
            )
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_hard_sample_deletion_revokes_consent_and_invalidates_export(
    client: TestClient,
) -> None:
    household_id, member_id = _create_household_and_member(client)
    event = client.post(
        f"/api/v1/households/{household_id}/events",
        headers=OWNER_HEADERS,
        json={
            "member_id": member_id,
            "event_type": "medication_confirmed",
            "confirmation_status": "CONFIRMED",
            "payload": {"drug_name": "Synthetic medication"},
        },
    )
    assert event.status_code == 201, event.text

    sample = client.post(
        f"/api/v1/households/{household_id}/hard-samples",
        headers=OWNER_HEADERS,
        json={
            "source_event_id": event.json()["id"],
            "member_id": member_id,
            "category": "hard_font",
            "note": "HCT-405 synthetic deletion scenario",
        },
    )
    assert sample.status_code == 201, sample.text
    sample_id = sample.json()["id"]

    approved = client.patch(
        f"/api/v1/households/{household_id}/hard-samples/{sample_id}",
        headers=OWNER_HEADERS,
        json={"status": "approved", "note": "Synthetic approval"},
    )
    assert approved.status_code == 200, approved.text

    consent = client.post(
        f"/api/v1/households/{household_id}/hard-samples/{sample_id}/training-consent",
        headers=OWNER_HEADERS,
        json={"scope": {"purpose": "synthetic-e2e"}, "license": "internal"},
    )
    assert consent.status_code == 201, consent.text
    assert consent.json()["status"] == "active"

    manifest = client.post(
        f"/api/v1/households/{household_id}/export-manifests",
        headers=OWNER_HEADERS,
        json={
            "version": "hct405-delete-v1",
            "group_key": "synthetic-group",
            "license": "internal",
            "sample_ids": [sample_id],
        },
    )
    assert manifest.status_code == 201, manifest.text
    manifest_id = manifest.json()["id"]

    deleted = client.delete(
        f"/api/v1/households/{household_id}/hard-samples/{sample_id}",
        headers=OWNER_HEADERS,
    )
    assert deleted.status_code == 200, deleted.text

    active_consent = client.get(
        f"/api/v1/households/{household_id}/hard-samples/{sample_id}/training-consent",
        headers=OWNER_HEADERS,
    )
    assert active_consent.status_code == 200, active_consent.text
    assert active_consent.json() is None

    invalidated = client.get(
        f"/api/v1/households/{household_id}/export-manifests/{manifest_id}",
        headers=OWNER_HEADERS,
    )
    assert invalidated.status_code == 200, invalidated.text
    assert invalidated.json()["status"] == "invalidated"

    visible_samples = client.get(
        f"/api/v1/households/{household_id}/hard-samples",
        headers=OWNER_HEADERS,
    )
    assert visible_samples.status_code == 200
    assert visible_samples.json() == []


def test_v2_binding_comparison_and_rollback_restore_previous_release(
    client: TestClient,
) -> None:
    def create_binding(dataset_version: str, report_hash: str) -> str:
        response = client.post(
            "/api/v1/model-version-bindings",
            headers=OWNER_HEADERS,
            json={
                "model_id": "hct405-synthetic-model",
                "dataset_version": dataset_version,
                "fixed_set_hash": f"fixed-{dataset_version}",
                "comparison_report_hash": report_hash,
            },
        )
        assert response.status_code == 201, response.text
        return response.json()["id"]

    v1_id = create_binding("synthetic-v1", "report-v1")
    activated_v1 = client.post(
        f"/api/v1/model-version-bindings/{v1_id}/activate",
        headers=OWNER_HEADERS,
        json={"approved_by": "independent-reviewer"},
    )
    assert activated_v1.status_code == 200, activated_v1.text

    v2_id = create_binding("synthetic-v2", "report-v2")
    comparison = client.get(
        f"/api/v1/model-version-bindings/{v2_id}/comparison",
        headers=OWNER_HEADERS,
    )
    assert comparison.status_code == 200, comparison.text
    assert comparison.json()["fixed_set_hash"] == "fixed-synthetic-v2"
    assert comparison.json()["comparison_report_hash"] == "report-v2"

    activated_v2 = client.post(
        f"/api/v1/model-version-bindings/{v2_id}/activate",
        headers=OWNER_HEADERS,
        json={"approved_by": "independent-reviewer"},
    )
    assert activated_v2.status_code == 200, activated_v2.text

    rolled_back = client.post(
        f"/api/v1/model-version-bindings/{v2_id}/rollback",
        headers=OWNER_HEADERS,
        json={"reason": "Synthetic HCT-405 rollback drill"},
    )
    assert rolled_back.status_code == 200, rolled_back.text
    assert rolled_back.json()["release_status"] == "revoked"

    previous = client.get(
        f"/api/v1/model-version-bindings/{v1_id}",
        headers=OWNER_HEADERS,
    )
    assert previous.status_code == 200, previous.text
    assert previous.json()["release_status"] == "active"
