"""HCT-429: household time zone API contract and owner boundary."""

from fastapi.testclient import TestClient

from app.config import get_settings

OWNER_HEADERS = {"X-Actor-Id": "owner"}


def _create_household(client: TestClient, **payload: object) -> dict:
    response = client.post(
        "/api/v1/households",
        headers=OWNER_HEADERS,
        json={"name": "HCT-429 household", **payload},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_create_and_read_household_exposes_explicit_time_zone(client: TestClient) -> None:
    household = _create_household(client, time_zone="Asia/Shanghai")

    listed = client.get("/api/v1/households", headers=OWNER_HEADERS)

    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["id"] == household["id"]
    assert listed.json()[0]["time_zone"] == "Asia/Shanghai"


def test_create_household_uses_deployment_default_when_omitted(client: TestClient) -> None:
    settings = get_settings()
    previous = settings.default_household_time_zone
    settings.default_household_time_zone = "America/New_York"
    try:
        household = _create_household(client)
    finally:
        settings.default_household_time_zone = previous

    assert household["time_zone"] == "America/New_York"


def test_invalid_time_zone_is_rejected_on_create_and_update(client: TestClient) -> None:
    invalid_create = client.post(
        "/api/v1/households",
        headers=OWNER_HEADERS,
        json={"name": "Invalid zone", "time_zone": "Mars/Olympus"},
    )
    assert invalid_create.status_code == 422

    household = _create_household(client, time_zone="Asia/Shanghai")
    invalid_update = client.patch(
        f"/api/v1/households/{household['id']}",
        headers=OWNER_HEADERS,
        json={"time_zone": "Not/AZone"},
    )
    assert invalid_update.status_code == 422

    unchanged = client.get("/api/v1/households", headers=OWNER_HEADERS)
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()[0]["time_zone"] == "Asia/Shanghai"


def test_only_owner_can_update_household_time_zone(client: TestClient) -> None:
    household = _create_household(client, time_zone="Asia/Shanghai")
    updated = client.patch(
        f"/api/v1/households/{household['id']}",
        headers=OWNER_HEADERS,
        json={"time_zone": "Europe/London"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["time_zone"] == "Europe/London"

    denied = client.patch(
        f"/api/v1/households/{household['id']}",
        headers={"X-Actor-Id": "caregiver"},
        json={"time_zone": "UTC"},
    )
    assert denied.status_code == 404
