import copy
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    HealthEvent,
    Household,
    Member,
    MemberStateProjection,
    OutboxMessage,
    ProjectionCheckpoint,
)
from app.schemas import HealthEventCompensationCreate, HealthEventCreate


class IdempotencyConflictError(ValueError):
    pass


class EventAlreadySupersededError(ValueError):
    pass


class EventOrderGapError(RuntimeError):
    pass


class CheckpointInvalidError(ValueError):
    pass


@dataclass(frozen=True)
class DispatchSummary:
    inspected: int = 0
    dispatched: int = 0
    failed: int = 0
    out_of_order: int = 0
    recovered_stale: int = 0


@dataclass(frozen=True)
class ReplayResult:
    member_id: str
    checkpoint_id: str | None
    events_replayed: int
    previous_state_hash: str | None
    rebuilt_state_hash: str
    consistent_with_online: bool
    last_sequence: int
    projection_version: int


Delivery = Callable[[Session, HealthEvent], None]


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def event_request_fingerprint(*, operation: str, actor_id: str, payload: object) -> str:
    return canonical_hash({"operation": operation, "actor_id": actor_id, "payload": payload})


def normalize_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > 128:
        raise ValueError("IDEMPOTENCY_KEY_INVALID")
    return normalized


def _next_member_sequence(session: Session, member_id: str) -> int:
    session.execute(select(Member.id).where(Member.id == member_id).with_for_update()).scalar_one()
    latest = session.scalar(
        select(func.max(HealthEvent.sequence_no)).where(HealthEvent.member_id == member_id)
    )
    return int(latest or 0) + 1


def _existing_idempotent_event(
    session: Session,
    *,
    household_id: str,
    idempotency_key: str | None,
    fingerprint: str,
) -> HealthEvent | None:
    if idempotency_key is None:
        return None
    existing = session.scalar(
        select(HealthEvent).where(
            HealthEvent.household_id == household_id,
            HealthEvent.idempotency_key == idempotency_key,
        )
    )
    if existing is not None and existing.request_fingerprint != fingerprint:
        raise IdempotencyConflictError("IDEMPOTENCY_KEY_CONFLICT")
    return existing


def reduce_projection_state(
    state: dict[str, Any],
    event: HealthEvent,
) -> dict[str, Any]:
    result = copy.deepcopy(state)
    superseded = set(result.get("superseded_event_ids", []))
    if event.supersedes_event_id is not None:
        superseded.add(event.supersedes_event_id)
    events_count = int(result.get("events_count", 0)) + 1
    result.update(
        {
            "last_event_type": event.event_type,
            "last_event_payload": copy.deepcopy(event.payload),
            "events_count": events_count,
            "active_event_count": events_count - len(superseded),
            "superseded_event_ids": sorted(superseded),
        }
    )
    return result


def apply_event_to_projection(session: Session, event: HealthEvent) -> str:
    if event.confirmation_status != "CONFIRMED":
        return "IGNORED_UNCONFIRMED"

    projection = session.get(MemberStateProjection, event.member_id)
    last_sequence = projection.last_sequence if projection is not None else 0
    if event.sequence_no <= last_sequence:
        return "ALREADY_APPLIED"

    missing = session.scalar(
        select(HealthEvent.id)
        .where(
            HealthEvent.member_id == event.member_id,
            HealthEvent.confirmation_status == "CONFIRMED",
            HealthEvent.sequence_no > last_sequence,
            HealthEvent.sequence_no < event.sequence_no,
        )
        .order_by(HealthEvent.sequence_no)
        .limit(1)
    )
    if missing is not None:
        raise EventOrderGapError("OUT_OF_ORDER")

    if projection is None:
        projection = MemberStateProjection(
            member_id=event.member_id,
            household_id=event.household_id,
            state={},
            last_sequence=0,
            version=0,
        )
        session.add(projection)
    projection.state = reduce_projection_state(projection.state or {}, event)
    projection.last_event_id = event.id
    projection.last_sequence = event.sequence_no
    projection.version = int(projection.version or 0) + 1
    projection.state_hash = canonical_hash(projection.state)
    projection.updated_at = datetime.now(UTC)
    return "APPLIED"


