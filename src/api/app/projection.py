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


def _drug_from_payload(payload: dict[str, Any], event_id: str, *, name: Any) -> dict[str, Any]:
    """Keep expiry/stock/ingredient so HCT-302 rules can fire from confirmed events."""
    return {
        "name": name,
        "added_by": event_id,
        "expiry_date": payload.get("expiry_date"),
        "stock": payload.get("stock"),
        "ingredient": payload.get("ingredient"),
        "candidate_id": payload.get("candidate_id"),
        "active_ingredients": payload.get("active_ingredients", []),
        "interaction_warnings": payload.get("interaction_warnings", []),
        "master_data_version": payload.get("master_data_version"),
        "specification": payload.get("specification") or payload.get("dosage"),
        "manufacturer": payload.get("manufacturer"),
        "indications": payload.get("indications", []),
        "cautions": payload.get("cautions", []),
        "contraindications": payload.get("contraindications", []),
    }


# Known event types that contribute to the relationship graph.
RELATION_EVENT_TYPES = frozenset({
    "medication_added",
    "medication_confirmed",
    "medication_stopped",
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
            drugs.append(_drug_from_payload(payload, event.id, name=payload.get("drug")))
        elif etype == "medication_confirmed":
            # Vision review confirmations archive with drug_name (HCT-207).
            name = payload.get("drug_name") or payload.get("drug")
            if name:
                drugs.append(_drug_from_payload(payload, event.id, name=name))
        elif etype == "medication_stopped":
            stopped = payload.get("drug_name") or payload.get("drug")
            drugs = [item for item in drugs if item.get("name") != stopped]
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


def build_relationship_graph_view(events: list[HealthEvent]) -> dict[str, Any]:
    """Return the minimum traceable graph representation for desktop rendering.

    The event payload is deliberately consumed only here and never returned to
    the browser. Callers receive active facts plus their source metadata.
    """
    facts = build_relationship_graph(events)
    events_by_id = {event.id: event for event in events}
    nodes: list[dict[str, Any]] = []

    def append_node(category: str, label: Any, source_event_id: str) -> None:
        if not isinstance(label, str) or not label:
            return
        source = events_by_id.get(source_event_id)
        if source is None:
            return
        nodes.append({
            "id": f"{category}:{source_event_id}",
            "category": category,
            "label": label,
            "source_event_id": source_event_id,
            "source_recorded_at": source.created_at,
            "source_created_by": source.created_by,
        })

    for drug in facts["drugs"]:
        append_node("drug", drug.get("name"), drug["added_by"])
    for allergy in facts["allergies"]:
        append_node("allergy", allergy.get("name"), allergy["added_by"])
    for disease in facts["diseases"]:
        append_node("disease", disease.get("name"), disease["added_by"])
    for plan in facts["plans"]:
        drug = plan.get("drug")
        if isinstance(drug, str) and drug:
            append_node("plan", f"{drug} · 计划", plan["added_by"])

    compensated = {
        event.compensates_event_id
        for event in events
        if event.event_type == "COMPENSATION" and event.compensates_event_id
    }
    for event in events:
        if event.id not in compensated and event.event_type == "caregiver_assigned":
            append_node("caregiver", "已授权照护关系", event.id)

    return {
        "nodes": nodes,
        "last_event_id": facts["last_event_id"],
        "events_count": facts["events_count"],
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
