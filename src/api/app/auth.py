"""
HCT-107: Local password auth, rate limiting, sessions, and PIN challenges.
"""

from __future__ import annotations

import logging
import secrets
import time
from collections import defaultdict
from typing import Any

import bcrypt
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

BCRYPT_ROUNDS = 12
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_SECONDS = 300
SESSION_TTL_SECONDS = 3600
PIN_TTL_SECONDS = 300

# In-memory stores (replace with DB-backed stores in production)
_password_hashes: dict[str, str] = {}  # actor_id → bcrypt hash
_pin_hashes: dict[tuple[str, str], str] = {}  # (household_id, actor_id) → bcrypt hash
_failed_attempts: dict[str, list[float]] = defaultdict(list)
_sessions: dict[str, dict[str, Any]] = {}  # session_token → {actor_id, expires_at}
# challenge_id → {actor_id, household_id, action, session_token, expires_at, used}
#
# HCT-427: keyed by an opaque challenge id, never by the secret itself. The
# challenge only records which session and action it belongs to; the secret the
# user must re-enter is their existing household PIN (see _pin_hashes), so the
# server never has to hand a one-time code back to the caller.
_pin_challenges: dict[str, dict[str, Any]] = {}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


# Used to keep unknown household identities on the same bcrypt verification path.
_DUMMY_PIN_HASH = hash_password("000000")


def _check_rate_limit(actor_id: str) -> None:
    now = time.time()
    attempts = [t for t in _failed_attempts.get(actor_id, []) if t > now - LOCKOUT_SECONDS]
    _failed_attempts[actor_id] = attempts
    if len(attempts) >= MAX_LOGIN_ATTEMPTS:
        wait = int(LOCKOUT_SECONDS - (now - min(attempts)))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"LOCKED:{wait}",
        )


def register_account(actor_id: str, password: str) -> None:
    if actor_id in _password_hashes:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="ACCOUNT_EXISTS")
    _password_hashes[actor_id] = hash_password(password)


def authenticate(actor_id: str, password: str) -> dict[str, Any]:
    _check_rate_limit(actor_id)
    hashed = _password_hashes.get(actor_id)
    if hashed is None or not verify_password(password, hashed):
        _failed_attempts[actor_id].append(time.time())
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="AUTH_FAILED")
    _failed_attempts.pop(actor_id, None)
    return _create_session(actor_id)


def _create_session(actor_id: str) -> dict[str, Any]:
    token = secrets.token_hex(32)
    expires_at = time.time() + SESSION_TTL_SECONDS
    _sessions[token] = {"actor_id": actor_id, "expires_at": expires_at}
    logger.info("LOGIN_OK actor=%s", actor_id)
    return {"session_token": token, "expires_at": expires_at}


def _validate_pin(pin: str) -> None:
    if len(pin) != 6 or any(char < "0" or char > "9" for char in pin):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="PIN_FORMAT_INVALID",
        )


def set_account_pin(actor_id: str, household_id: str, pin: str) -> None:
    """Create or replace the six-digit PIN for one actor in one household."""
    _validate_pin(pin)
    _pin_hashes[(household_id, actor_id)] = hash_password(pin)


def authenticate_with_pin(actor_id: str, household_id: str, pin: str) -> dict[str, Any]:
    """Authenticate a household-scoped actor with a six-digit PIN."""
    _validate_pin(pin)
    rate_key = f"pin:{household_id}:{actor_id}"
    _check_rate_limit(rate_key)
    hashed = _pin_hashes.get((household_id, actor_id))
    if not verify_password(pin, hashed or _DUMMY_PIN_HASH):
        _failed_attempts[rate_key].append(time.time())
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="AUTH_FAILED")
    _failed_attempts.pop(rate_key, None)
    return _create_session(actor_id)


def validate_session(token: str) -> str:
    session = _sessions.get(token)
    if session is None or session["expires_at"] < time.time():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="SESSION_INVALID")
    return session["actor_id"]


def introspect_session(token: str) -> dict[str, Any]:
    """Report the live session behind a token so a client can revalidate it.

    Raises 401 once the session is expired, logged out or revoked, which is what
    lets a client drop a stale session on cold start instead of waiting for the
    next business request to fail.
    """
    actor_id = validate_session(token)
    return {"actor_id": actor_id, "expires_at": _sessions[token]["expires_at"]}