def _append_event(
    session: Session,
    *,
    household: Household,
    member: Member,
    actor_id: str,
    idempotency_key: str | None,
    fingerprint: str,
    correlation_id: str,
    event_type: str,
    source: str,
    confirmation_status: str,
    payload: dict[str, Any],
    evidence: dict[str, Any],
    occurred_at: datetime | None,
    causation_id: str | None = None,
    supersedes_event_id: str | None = None,
) -> HealthEvent:
    existing = _existing_idempotent_event(
        session,
        household_id=household.id,
        idempotency_key=idempotency_key,
        fingerprint=fingerprint,
    )
    if existing is not None:
        return existing

    event = HealthEvent(
        household_id=household.id,
        member_id=member.id,
        sequence_no=_next_member_sequence(session, member.id),
        event_type=event_type,
        source=source,
        confirmation_status=confirmation_status,
        payload=payload,
        evidence=evidence,
        created_by=actor_id,
        confirmed_by=actor_id if confirmation_status == "CONFIRMED" else None,
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
        correlation_id=correlation_id,
        causation_id=causation_id,
        compensates_event_id=supersedes_event_id,
        supersedes_event_id=supersedes_event_id,
        schema_version=1,
        occurred_at=occurred_at or datetime.now(UTC),
    )
    session.add(event)
    session.flush()
    session.add(
        OutboxMessage(
            event_id=event.id,
            topic=(
                "health_event.compensated"
                if supersedes_event_id is not None
                else (
                    "health_event.created"
                    if confirmation_status == "CONFIRMED"
                    else "health_event.pending"
                )
            ),
            payload={
                "event_id": event.id,
                "household_id": household.id,
                "member_id": member.id,
                "sequence_no": event.sequence_no,
                "confirmation_status": event.confirmation_status,
                "schema_version": event.schema_version,
            },
        )
    )
    apply_event_to_projection(session, event)
    return event


def append_health_event_transaction(
    session: Session,
    *,
    household: Household,
    member: Member,
    actor_id: str,
    idempotency_key: str | None,
    correlation_id: str,
    payload: HealthEventCreate,
) -> HealthEvent:
    normalized_key = normalize_idempotency_key(idempotency_key)
    fingerprint = event_request_fingerprint(
        operation="APPEND_EVENT",
        actor_id=actor_id,
        payload=payload.model_dump(mode="json"),
    )
    try:
        event = _append_event(
            session,
            household=household,
            member=member,
            actor_id=actor_id,
            idempotency_key=normalized_key,
            fingerprint=fingerprint,
            correlation_id=correlation_id,
            event_type=payload.event_type,
            source=payload.source,
            confirmation_status=payload.confirmation_status,
            payload=payload.payload,
            evidence=payload.evidence,
            occurred_at=payload.occurred_at,
        )
        session.commit()
        session.refresh(event)
        return event
    except IntegrityError:
        session.rollback()
        existing = _existing_idempotent_event(
            session,
            household_id=household.id,
            idempotency_key=normalized_key,
            fingerprint=fingerprint,
        )
        if existing is not None:
            return existing
        raise
    except Exception:
        session.rollback()
        raise


def append_compensation_transaction(
    session: Session,
    *,
    household: Household,
    member: Member,
    target: HealthEvent,
    actor_id: str,
    idempotency_key: str | None,
    correlation_id: str,
    payload: HealthEventCompensationCreate,
) -> HealthEvent:
    normalized_key = normalize_idempotency_key(idempotency_key)
    fingerprint = event_request_fingerprint(
        operation=f"COMPENSATE_EVENT:{target.id}",
        actor_id=actor_id,
        payload=payload.model_dump(mode="json"),
    )
    existing = _existing_idempotent_event(
        session,
        household_id=household.id,
        idempotency_key=normalized_key,
        fingerprint=fingerprint,
    )
    if existing is not None:
        return existing
    if target.confirmation_status != "CONFIRMED":
        raise ValueError("UNCONFIRMED_EVENT_CANNOT_BE_COMPENSATED")
    replacement = session.scalar(
        select(HealthEvent.id).where(HealthEvent.supersedes_event_id == target.id)
    )
    if replacement is not None:
        raise EventAlreadySupersededError("EVENT_ALREADY_SUPERSEDED")
    try:
        event = _append_event(
            session,
            household=household,
            member=member,
            actor_id=actor_id,
            idempotency_key=normalized_key,
            fingerprint=fingerprint,
            correlation_id=correlation_id,
            event_type=payload.event_type,
            source="MANUAL",
            confirmation_status="CONFIRMED",
            payload=payload.payload,
            evidence={**payload.evidence, "correction_reason": payload.reason},
            occurred_at=payload.occurred_at,
            causation_id=target.id,
            supersedes_event_id=target.id,
        )
        session.commit()
        session.refresh(event)
        return event
    except Exception:
        session.rollback()
        raise


