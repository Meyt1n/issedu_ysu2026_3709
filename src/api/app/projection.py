"""
HCT-301: Event timeline and relationship graph projection.

Rebuilds member-disease-allergy-drug-plan-caregiver relationships
from the immutable health event chain. Supports full replay and
checkpoint-based incremental rebuild.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import HealthEvent, MemberStateProjection

logger = logging.getLogger(__name__)

# Known event types that contribute to the relationship graph.
RELATION_EVENT_TYPES = frozenset({
    "medication_added",
    "medication_corrected",
    "allergy_added",
    "allergy_removed",
    "disease_added",
    "disease_resolved",
    "plan_created",
    "plan_updated",
    "caregiver_assigned",
    "COMPENSATION",
})


def build_relationship_graph(
    events: list[HealthEvent],
) -> dict[str, Any]:
    """Rebuild the relationship graph from an ordered event list.

    Returns a dict with keys: member_id, drugs, allergies, diseases,
    plans, caregivers, last_event_id, events_count.
    """
    drugs: list[dict[str, Any]] = []
    allergies: list[dict[str, Any]] = []
    diseases: list[dict[str, Any]] = []
    plans: list[dict[str, Any]] = []
    caregivers: list[str] = []
    compensated: set[str] = set()
    last_event_id: str | None = None

    for event in events:
        if event.event_type == "COMPENSATION" and event.compensates_event_id:
            compensated.add(event.compensates_event_id)
        last_event_id = event.id

    for event in events:
        if event.id in compensated:
            continue
        etype = event.event_type
        payload = event.payload or {}

        if etype == "medication_added":
            drugs.append({"name": payload.get("drug"), "added_by": event.id})
        elif etype == "allergy_added":
            allergies.append({"name": payload.get("allergy"), "added_by": event.id})
        elif etype == "allergy_removed":
            allergies = [a for a in allergies if a.get("name") != payload.get("allergy")]
        elif etype == "disease_added":
            diseases.append({"name": payload.get("disease"), "added_by": event.id})
        elif etype == "disease_resolved":
            diseases = [d for d in diseases if d.get("name") != payload.get("disease")]
        elif etype in ("plan_created", "plan_updated"):
            plans.append({
                "drug": payload.get("drug"),
                "schedule": payload.get("schedule"),
                "added_by": event.id,
            })
        elif etype == "caregiver_assigned":
            caregivers.append(payload.get("caregiver_id", ""))

    return {
        "drugs": drugs,
        "allergies": allergies,
        "diseases": diseases,
        "plans": plans,
        "caregivers": list(dict.fromkeys(caregivers)),
        "last_event_id": last_event_id,
        "events_count": len(events),
    }


def get_timeline(
    session: Session,
    member_id: str,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[HealthEvent]:
    """Return the ordered event timeline for a member."""
    query = select(HealthEvent).where(
        HealthEvent.member_id == member_id,
        HealthEvent.confirmation_status == "CONFIRMED",
    )
    if since is not None:
        query = query.where(HealthEvent.created_at >= since)
    if until is not None:
        query = query.where(HealthEvent.created_at <= until)
    return list(session.scalars(query.order_by(HealthEvent.sequence_no)).all())


def rebuild_projection(
    session: Session,
    member_id: str,
    household_id: str,
    *,
    checkpoint_event_id: str | None = None,
) -> MemberStateProjection:
    """Full or incremental rebuild of the member state projection.

    If *checkpoint_event_id* is provided, only events after it are replayed.
    """
    events = get_timeline(session, member_id)
    if checkpoint_event_id:
        events = [e for e in events if e.id > checkpoint_event_id]

    graph = build_relationship_graph(events)
    projection = session.get(MemberStateProjection, member_id)
    if projection is None:
        projection = MemberStateProjection(
            member_id=member_id,
            household_id=household_id,
            state={},
        )
        session.add(projection)

    projection.state = graph
    projection.last_event_id = graph["last_event_id"]
    projection.updated_at = datetime.now(UTC)
    session.commit()
    logger.info(
        "PROJECTION_REBUILT member=%s events=%d last=%s",
        member_id, graph["events_count"], graph["last_event_id"],
    )
    return projection
