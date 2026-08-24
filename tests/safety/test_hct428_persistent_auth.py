"""HCT-428: auth state survives a worker/session boundary and stores no bearer secret."""

import hashlib

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.auth import (
    authenticate,
    generate_pin_challenge,
    logout,
    register_account,
    set_account_pin,
    validate_session,
    verify_pin_challenge,
)
from app.models import AuthSession


def _new_session(db_session: Session) -> Session:
    return sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)()


def test_session_and_credentials_are_visible_to_another_worker_session(db_session: Session) -> None:
    register_account("hct428-owner", "hct428-password", db_session)
    login = authenticate("hct428-owner", "hct428-password", db_session)
    token = login["session_token"]

    stored = db_session.scalar(select(AuthSession).where(AuthSession.actor_id == "hct428-owner"))
    assert stored is not None
    assert stored.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in stored.token_hash

    worker_session = _new_session(db_session)
    try:
        assert validate_session(token, worker_session) == "hct428-owner"
        logout(token, worker_session)
    finally:
        worker_session.close()

    with pytest.raises(HTTPException) as exc:
        validate_session(token, db_session)
    assert exc.value.status_code == 401


def test_pin_challenge_and_rate_limit_are_database_backed(db_session: Session) -> None:
    register_account("hct428-pin", "hct428-password", db_session)
    set_account_pin("hct428-pin", "household-428", "135790", db_session)
    token = authenticate("hct428-pin", "hct428-password", db_session)["session_token"]
    challenge = generate_pin_challenge(
        "hct428-pin", "confirm_high_risk", token, "household-428", db_session
    )

    worker_session = _new_session(db_session)
    try:
        grant = verify_pin_challenge(
            challenge["challenge_id"],
            "confirm_high_risk",
            token,
            "135790",
            worker_session,
        )
    finally:
        worker_session.close()
    assert grant["status"] == "confirmed"

    for _ in range(5):
        worker_session = _new_session(db_session)
        try:
            with pytest.raises(HTTPException):
                authenticate("hct428-pin", "bad-password", worker_session)
        finally:
            worker_session.close()
    with pytest.raises(HTTPException) as exc:
        authenticate("hct428-pin", "bad-password", db_session)
    assert exc.value.status_code == 429


def test_new_login_rotates_the_previous_session(db_session: Session) -> None:
    register_account("hct428-rotate", "hct428-password", db_session)
    first = authenticate("hct428-rotate", "hct428-password", db_session)["session_token"]
    second = authenticate("hct428-rotate", "hct428-password", db_session)["session_token"]
    assert first != second
    with pytest.raises(HTTPException) as exc:
        validate_session(first, db_session)
    assert exc.value.status_code == 401
    assert validate_session(second, db_session) == "hct428-rotate"