def create_projection_checkpoint(
    session: Session,
    *,
    projection: MemberStateProjection,
    actor_id: str,
) -> ProjectionCheckpoint:
    state_hash = projection.state_hash or canonical_hash(projection.state)
    existing = session.scalar(
        select(ProjectionCheckpoint).where(
            ProjectionCheckpoint.member_id == projection.member_id,
            ProjectionCheckpoint.last_sequence == projection.last_sequence,
        )
    )
    if existing is not None:
        if existing.state_hash != state_hash:
            raise CheckpointInvalidError("CHECKPOINT_STATE_CONFLICT")
        return existing
    checkpoint = ProjectionCheckpoint(
        member_id=projection.member_id,
        household_id=projection.household_id,
        last_sequence=projection.last_sequence,
        last_event_id=projection.last_event_id,
        state=copy.deepcopy(projection.state),
        state_hash=state_hash,
        created_by=actor_id,
    )
    session.add(checkpoint)
    session.commit()
    session.refresh(checkpoint)
    return checkpoint


def replay_member_projection(
    session: Session,
    *,
    household_id: str,
    member_id: str,
    checkpoint_id: str | None,
) -> ReplayResult:
    checkpoint: ProjectionCheckpoint | None = None
    state: dict[str, Any] = {}
    last_sequence = 0
    last_event_id: str | None = None
    if checkpoint_id is not None:
        checkpoint = session.get(ProjectionCheckpoint, checkpoint_id)
        if (
            checkpoint is None
            or checkpoint.household_id != household_id
            or checkpoint.member_id != member_id
            or canonical_hash(checkpoint.state) != checkpoint.state_hash
        ):
            raise CheckpointInvalidError("CHECKPOINT_INVALID")
        state = copy.deepcopy(checkpoint.state)
        last_sequence = checkpoint.last_sequence
        last_event_id = checkpoint.last_event_id

    events = list(
        session.scalars(
            select(HealthEvent)
            .where(
                HealthEvent.household_id == household_id,
                HealthEvent.member_id == member_id,
                HealthEvent.confirmation_status == "CONFIRMED",
                HealthEvent.sequence_no > last_sequence,
            )
            .order_by(HealthEvent.sequence_no)
        ).all()
    )
    for event in events:
        state = reduce_projection_state(state, event)
        last_sequence = event.sequence_no
        last_event_id = event.id
    rebuilt_hash = canonical_hash(state)
    projection = session.get(MemberStateProjection, member_id)
    previous_hash = (
        None
        if projection is None
        else projection.state_hash or canonical_hash(projection.state)
    )
    consistent = previous_hash == rebuilt_hash
    if projection is None:
        projection = MemberStateProjection(
            member_id=member_id,
            household_id=household_id,
            state={},
            version=0,
            last_sequence=0,
        )
        session.add(projection)
    projection.state = state
    projection.last_event_id = last_event_id
    projection.last_sequence = last_sequence
    projection.version = int(projection.version or 0) + 1
    projection.state_hash = rebuilt_hash
    projection.updated_at = datetime.now(UTC)
    session.commit()
    return ReplayResult(
        member_id=member_id,
        checkpoint_id=checkpoint.id if checkpoint is not None else None,
        events_replayed=len(events),
        previous_state_hash=previous_hash,
        rebuilt_state_hash=rebuilt_hash,
        consistent_with_online=consistent,
        last_sequence=last_sequence,
        projection_version=projection.version,
    )


