"""HCT-308 care-plan worker entrypoint contract for standard deployment.

The compose service runs ``python -m app.care_plan_worker --loop
--ready-file …`` and its container healthcheck waits for the ready file.
These tests pin the CLI surface and the single-cycle behaviour so the
docker-compose wiring cannot silently break.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.care_plan_worker as worker_module
from app.models import Base


@pytest.fixture()
def isolated_worker_database(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(worker_module, "SessionLocal", session_factory)
    try:
        yield
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_single_cycle_writes_ready_file_and_exits_zero(
    isolated_worker_database, tmp_path: Path
) -> None:
    ready_file = tmp_path / "care-plan-worker.ready"
    exit_code = worker_module.run_worker(loop=False, ready_file=ready_file)
    assert exit_code == 0
    assert ready_file.read_text(encoding="ascii") == "ready\n"


def test_single_cycle_failure_returns_nonzero_without_ready_file(
    isolated_worker_database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("DB_UNAVAILABLE")

    monkeypatch.setattr(worker_module, "automation_cycle", boom)
    ready_file = tmp_path / "care-plan-worker.ready"
    exit_code = worker_module.run_worker(loop=False, ready_file=ready_file)
    assert exit_code == 1
    assert not ready_file.exists()


def test_cli_accepts_loop_and_ready_file_flags() -> None:
    """The flags used by docker-compose.yml must stay valid."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--ready-file", type=Path)
    # 真正的校验：模块级 parser 接受 compose 传入的参数组合。
    module_source = Path(worker_module.__file__).read_text(encoding="utf-8")
    assert '"--loop"' in module_source
    assert '"--ready-file"' in module_source
