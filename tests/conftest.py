import sys
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

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

from app import config as app_config  # noqa: E402

# Ignore the developer's local ``.env`` for the whole suite.
#
# ``Settings`` loads ``.env`` by default, so tests asserting *default deployment*
# behaviour silently took on whatever the current machine had configured: with
# ``MASTER_DATA_APPROVED_VERSIONS=demo-cn-en-v1`` set locally, the capabilities
# contract test failed on that machine and passed in CI (which has no ``.env``).
# Same commit, different verdict per machine — so the suite pins the documented
# defaults instead.  This must happen before ``app.db``/``app.main`` are imported,
# because those bind ``settings = get_settings()`` at import time.  Individual
# tests still opt into non-default values with ``monkeypatch``.
app_config.Settings.model_config["env_file"] = None

from app.config import get_settings  # noqa: E402
from app.db import get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402


@pytest.fixture(autouse=True)
def _restore_settings_singleton() -> Generator[None, None, None]:
    """Keep ``get_settings()`` returning the same object for every test.

    ``app.routes``/``app.db``/``app.main`` and ``migrations/env.py`` bind a
    module-level ``settings = get_settings()`` snapshot at import time.  A test
    that calls ``get_settings.cache_clear()`` (migration tests legitimately do,
    to pick up a new ``DATABASE_URL``) leaves the cache empty, so the next
    ``get_settings()`` builds a *different* instance while those snapshots keep
    the old one.  Configuration patched on one object is then invisible to the
    other — that split previously made ~20 contract tests fail or pass purely
    on execution order (``FILE_NOT_FOUND``: written under one ``file_root``,
    looked up under another).

    Re-priming the cache with the original instance makes the suite order
    independent without forcing every migration test to manage it by hand.
    """
    original = get_settings()
    try:
        yield
    finally:
        if get_settings() is not original:
            get_settings.cache_clear()
            with patch.object(app_config, "Settings", lambda: original):
                get_settings()


@pytest.fixture(autouse=True)
def _set_explicit_test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep safety behaviour deterministic and opt legacy test identity in explicitly.

    HCT-498 makes formal Bearer sessions the runtime default. Existing API
    contract fixtures still use synthetic X-Actor-Id values as a test harness,
    so the suite enables that legacy path here instead of relying on a runtime
    default. Individual security tests can override either setting.
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "agent_open_chat", False)
    monkeypatch.setattr(settings, "allow_dev_actor_header", True)


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
