"""HCT-417: web-facing JSON auth and in-memory bearer session boundary."""

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import db as db_module
from app.main import app
from app.models import Base


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


def test_malformed_authorization_does_not_fall_back_to_dev_actor(client: TestClient):
    response = client.get(
        "/api/v1/households",
        headers={"Authorization": "Basic not-a-bearer", "X-Actor-Id": "dev-actor"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "AUTH_REQUIRED"




def test_auth_session_is_committed_across_request_boundaries(tmp_path, monkeypatch):
    """A successful login must survive the dependency session closing.

    The normal test client shares one in-memory SQLAlchemy session, which can
    hide a missing commit: login and the following request see the same
    uncommitted row. Use a file-backed SQLite database and a new session per
    request to reproduce the production boundary.
    """
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'auth-boundary.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    # The production dependency itself owns the commit/rollback boundary.
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    app.dependency_overrides.clear()
    try:
        with TestClient(app) as isolated_client:
            actor_id = f"boundary-{uuid4().hex[:10]}"
            password = "local-password-123"
            registered = isolated_client.post(
                "/api/v1/auth/register",
                json={"actor_id": actor_id, "password": password},
            )
            assert registered.status_code == 201

            login = isolated_client.post(
                "/api/v1/auth/login",
                json={"actor_id": actor_id, "password": password},
            )
            assert login.status_code == 200
            token = login.json()["session_token"]

            created = isolated_client.post(
                "/api/v1/households",
                json={"name": "Synthetic auth boundary household"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert created.status_code == 201

            logged_out = isolated_client.post(
                "/api/v1/auth/logout",
                json={"session_token": token},
            )
            assert logged_out.status_code == 200
            denied = isolated_client.get(
                "/api/v1/households",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert denied.status_code == 401
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
