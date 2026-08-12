"""
HCT-107: Local auth tests — password, rate limiting, sessions, PIN challenges.
"""

import time

import pytest
from fastapi import HTTPException

from app.auth import (
    authenticate,
    generate_pin_challenge,
    hash_password,
    logout,
    register_account,
    validate_session,
    verify_password,
    verify_pin,
)


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


class TestPinChallenge:
    def test_generate_and_verify(self):
        register_account("actor-pin", "pass")
        result = authenticate("actor-pin", "pass")
        challenge = generate_pin_challenge("actor-pin", "delete_record", result["session_token"])
        assert "pin" in challenge
        assert len(challenge["pin"]) == 6

        ok = verify_pin(challenge["pin"], "delete_record", result["session_token"])
        assert ok is True

    def test_pin_replay_rejected(self):
        register_account("actor-pin2", "pass")
        result = authenticate("actor-pin2", "pass")
        challenge = generate_pin_challenge("actor-pin2", "delete_record", result["session_token"])
        assert verify_pin(challenge["pin"], "delete_record", result["session_token"])
        assert not verify_pin(challenge["pin"], "delete_record", result["session_token"])

    def test_pin_wrong_session_rejected(self):
        register_account("actor-pin3", "pass")
        result = authenticate("actor-pin3", "pass")
        challenge = generate_pin_challenge("actor-pin3", "delete_record", result["session_token"])
        assert not verify_pin(challenge["pin"], "delete_record", "other-token")

    def test_pin_wrong_action_rejected(self):
        register_account("actor-pin4", "pass")
        result = authenticate("actor-pin4", "pass")
        challenge = generate_pin_challenge("actor-pin4", "delete_record", result["session_token"])
        assert not verify_pin(challenge["pin"], "wrong_action", result["session_token"])
