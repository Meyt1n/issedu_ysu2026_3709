from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from app import event_service
from app.config import get_settings
from app.event_service import dispatch_outbox_batch, dispatch_outbox_message
from app.models import HealthEvent, MemberStateProjection, OutboxMessage
from app.outbox_worker import dispatch_cycle, run_worker

REPO_ROOT = Path(__file__).resolve().parents[2]
OWNER_HEADERS = {"X-Actor-Id": "owner"}


def create_household_and_member(client: TestClient) -> tuple[str, str]:
    household = client.post(
        "/api/v1/households",
        headers=OWNER_HEADERS,
        json={"name": "HCT-103 synthetic household"},
    )
    assert household.status_code == 201
    household_id = household.json()["id"]
    member = client.post(
        f"/api/v1/households/{household_id}/members",
        headers=OWNER_HEADERS,
        json={"display_name": "Synthetic member", "role": "SELF"},
    )
    assert member.status_code == 201
    return household_id, member.json()["id"]


def append_confirmed_event(
    client: TestClient,
    household_id: str,
    member_id: str,
    *,
    key: str,
    value: str,
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/households/{household_id}/events",
        headers={**OWNER_HEADERS, "Idempotency-Key": key},
        json={
            "member_id": member_id,
            "event_type": "NOTE",
            "confirmation_status": "CONFIRMED",
            "payload": {"value": value},
        },
    )
    assert response.status_code == 201
    return response.json()