def dispatch_outbox_message(
    session: Session,
    message_id: str,
    *,
    deliver: Delivery | None = None,
    now: datetime | None = None,
) -> str:
    current_time = now or datetime.now(UTC)
    message = session.get(OutboxMessage, message_id)
    if message is None:
        return "NOT_FOUND"
    if message.status == "DISPATCHED":
        return "ALREADY_DISPATCHED"

    message.status = "PROCESSING"
    message.attempts = int(message.attempts or 0) + 1
    message.locked_at = current_time
    message.last_error = None
    message.updated_at = current_time
    session.commit()
    try:
        message = session.get(OutboxMessage, message_id)
        if message is None:
            return "NOT_FOUND"
        event = session.get(HealthEvent, message.event_id)
        if event is None:
            raise RuntimeError("OUTBOX_EVENT_NOT_FOUND")
        (deliver or apply_event_to_projection)(session, event)
        message.status = "DISPATCHED"
        message.dispatched = True
        message.dispatched_at = current_time
        message.locked_at = None
        message.last_error = None
        message.updated_at = current_time
        session.commit()
        return "DISPATCHED"
    except EventOrderGapError:
        session.rollback()
        message = session.get(OutboxMessage, message_id)
        if message is not None:
            message.status = "FAILED"
            message.locked_at = None
            message.last_error = "OUT_OF_ORDER"
            message.available_at = current_time
            message.updated_at = current_time
            session.commit()
        return "OUT_OF_ORDER"
    except Exception:
        session.rollback()
        message = session.get(OutboxMessage, message_id)
        if message is not None:
            message.status = "FAILED"
            message.locked_at = None
            message.last_error = "DOWNSTREAM_UNAVAILABLE"
            message.available_at = current_time
            message.updated_at = current_time
            session.commit()
        return "FAILED"


def dispatch_outbox_batch(
    session: Session,
    *,
    household_id: str,
    max_messages: int,
    stale_after: timedelta = timedelta(minutes=5),
    deliver: Delivery | None = None,
    now: datetime | None = None,
) -> DispatchSummary:
    current_time = now or datetime.now(UTC)
    stale_before = current_time - stale_after
    stale_messages = list(
        session.scalars(
            select(OutboxMessage)
            .join(HealthEvent, HealthEvent.id == OutboxMessage.event_id)
            .where(
                HealthEvent.household_id == household_id,
                OutboxMessage.status == "PROCESSING",
            )
        ).all()
    )
    recovered_stale = 0
    for message in stale_messages:
        if message.locked_at is not None and _as_utc(message.locked_at) <= stale_before:
            message.status = "PENDING"
            message.locked_at = None
            message.last_error = "PROCESS_INTERRUPTED"
            message.updated_at = current_time
            recovered_stale += 1
    if recovered_stale:
        session.commit()

    messages = list(
        session.scalars(
            select(OutboxMessage)
            .join(HealthEvent, HealthEvent.id == OutboxMessage.event_id)
            .where(
                HealthEvent.household_id == household_id,
                OutboxMessage.status.in_(["PENDING", "FAILED"]),
                or_(
                    OutboxMessage.available_at.is_(None),
                    OutboxMessage.available_at <= current_time,
                ),
            )
            .order_by(HealthEvent.member_id, HealthEvent.sequence_no, OutboxMessage.id)
            .limit(max_messages)
        ).all()
    )
    dispatched = failed = out_of_order = 0
    for message in messages:
        outcome = dispatch_outbox_message(
            session,
            message.id,
            deliver=deliver,
            now=current_time,
        )
        if outcome == "DISPATCHED":
            dispatched += 1
        elif outcome == "OUT_OF_ORDER":
            out_of_order += 1
        elif outcome == "FAILED":
            failed += 1
    return DispatchSummary(
        inspected=len(messages),
        dispatched=dispatched,
        failed=failed,
        out_of_order=out_of_order,
        recovered_stale=recovered_stale,
    )
