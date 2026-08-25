"""
HCT-107: Local auth tests — password, rate limiting, sessions, PIN challenges.
HCT-427: step-up challenges carry no secret and session revalidation is explicit.
"""

import time

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth as auth_module
from app.auth import (
    authenticate,
    generate_pin_challenge,
    hash_password,
    introspect_session,
    logout,
    register_account,
    set_account_pin,
    validate_session,
    verify_password,
    verify_pin_challenge,
)
from app.models import Base


@pytest.fixture(autouse=True)
def isolated_auth_database(monkeypatch: pytest.MonkeyPatch):
    """Keep pure auth tests independent from the developer's local database."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(auth_module, "SessionLocal", session_factory)
    auth_module._pin_challenges.clear()
    auth_module._face_challenges.clear()
    auth_module._face_failed_attempts.clear()
    try:
        yield
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


class TestPasswordHashing:
    def test_hash_and_verify(self):
        password = "correct-horse-battery-staple"
        hashed = hash_password(password)
        assert hashed != password
        assert verify_password(password, hashed) is True
        assert verify_password("wrong", hashed) is False

    def test_different_salts(self):
        pw = "test123"
        h1 = hash_password(pw)
        h2 = hash_password(pw)
        assert h1 != h2  # different salts
        assert verify_password(pw, h1)
        assert verify_password(pw, h2)


class TestAuthFlow:
    def test_register_and_login(self):
        actor = "actor-auth-test"
        try:
            register_account(actor, "secret-pass")
        except HTTPException:
            pass  # already exists from previous run

        result = authenticate(actor, "secret-pass")
        assert "session_token" in result
        assert result["expires_at"] > time.time()

    def test_wrong_password_rejected(self):
        register_account("actor-wrong", "real-pass")
        with pytest.raises(HTTPException) as exc:
            authenticate("actor-wrong", "wrong-pass")
        assert exc.value.status_code == 401

    def test_nonexistent_account_rejected(self):
        with pytest.raises(HTTPException) as exc:
            authenticate("actor-nobody", "any-pass")
        assert exc.value.status_code == 401


class TestRateLimiting:
    def test_lockout_after_max_attempts(self):
        actor = "actor-brute"
        register_account(actor, "safe-pass")
        for _ in range(5):
            try:
                authenticate(actor, "bad-pass")
            except HTTPException:
                pass
        with pytest.raises(HTTPException) as exc:
            authenticate(actor, "bad-pass")
        assert exc.value.status_code == 429


class TestSession:
    def test_valid_session(self):
        register_account("actor-session", "pass")
        result = authenticate("actor-session", "pass")
        actor = validate_session(result["session_token"])
        assert actor == "actor-session"

    def test_invalid_token_rejected(self):
        with pytest.raises(HTTPException) as exc:
            validate_session("invalid-token")
        assert exc.value.status_code == 401

    def test_logout(self):
        register_account("actor-logout", "pass")
        result = authenticate("actor-logout", "pass")
        logout(result["session_token"])
        with pytest.raises(HTTPException):
            validate_session(result["session_token"])


class TestSessionIntrospection:
    def test_reports_live_session(self):
        register_account("actor-introspect", "pass")
        result = authenticate("actor-introspect", "pass")
        reported = introspect_session(result["session_token"])
        assert reported["actor_id"] == "actor-introspect"
        assert reported["expires_at"] == result["expires_at"]

    def test_rejects_logged_out_session(self):
        register_account("actor-introspect2", "pass")
        result = authenticate("actor-introspect2", "pass")
        logout(result["session_token"])
        with pytest.raises(HTTPException) as exc:
            introspect_session(result["session_token"])
        assert exc.value.status_code == 401


def _actor_with_pin(name: str, household: str, pin: str = "135790") -> str:
    """Register an actor, open a session and configure its household PIN."""
    register_account(name, "pass")
    session_token = authenticate(name, "pass")["session_token"]
    set_account_pin(name, household, pin)
    return session_token


class TestStepUpChallenge:
    def test_challenge_never_returns_a_secret(self):
        token = _actor_with_pin("actor-step1", "hh-step1")
        challenge = generate_pin_challenge("actor-step1", "delete_record", token)
        assert set(challenge) == {"challenge_id", "action", "household_id", "expires_at"}
        assert "pin" not in challenge
        assert "135790" not in str(challenge)
        assert challenge["household_id"] == "hh-step1"
        assert challenge["expires_at"] > time.time()

    def test_generate_and_verify(self):
        token = _actor_with_pin("actor-step2", "hh-step2")
        challenge = generate_pin_challenge("actor-step2", "delete_record", token)
        grant = verify_pin_challenge(
            challenge["challenge_id"], "delete_record", token, "135790"
        )
        assert grant["challenge_id"] == challenge["challenge_id"]
        assert grant["action"] == "delete_record"
        assert grant["confirmed_at"] <= time.time()

    def test_replay_rejected(self):
        token = _actor_with_pin("actor-step3", "hh-step3")
        challenge = generate_pin_challenge("actor-step3", "delete_record", token)
        verify_pin_challenge(challenge["challenge_id"], "delete_record", token, "135790")
        with pytest.raises(HTTPException) as exc:
            verify_pin_challenge(challenge["challenge_id"], "delete_record", token, "135790")
        assert exc.value.status_code == 409
        assert exc.value.detail == "STEP_UP_REPLAY"

    def test_foreign_session_rejected(self):
        token = _actor_with_pin("actor-step4", "hh-step4")
        challenge = generate_pin_challenge("actor-step4", "delete_record", token)
        other = _actor_with_pin("actor-step4b", "hh-step4b")
        with pytest.raises(HTTPException) as exc:
            verify_pin_challenge(challenge["challenge_id"], "delete_record", other, "135790")
        assert exc.value.status_code == 403
        assert exc.value.detail == "STEP_UP_FAILED"

    def test_wrong_action_rejected(self):
        token = _actor_with_pin("actor-step5", "hh-step5")
        challenge = generate_pin_challenge("actor-step5", "delete_record", token)
        with pytest.raises(HTTPException) as exc:
            verify_pin_challenge(challenge["challenge_id"], "grant_access", token, "135790")
        assert exc.value.status_code == 403

    def test_unknown_challenge_rejected(self):
        token = _actor_with_pin("actor-step6", "hh-step6")
        with pytest.raises(HTTPException) as exc:
            verify_pin_challenge("no-such-challenge", "delete_record", token, "135790")
        assert exc.value.status_code == 403
        assert exc.value.detail == "STEP_UP_FAILED"

    def test_wrong_code_does_not_consume_the_challenge(self):
        token = _actor_with_pin("actor-step7", "hh-step7")
        challenge = generate_pin_challenge("actor-step7", "delete_record", token)
        with pytest.raises(HTTPException) as exc:
            verify_pin_challenge(challenge["challenge_id"], "delete_record", token, "000000")
        assert exc.value.status_code == 403
        # A mistyped PIN must stay recoverable inside the same challenge window.
        grant = verify_pin_challenge(
            challenge["challenge_id"], "delete_record", token, "135790"
        )
        assert grant["action"] == "delete_record"

    def test_expired_challenge_rejected(self):
        token = _actor_with_pin("actor-step8", "hh-step8")
        challenge = generate_pin_challenge("actor-step8", "delete_record", token)
        # Age the challenge past its TTL without waiting five minutes.
        auth_module._pin_challenges[challenge["challenge_id"]]["expires_at"] = time.time() - 1
        with pytest.raises(HTTPException) as exc:
            verify_pin_challenge(challenge["challenge_id"], "delete_record", token, "135790")
        assert exc.value.status_code == 409
        assert exc.value.detail == "STEP_UP_EXPIRED"

    def test_brute_force_locks_the_step_up_window(self):
        token = _actor_with_pin("actor-step9", "hh-step9")
        challenge = generate_pin_challenge("actor-step9", "delete_record", token)
        for _ in range(5):
            with pytest.raises(HTTPException):
                verify_pin_challenge(challenge["challenge_id"], "delete_record", token, "000000")
        with pytest.raises(HTTPException) as exc:
            verify_pin_challenge(challenge["challenge_id"], "delete_record", token, "135790")
        assert exc.value.status_code == 429

    def test_requires_a_configured_pin(self):
        register_account("actor-step10", "pass")
        token = authenticate("actor-step10", "pass")["session_token"]
        with pytest.raises(HTTPException) as exc:
            generate_pin_challenge("actor-step10", "delete_record", token)
        assert exc.value.status_code == 409
        assert exc.value.detail == "PIN_NOT_CONFIGURED"

    def test_household_must_be_explicit_when_ambiguous(self):
        token = _actor_with_pin("actor-step11", "hh-step11a")
        set_account_pin("actor-step11", "hh-step11b", "246802")
        with pytest.raises(HTTPException) as exc:
            generate_pin_challenge("actor-step11", "delete_record", token)
        assert exc.value.status_code == 409
        assert exc.value.detail == "HOUSEHOLD_REQUIRED"
        # Naming the household resolves it, and that household's own PIN applies.
        challenge = generate_pin_challenge(
            "actor-step11", "delete_record", token, "hh-step11b"
        )
        assert challenge["household_id"] == "hh-step11b"
        grant = verify_pin_challenge(
            challenge["challenge_id"], "delete_record", token, "246802"
        )
        assert grant["action"] == "delete_record"

    def test_challenge_requires_the_session_owner(self):
        token = _actor_with_pin("actor-step12", "hh-step12")
        set_account_pin("actor-step12-other", "hh-step12", "111111")
        with pytest.raises(HTTPException) as exc:
            generate_pin_challenge("actor-step12-other", "delete_record", token)
        assert exc.value.status_code == 403

    def test_expired_session_cannot_open_a_challenge(self):
        token = _actor_with_pin("actor-step13", "hh-step13")
        logout(token)
        with pytest.raises(HTTPException) as exc:
            generate_pin_challenge("actor-step13", "delete_record", token)
        assert exc.value.status_code == 401
        with pytest.raises(HTTPException):
            validate_session(token)
