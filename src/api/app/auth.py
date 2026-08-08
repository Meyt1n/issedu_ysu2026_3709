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
_failed_attempts: dict[str, list[float]] = defaultdict(list)
_sessions: dict[str, dict[str, Any]] = {}  # session_token → {actor_id, expires_at}
_pin_challenges: dict[str, dict[str, Any]] = {}  # pin_code → {actor_id, action, session_token, expires_at, used}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


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
    token = secrets.token_hex(32)
    expires_at = time.time() + SESSION_TTL_SECONDS
    _sessions[token] = {"actor_id": actor_id, "expires_at": expires_at}
    logger.info("LOGIN_OK actor=%s", actor_id)
    return {"session_token": token, "expires_at": expires_at}


def validate_session(token: str) -> str:
    session = _sessions.get(token)
    if session is None or session["expires_at"] < time.time():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="SESSION_INVALID")
    return session["actor_id"]


def logout(token: str) -> None:
    _sessions.pop(token, None)


def generate_pin_challenge(actor_id: str, action: str, session_token: str) -> dict[str, Any]:
    validate_session(session_token)
    pin = f"{secrets.randbelow(1000000):06d}"
    expires_at = time.time() + PIN_TTL_SECONDS
    _pin_challenges[pin] = {
        "actor_id": actor_id,
        "action": action,
        "session_token": session_token,
        "expires_at": expires_at,
        "used": False,
    }
    logger.info("PIN_CREATED actor=%s action=%s", actor_id, action)
    return {"pin": pin, "expires_at": expires_at, "action": action}


def verify_pin(pin: str, action: str, session_token: str) -> bool:
    challenge = _pin_challenges.get(pin)
    if challenge is None:
        logger.warning("PIN_NOT_FOUND")
        return False
    if challenge["expires_at"] < time.time():
        _pin_challenges.pop(pin, None)
        logger.warning("PIN_EXPIRED")
        return False
    if challenge["used"]:
        logger.warning("PIN_REPLAY")
        return False
    if challenge["session_token"] != session_token:
        logger.warning("PIN_SESSION_MISMATCH")
        return False
    if challenge["action"] != action:
        logger.warning("PIN_ACTION_MISMATCH")
        return False
    challenge["used"] = True
    logger.info("PIN_VERIFIED actor=%s action=%s", challenge["actor_id"], action)
    return True
