"""HCT-417: web-facing JSON auth and in-memory bearer session boundary."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_session
from app.main import app
from app.models import Base


@pytest.fixture()
def isolated_session_client():
    """Use a fresh SQLAlchemy session for each HTTP request.

    The shared ``client`` fixture intentionally reuses one session for most
    contract tests.  This fixture catches missing route commits that only
    appear in the real web flow, where registration, login and scope loading
    are separate requests.
    """
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_session, None)
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_json_login_uses_bearer_identity_and_logout_revokes_session(client: TestClient):
    actor_id = f"web-session-{uuid4().hex[:10]}"
    password = "local-password-123"

    registered = client.post(
        "/api/v1/auth/register",
        json={"actor_id": actor_id, "password": password},
    )
    assert registered.status_code == 201

    login = client.post(
        "/api/v1/auth/login",
        json={"actor_id": actor_id, "password": password},
    )
    assert login.status_code == 200
    body = login.json()
    assert body["actor_id"] == actor_id
    token = body["session_token"]
    assert len(token) >= 32

    created = client.post(
        "/api/v1/households",
        json={"name": "Synthetic session household"},
        headers={"Authorization": f"Bearer {token}", "X-Actor-Id": "wrong-actor"},
    )
    assert created.status_code == 201
    assert created.json()["created_by"] == actor_id

    logged_out = client.post("/api/v1/auth/logout", json={"session_token": token})
    assert logged_out.status_code == 200

    denied = client.get(
        "/api/v1/households",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert denied.status_code == 401


def test_registration_login_and_session_revalidation_cross_request(
    isolated_session_client: TestClient,
):
    actor_id = f"web-registration-{uuid4().hex[:10]}"
    password = "local-password-123"

    registered = isolated_session_client.post(
        "/api/v1/auth/register",
        json={"actor_id": actor_id, "password": password},
    )
    assert registered.status_code == 201, registered.text

    login = isolated_session_client.post(
        "/api/v1/auth/login",
        json={"actor_id": actor_id, "password": password},
    )
    assert login.status_code == 200, login.text
    token = login.json()["session_token"]

    revalidated = isolated_session_client.post(
        "/api/v1/auth/session",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert revalidated.status_code == 200, revalidated.text
    assert revalidated.json()["actor_id"] == actor_id

    logged_out = isolated_session_client.post(
        "/api/v1/auth/logout",
        json={"session_token": token},
    )
    assert logged_out.status_code == 200, logged_out.text
    assert (
        isolated_session_client.post(
            "/api/v1/auth/session",
            headers={"Authorization": f"Bearer {token}"},
        ).status_code
        == 401
    )


def test_malformed_authorization_does_not_fall_back_to_dev_actor(client: TestClient):
    response = client.get(
        "/api/v1/households",
        headers={"Authorization": "Basic not-a-bearer", "X-Actor-Id": "dev-actor"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "AUTH_REQUIRED"
