import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Pytest's optional ``pythonpath`` configuration is not present in every
# locked runner.  Keep test imports deterministic without changing runtime
# package configuration or production import paths.
REPO_ROOT = Path(__file__).resolve().parents[1]
for source_path in (REPO_ROOT / "src/api", REPO_ROOT / "src", REPO_ROOT / "scripts"):
    source = str(source_path)
    if source not in sys.path:
        sys.path.insert(0, source)

from app.config import get_settings  # noqa: E402
from app.db import get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402


@pytest.fixture(autouse=True)
def _close_open_chat_in_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep FR-08 evidence walls on in tests even though demos default open.

    Individual tests may re-enable ``agent_open_chat`` with monkeypatch.
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "agent_open_chat", False)


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_get_session() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    settings = get_settings()
    previous_enforcement = settings.vision_quality_enforce_retake
    # API contract/e2e tests cover the strict safety path even when a local
    # developer .env enables advisory-only demo mode.
    settings.vision_quality_enforce_retake = True
    with TestClient(app) as test_client:
        try:
            yield test_client
        finally:
            settings.vision_quality_enforce_retake = previous_enforcement
            app.dependency_overrides.clear()