def logout(token: str) -> None:
    _sessions.pop(token, None)


def pin_households_for_actor(actor_id: str) -> list[str]:
    """Households where this actor has configured a PIN (see set_account_pin)."""
    return sorted(household for household, actor in _pin_hashes if actor == actor_id)


def _step_up_failed() -> HTTPException:
    # One opaque failure for wrong code, unknown challenge, foreign session and
    # action mismatch: the caller must not learn which check rejected it.
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="STEP_UP_FAILED")


def generate_pin_challenge(
    actor_id: str,
    action: str,
    session_token: str,
    household_id: str | None = None,
) -> dict[str, Any]:
    """Open a single-use step-up challenge bound to this session and action.

    The response deliberately carries no secret. Verification re-checks the
    actor's own household PIN, so there is nothing to deliver out of band and
    nothing for a caller to echo back to itself.
    """
    session_actor = validate_session(session_token)
    if session_actor != actor_id:
        raise _step_up_failed()

    if household_id is None:
        candidates = pin_households_for_actor(actor_id)
        if not candidates:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="PIN_NOT_CONFIGURED",
            )
        if len(candidates) > 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="HOUSEHOLD_REQUIRED",
            )
        household_id = candidates[0]
    elif (household_id, actor_id) not in _pin_hashes:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="PIN_NOT_CONFIGURED")

    challenge_id = secrets.token_hex(16)
    expires_at = time.time() + PIN_TTL_SECONDS
    _pin_challenges[challenge_id] = {
        "actor_id": actor_id,
        "household_id": household_id,
        "action": action,
        "session_token": session_token,
        "expires_at": expires_at,
        "used": False,
    }
    logger.info("PIN_CREATED actor=%s action=%s challenge=%s", actor_id, action, challenge_id)
    return {
        "challenge_id": challenge_id,
        "action": action,
        "household_id": household_id,
        "expires_at": expires_at,
    }


def verify_pin_challenge(
    challenge_id: str,
    action: str,
    session_token: str,
    code: str,
) -> dict[str, Any]:
    """Consume a step-up challenge. Never logs or echoes the submitted code."""
    challenge = _pin_challenges.get(challenge_id)
    if challenge is None:
        logger.warning("PIN_NOT_FOUND challenge=%s", challenge_id)
        raise _step_up_failed()
    if challenge["expires_at"] < time.time():
        _pin_challenges.pop(challenge_id, None)
        logger.warning("PIN_EXPIRED challenge=%s", challenge_id)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="STEP_UP_EXPIRED")
    if challenge["used"]:
        logger.warning("PIN_REPLAY challenge=%s", challenge_id)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="STEP_UP_REPLAY")
    if challenge["session_token"] != session_token:
        logger.warning("PIN_SESSION_MISMATCH challenge=%s", challenge_id)
        raise _step_up_failed()
    if challenge["action"] != action:
        logger.warning("PIN_ACTION_MISMATCH challenge=%s", challenge_id)
        raise _step_up_failed()

    actor_id = challenge["actor_id"]
    household_id = challenge["household_id"]
    rate_key = f"stepup:{household_id}:{actor_id}"
    _check_rate_limit(rate_key)
    hashed = _pin_hashes.get((household_id, actor_id))
    if not verify_password(code, hashed or _DUMMY_PIN_HASH):
        # A wrong code does not burn the challenge, but it does count towards
        # the lockout so the challenge window cannot be brute forced.
        _failed_attempts[rate_key].append(time.time())
        logger.warning("PIN_CODE_MISMATCH actor=%s action=%s", actor_id, action)
        raise _step_up_failed()

    _failed_attempts.pop(rate_key, None)
    challenge["used"] = True
    confirmed_at = time.time()
    logger.info("PIN_VERIFIED actor=%s action=%s challenge=%s", actor_id, action, challenge_id)
    return {
        "status": "confirmed",
        "challenge_id": challenge_id,
        "action": action,
        "confirmed_at": confirmed_at,
    }
