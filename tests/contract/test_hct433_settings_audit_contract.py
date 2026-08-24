"""HCT-433: household setting changes leave a minimal request-linked audit."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AccessAudit

OWNER_HEADERS = {"X-Actor-Id": "owner"}


def _create_household(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/households",
        headers=OWNER_HEADERS,
        json={"name": "HCT-433 household", "time_zone": "Asia/Shanghai"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _setting_audits(db_session: Session, household_id: str) -> list[AccessAudit]:
    return list(
        db_session.scalars(
            select(AccessAudit)
            .where(
                AccessAudit.household_id == household_id,
                AccessAudit.action == "UPDATE_TIME_ZONE",
            )
            .order_by(AccessAudit.created_at, AccessAudit.id)
        )
    )


def test_changed_time_zone_has_minimal_request_linked_audit(
    client: TestClient, db_session: Session
) -> None:
    household = _create_household(client)
    request_id = "hct433-setting-change"

    updated = client.patch(
        f"/api/v1/households/{household['id']}",
        headers={**OWNER_HEADERS, "X-Request-ID": request_id},
        json={"time_zone": "Europe/London"},
    )

    assert updated.status_code == 200, updated.text
    audits = _setting_audits(db_session, household["id"])
    assert len(audits) == 1
    assert audits[0].operation == "UPDATE"
    assert audits[0].data_field == "household.time_zone"
    assert audits[0].outcome == "ALLOWED"
    assert audits[0].request_id == request_id
    assert audits[0].purpose == "household-settings"


def test_same_time_zone_does_not_create_duplicate_audit(
    client: TestClient, db_session: Session
) -> None:
    household = _create_household(client)
    first = client.patch(
        f"/api/v1/households/{household['id']}",
        headers={**OWNER_HEADERS, "X-Request-ID": "hct433-first"},
        json={"time_zone": "Europe/London"},
    )
    second = client.patch(
        f"/api/v1/households/{household['id']}",
        headers={**OWNER_HEADERS, "X-Request-ID": "hct433-same"},
        json={"time_zone": "Europe/London"},
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    audits = _setting_audits(db_session, household["id"])
    assert len(audits) == 1
    assert audits[0].request_id == "hct433-first"


def test_non_owner_cannot_create_setting_audit(
    client: TestClient, db_session: Session
) -> None:
    household = _create_household(client)

    denied = client.patch(
        f"/api/v1/households/{household['id']}",
        headers={"X-Actor-Id": "caregiver", "X-Request-ID": "hct433-denied"},
        json={"time_zone": "Europe/London"},
    )

    assert denied.status_code == 404
    assert _setting_audits(db_session, household["id"]) == []