def test_same_idempotency_key_returns_one_result_and_rejects_conflict(
    client: TestClient,
    db_session: Session,
) -> None:
    household_id, member_id = create_household_and_member(client)
    first = append_confirmed_event(
        client, household_id, member_id, key="event-retry-1", value="first"
    )
    repeated = append_confirmed_event(
        client, household_id, member_id, key="event-retry-1", value="first"
    )

    assert repeated["id"] == first["id"]
    assert repeated["sequence_no"] == 1
    assert db_session.scalar(select(func.count()).select_from(HealthEvent)) == 1
    assert db_session.scalar(select(func.count()).select_from(OutboxMessage)) == 1

    conflict = client.post(
        f"/api/v1/households/{household_id}/events",
        headers={**OWNER_HEADERS, "Idempotency-Key": "event-retry-1"},
        json={
            "member_id": member_id,
            "event_type": "NOTE",
            "confirmation_status": "CONFIRMED",
            "payload": {"value": "different"},
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "IDEMPOTENCY_KEY_CONFLICT"


def test_projection_failure_rolls_back_event_and_outbox_atomically(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    household_id, member_id = create_household_and_member(client)

    def fail_projection(_session: Session, _event: HealthEvent) -> str:
        raise RuntimeError("synthetic projection failure")

    monkeypatch.setattr(event_service, "apply_event_to_projection", fail_projection)
    with pytest.raises(RuntimeError, match="synthetic projection failure"):
        append_confirmed_event(
            client,
            household_id,
            member_id,
            key="atomic-rollback-1",
            value="must rollback",
        )

    assert db_session.scalar(select(func.count()).select_from(HealthEvent)) == 0
    assert db_session.scalar(select(func.count()).select_from(OutboxMessage)) == 0
    assert db_session.get(MemberStateProjection, member_id) is None


def test_correction_appends_compensation_and_keeps_original(
    client: TestClient,
) -> None:
    household_id, member_id = create_household_and_member(client)
    original = append_confirmed_event(
        client, household_id, member_id, key="original-1", value="before"
    )
    correction = client.post(
        f"/api/v1/households/{household_id}/events/{original['id']}/compensations",
        headers={**OWNER_HEADERS, "Idempotency-Key": "correction-1"},
        json={
            "event_type": "NOTE_CORRECTED",
            "payload": {"value": "after"},
            "reason": "manual correction",
        },
    )
    assert correction.status_code == 201
    corrected = correction.json()
    assert corrected["supersedes_event_id"] == original["id"]
    assert corrected["sequence_no"] == 2

    events = client.get(
        f"/api/v1/households/{household_id}/events",
        headers=OWNER_HEADERS,
    ).json()
    assert [item["payload"]["value"] for item in events] == ["before", "after"]
    assert events[0]["supersedes_event_id"] is None

    state = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/state",
        headers=OWNER_HEADERS,
    ).json()
    assert state["last_sequence"] == 2
    assert state["state"]["last_event_payload"] == {"value": "after"}
    assert state["state"]["events_count"] == 2
    assert state["state"]["active_event_count"] == 1
    assert state["state"]["superseded_event_ids"] == [original["id"]]


def test_projection_replays_from_empty_and_checkpoint_deterministically(
    client: TestClient,
) -> None:
    household_id, member_id = create_household_and_member(client)
    append_confirmed_event(client, household_id, member_id, key="replay-1", value="one")
    checkpoint = client.post(
        f"/api/v1/households/{household_id}/members/{member_id}/state/checkpoints",
        headers=OWNER_HEADERS,
    )
    assert checkpoint.status_code == 201
    checkpoint_id = checkpoint.json()["id"]
    append_confirmed_event(client, household_id, member_id, key="replay-2", value="two")

    online = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/state",
        headers=OWNER_HEADERS,
    ).json()
    from_empty = client.post(
        f"/api/v1/households/{household_id}/members/{member_id}/state/replay",
        headers=OWNER_HEADERS,
        json={},
    )
    assert from_empty.status_code == 200
    assert from_empty.json()["consistent_with_online"] is True
    assert from_empty.json()["events_replayed"] == 2
    assert from_empty.json()["rebuilt_state_hash"] == online["state_hash"]

    from_checkpoint = client.post(
        f"/api/v1/households/{household_id}/members/{member_id}/state/replay",
        headers=OWNER_HEADERS,
        json={"checkpoint_id": checkpoint_id},
    )
    assert from_checkpoint.status_code == 200
    assert from_checkpoint.json()["consistent_with_online"] is True
    assert from_checkpoint.json()["events_replayed"] == 1


def test_outbox_failure_stale_lock_and_duplicate_delivery_are_recoverable(
    client: TestClient,
    db_session: Session,
) -> None:
    household_id, member_id = create_household_and_member(client)
    event = append_confirmed_event(
        client, household_id, member_id, key="outbox-retry-1", value="one"
    )
    projection = db_session.get(MemberStateProjection, member_id)
    assert projection is not None
    original_version = projection.version

    def unavailable(_session: Session, _event: HealthEvent) -> None:
        raise RuntimeError("synthetic downstream unavailable")

    failed = dispatch_outbox_batch(
        db_session,
        household_id=household_id,
        max_messages=10,
        deliver=unavailable,
    )
    assert failed.failed == 1
    message = db_session.scalar(select(OutboxMessage).where(OutboxMessage.event_id == event["id"]))
    assert message is not None
    assert message.status == "FAILED"
    assert message.last_error == "DOWNSTREAM_UNAVAILABLE"

    message.status = "PROCESSING"
    message.locked_at = datetime.now(UTC) - timedelta(minutes=10)
    db_session.commit()
    recovered = dispatch_outbox_batch(
        db_session,
        household_id=household_id,
        max_messages=10,
        stale_after=timedelta(minutes=5),
    )
    assert recovered.recovered_stale == 1
    assert recovered.dispatched == 1
    db_session.refresh(message)
    db_session.refresh(projection)
    assert message.status == "DISPATCHED"
    assert message.attempts == 2
    assert projection.version == original_version


def test_worker_cycle_dispatches_and_writes_readiness(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    household_id, member_id = create_household_and_member(client)
    append_confirmed_event(client, household_id, member_id, key="worker-1", value="one")

    summary = dispatch_cycle(db_session)
    assert summary.dispatched == 1
    message = db_session.scalar(select(OutboxMessage))
    assert message is not None and message.status == "DISPATCHED"

    class SessionScope:
        def __enter__(self) -> Session:
            return db_session

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr("app.outbox_worker.SessionLocal", SessionScope)
    ready_file = tmp_path / "outbox-worker.ready"
    assert run_worker(loop=False, ready_file=ready_file) == 0
    assert ready_file.read_text(encoding="ascii") == "ready\n"

    assert dispatch_outbox_message(db_session, message.id) == "ALREADY_DISPATCHED"


def test_out_of_order_delivery_waits_for_missing_confirmed_event(
    client: TestClient,
    db_session: Session,
) -> None:
    household_id, member_id = create_household_and_member(client)
    first = append_confirmed_event(client, household_id, member_id, key="ordered-1", value="one")
    second = append_confirmed_event(client, household_id, member_id, key="ordered-2", value="two")
    first_message = db_session.scalar(
        select(OutboxMessage).where(OutboxMessage.event_id == first["id"])
    )
    second_message = db_session.scalar(
        select(OutboxMessage).where(OutboxMessage.event_id == second["id"])
    )
    assert first_message is not None and second_message is not None

    db_session.delete(db_session.get(MemberStateProjection, member_id))
    db_session.commit()
    assert dispatch_outbox_message(db_session, second_message.id) == "OUT_OF_ORDER"
    assert dispatch_outbox_message(db_session, first_message.id) == "DISPATCHED"
    assert dispatch_outbox_message(db_session, second_message.id) == "DISPATCHED"
    projection = db_session.get(MemberStateProjection, member_id)
    assert projection is not None
    assert projection.last_sequence == 2
    assert projection.state["last_event_payload"] == {"value": "two"}


def test_hct103_migration_preserves_existing_events_and_blocks_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "hct103-upgrade.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config(str(REPO_ROOT / "alembic.ini"))
    engine = create_engine(database_url)
    try:
        command.upgrade(config, "0003_hct102_auth_security")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO household (id, name, created_by) "
                    "VALUES ('household-1', 'Existing', 'owner')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO member (id, household_id, display_name, role) "
                    "VALUES ('member-1', 'household-1', 'Existing member', 'SELF')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO health_event ("
                    "id, household_id, member_id, event_type, source, confirmation_status, "
                    "payload, evidence, created_by, confirmed_by"
                    ") VALUES ("
                    "'event-1', 'household-1', 'member-1', 'NOTE', 'MANUAL', 'CONFIRMED', "
                    "'{\"value\":\"existing\"}', '{}', 'owner', 'owner'"
                    ")"
                )
            )
        command.upgrade(config, "head")
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT sequence_no, schema_version, correlation_id "
                    "FROM health_event WHERE id = 'event-1'"
                )
            ).one()
            assert row.sequence_no == 1
            assert row.schema_version == 1
            assert row.correlation_id == "event-1"
            with pytest.raises(DatabaseError, match="HEALTH_EVENT_IMMUTABLE"):
                connection.execute(
                    text("UPDATE health_event SET event_type = 'ALTERED' WHERE id = 'event-1'")
                )
    finally:
        engine.dispose()
        get_settings.cache_clear()
