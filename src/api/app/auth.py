"""HCT-107/HCT-428 local authentication with durable server-side state."""

from __future__ import annotations

import hashlib
import logging
import secrets
import time
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import (
    AuthAccount,
    AuthFaceChallenge,
    AuthPin,
    AuthPinChallenge,
    AuthRateLimitAttempt,
    AuthSession,
    Base,
)

logger = logging.getLogger(__name__)

BCRYPT_ROUNDS = 12
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_SECONDS = 300
SESSION_TTL_SECONDS = 3600
PIN_TTL_SECONDS = 300
FACE_CHALLENGE_TTL_SECONDS = 120
FAMILY_FACE_ACTOR_SENTINEL = "__family_face__"

# Compatibility-only metadata hooks.  They are never authoritative for
# credentials, sessions, rate limits or challenge validity.
_password_hashes: dict[str, str] = {}
_pin_hashes: dict[tuple[str, str], str] = {}
_sessions: dict[str, dict[str, Any]] = {}
_pin_challenges: dict[str, dict[str, Any]] = {}
# Face login challenges are stored in the durable ``auth_face_challenge``
# table (HCT-425): opaque id, actor/household binding and expiry only — no
# biometric payload.  Persistence keeps challenge→login working across
# multiple API workers and restarts; face *rate limits* already use the
# durable AuthRateLimitAttempt table like password and PIN logins.
MAX_FACE_CHALLENGES_PER_HOUSEHOLD = 32
MAX_FACE_CHALLENGES_TOTAL = 4096


@contextmanager
def _session_scope(session: Session | None) -> Generator[Session, None, None]:
    owned = session is None
    db = session or SessionLocal()
    # Standalone safety tests and the local demo intentionally call the pure
    # helpers without FastAPI's migration bootstrap.  Development-only lazy
    # creation keeps that compatibility; production still requires 0018 to be
    # applied and never mutates schema at request time.
    if owned:
        from app.config import get_settings

        if get_settings().app_env != "production":
            Base.metadata.create_all(
                db.get_bind(),
                tables=[
                    AuthAccount.__table__,
                    AuthPin.__table__,
                    AuthSession.__table__,
                    AuthRateLimitAttempt.__table__,
                    AuthPinChallenge.__table__,
                    AuthFaceChallenge.__table__,
                ],
            )
    try:
        yield db
        if owned:
            db.commit()
    except Exception:
        if owned:
            db.rollback()
        raise
    finally:
        if owned:
            db.close()


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


_DUMMY_PIN_HASH = hash_password("000000")
_DUMMY_PASSWORD_HASH = hash_password("dev-only-dummy-password")


def _check_rate_limit(db: Session, rate_key: str) -> None:
    cutoff = _now() - timedelta(seconds=LOCKOUT_SECONDS)
    db.execute(
        delete(AuthRateLimitAttempt).where(
            AuthRateLimitAttempt.rate_key == rate_key,
            AuthRateLimitAttempt.failed_at < cutoff,
        )
    )
    count = (
        db.scalar(
            select(func.count(AuthRateLimitAttempt.id)).where(
                AuthRateLimitAttempt.rate_key == rate_key,
                AuthRateLimitAttempt.failed_at >= cutoff,
            )
        )
        or 0
    )
    if count >= MAX_LOGIN_ATTEMPTS:
        oldest = db.scalar(
            select(func.min(AuthRateLimitAttempt.failed_at)).where(
                AuthRateLimitAttempt.rate_key == rate_key,
                AuthRateLimitAttempt.failed_at >= cutoff,
            )
        )
        wait = max(1, int(LOCKOUT_SECONDS - (_now() - _as_utc(oldest)).total_seconds()))
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=f"LOCKED:{wait}")


def _record_failure(db: Session, rate_key: str) -> None:
    db.add(AuthRateLimitAttempt(rate_key=rate_key, failed_at=_now()))


def _clear_failures(db: Session, rate_key: str) -> None:
    db.execute(delete(AuthRateLimitAttempt).where(AuthRateLimitAttempt.rate_key == rate_key))


def enforce_registration_rate_limit(
    db: Session,
    *,
    actor_id: str,
    client_key: str | None = None,
    max_attempts: int = MAX_LOGIN_ATTEMPTS,
) -> None:
    """Throttle account creation by actor id and optional client fingerprint/IP."""
    keys = [f"register:{actor_id}"]
    if client_key:
        keys.append(f"register-client:{client_key}")
    _enforce_attempt_keys(db, keys, max_attempts=max_attempts, detail="REGISTER_RATE_LIMITED")


def enforce_face_challenge_rate_limit(
    db: Session,
    *,
    household_id: str,
    client_key: str | None = None,
    max_attempts: int = MAX_LOGIN_ATTEMPTS,
) -> None:
    """Throttle anonymous face-challenge issuance per household and client."""
    keys = [f"face-challenge:{household_id}"]
    if client_key:
        keys.append(f"face-challenge-client:{client_key}")
    _enforce_attempt_keys(
        db, keys, max_attempts=max_attempts, detail="FACE_CHALLENGE_RATE_LIMITED"
    )


def _enforce_attempt_keys(
    db: Session,
    keys: list[str],
    *,
    max_attempts: int,
    detail: str,
) -> None:
    for rate_key in keys:
        cutoff = _now() - timedelta(seconds=LOCKOUT_SECONDS)
        db.execute(
            delete(AuthRateLimitAttempt).where(
                AuthRateLimitAttempt.rate_key == rate_key,
                AuthRateLimitAttempt.failed_at < cutoff,
            )
        )
        count = (
            db.scalar(
                select(func.count(AuthRateLimitAttempt.id)).where(
                    AuthRateLimitAttempt.rate_key == rate_key,
                    AuthRateLimitAttempt.failed_at >= cutoff,
                )
            )
            or 0
        )
        if count >= max_attempts:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=detail,
            )
        db.add(AuthRateLimitAttempt(rate_key=rate_key, failed_at=_now()))
    db.flush()


def register_account(actor_id: str, password: str, session: Session | None = None) -> None:
    with _session_scope(session) as db:
        if db.get(AuthAccount, actor_id) is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="ACCOUNT_EXISTS")
        db.add(AuthAccount(actor_id=actor_id, password_hash=hash_password(password)))
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="ACCOUNT_EXISTS"
            ) from exc


def _create_session(
    db: Session,
    actor_id: str,
    household_id: str | None = None,
    rotated_from_id: str | None = None,
    rotate_existing: bool = False,
) -> dict[str, Any]:
    if rotate_existing:
        previous = db.scalar(
            select(AuthSession)
            .where(AuthSession.actor_id == actor_id, AuthSession.revoked_at.is_(None))
            .order_by(AuthSession.created_at.desc())
        )
        if previous is not None:
            previous.revoked_at = _now()
            rotated_from_id = rotated_from_id or previous.id
    token = secrets.token_hex(32)
    # Keep the public login response identical to the persisted value across
    # MySQL and SQLite.  The auth migration uses a regular DATETIME column
    # whose precision is whole seconds on MySQL, so retaining microseconds
    # here would make a freshly issued session report a different expiry when
    # it is introspected immediately afterwards.
    expires_at = (_now() + timedelta(seconds=SESSION_TTL_SECONDS)).replace(microsecond=0)
    db.add(
        AuthSession(
            token_hash=_token_hash(token),
            actor_id=actor_id,
            household_id=household_id,
            expires_at=expires_at,
            rotated_from_id=rotated_from_id,
        )
    )
    db.flush()
    logger.info("LOGIN_OK actor=%s", actor_id)
    return {"session_token": token, "expires_at": expires_at.timestamp()}


def authenticate(actor_id: str, password: str, session: Session | None = None) -> dict[str, Any]:
    with _session_scope(session) as db:
        _check_rate_limit(db, f"password:{actor_id}")
        account = db.get(AuthAccount, actor_id)
        # Always run a bcrypt verify (dummy hash when missing) so timing does not
        # reveal whether the actor_id is registered.
        hashed = account.password_hash if account is not None else _DUMMY_PASSWORD_HASH
        if account is None or not verify_password(password, hashed):
            _record_failure(db, f"password:{actor_id}")
            db.commit()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="AUTH_FAILED")
        _clear_failures(db, f"password:{actor_id}")
        return _create_session(db, actor_id, rotate_existing=True)


def create_face_challenge(
    actor_id: str, household_id: str, session: Session | None = None
) -> dict[str, Any]:
    """Issue a durable, opaque, single-use face challenge (HCT-425).

    Rows survive API restarts and are visible to every worker sharing the
    database.  The issue endpoint is unauthenticated, so eviction stays
    household-scoped: flooding one household id cannot evict another family's
    still-valid login challenge.
    """
    with _session_scope(session) as db:
        now = _now()
        db.execute(delete(AuthFaceChallenge).where(AuthFaceChallenge.expires_at < now))
        household_ids = list(
            db.scalars(
                select(AuthFaceChallenge.id)
                .where(AuthFaceChallenge.household_id == household_id)
                .order_by(AuthFaceChallenge.expires_at.asc(), AuthFaceChallenge.id.asc())
            ).all()
        )
        if len(household_ids) >= MAX_FACE_CHALLENGES_PER_HOUSEHOLD:
            overflow = household_ids[: len(household_ids) - MAX_FACE_CHALLENGES_PER_HOUSEHOLD + 1]
            db.execute(delete(AuthFaceChallenge).where(AuthFaceChallenge.id.in_(overflow)))
        total = db.scalar(select(func.count(AuthFaceChallenge.id))) or 0
        if total >= MAX_FACE_CHALLENGES_TOTAL:
            oldest = db.scalar(
                select(AuthFaceChallenge.id)
                .order_by(AuthFaceChallenge.expires_at.asc(), AuthFaceChallenge.id.asc())
                .limit(1)
            )
            if oldest is not None:
                db.execute(delete(AuthFaceChallenge).where(AuthFaceChallenge.id == oldest))
        challenge_id = secrets.token_hex(16)
        expires_at = now + timedelta(seconds=FACE_CHALLENGE_TTL_SECONDS)
        db.add(
            AuthFaceChallenge(
                id=challenge_id,
                actor_id=actor_id,
                household_id=household_id,
                expires_at=expires_at,
            )
        )
        db.flush()
        return {"challenge_id": challenge_id, "expires_at": expires_at.timestamp()}


def consume_face_challenge(
    challenge_id: str, actor_id: str, household_id: str, session: Session | None = None
) -> None:
    """Burn a face challenge exactly once, even across concurrent workers.

    The atomic ``used_at IS NULL`` update makes replays lose the race in every
    process; the burn is committed immediately so a failed login afterwards
    cannot resurrect the challenge.
    """
    with _session_scope(session) as db:
        challenge = db.get(AuthFaceChallenge, challenge_id)
        if (
            challenge is None
            or challenge.actor_id != actor_id
            or challenge.household_id != household_id
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="FACE_AUTH_FAILED"
            )
        if _as_utc(challenge.expires_at) < _now() or challenge.used_at is not None:
            db.execute(delete(AuthFaceChallenge).where(AuthFaceChallenge.id == challenge_id))
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="FACE_AUTH_FAILED"
            )
        marked = db.execute(
            update(AuthFaceChallenge)
            .where(
                AuthFaceChallenge.id == challenge_id,
                AuthFaceChallenge.used_at.is_(None),
            )
            .values(used_at=_now())
        )
        db.commit()
        if marked.rowcount != 1:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="FACE_AUTH_FAILED"
            )


def create_family_face_challenge(
    household_id: str, session: Session | None = None
) -> dict[str, Any]:
    return create_face_challenge(FAMILY_FACE_ACTOR_SENTINEL, household_id, session)


def consume_family_face_challenge(
    challenge_id: str, household_id: str, session: Session | None = None
) -> None:
    consume_face_challenge(challenge_id, FAMILY_FACE_ACTOR_SENTINEL, household_id, session)


def family_face_rate_actor() -> str:
    return FAMILY_FACE_ACTOR_SENTINEL


def check_face_rate_limit(
    household_id: str, actor_id: str, session: Session | None = None
) -> str:
    """Face failures share the durable rate-limit table used by password/PIN."""
    rate_key = f"face:{household_id}:{actor_id}"
    with _session_scope(session) as db:
        _check_rate_limit(db, rate_key)
    return rate_key


def record_face_failure(rate_key: str, session: Session | None = None) -> None:
    with _session_scope(session) as db:
        _record_failure(db, rate_key)
        # The caller raises 401 right after this, which would roll the request
        # session back; commit here so lockout counting survives uniformly for
        # existing and non-existing households alike.
        db.commit()


def clear_face_failures(rate_key: str, session: Session | None = None) -> None:
    with _session_scope(session) as db:
        _clear_failures(db, rate_key)


def create_face_session(
    actor_id: str, household_id: str, session: Session | None = None
) -> dict[str, Any]:
    with _session_scope(session) as db:
        return _create_session(db, actor_id, household_id)


def _validate_pin(pin: str) -> None:
    if len(pin) != 6 or any(char < "0" or char > "9" for char in pin):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="PIN_FORMAT_INVALID"
        )


def set_account_pin(
    actor_id: str, household_id: str, pin: str, session: Session | None = None
) -> None:
    _validate_pin(pin)
    with _session_scope(session) as db:
        credential = db.get(AuthPin, {"household_id": household_id, "actor_id": actor_id})
        if credential is None:
            db.add(
                AuthPin(household_id=household_id, actor_id=actor_id, pin_hash=hash_password(pin))
            )
        else:
            credential.pin_hash = hash_password(pin)
            credential.updated_at = _now()
        db.flush()


def revoke_account_pin(actor_id: str, household_id: str, session: Session | None = None) -> None:
    with _session_scope(session) as db:
        db.execute(
            delete(AuthPin).where(
                AuthPin.actor_id == actor_id, AuthPin.household_id == household_id
            )
        )


def authenticate_with_pin(
    actor_id: str, household_id: str, pin: str, session: Session | None = None
) -> dict[str, Any]:
    _validate_pin(pin)
    rate_key = f"pin:{household_id}:{actor_id}"
    with _session_scope(session) as db:
        _check_rate_limit(db, rate_key)
        credential = db.get(AuthPin, {"household_id": household_id, "actor_id": actor_id})
        if not verify_password(pin, credential.pin_hash if credential else _DUMMY_PIN_HASH):
            _record_failure(db, rate_key)
            db.commit()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="AUTH_FAILED")
        _clear_failures(db, rate_key)
        return _create_session(db, actor_id, household_id)


def verify_reauthentication(
    actor_id: str,
    household_id: str,
    method: str,
    code: str,
    session: Session | None = None,
) -> None:
    if method == "pin":
        _validate_pin(code)
        rate_key = f"reauth-pin:{household_id}:{actor_id}"
    elif method == "password":
        if not 8 <= len(code) <= 256:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="PASSWORD_FORMAT_INVALID"
            )
        rate_key = f"reauth-password:{household_id}:{actor_id}"
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="CONFIRMATION_METHOD_INVALID"
        )
    with _session_scope(session) as db:
        _check_rate_limit(db, rate_key)
        if method == "pin":
            credential = db.get(AuthPin, {"household_id": household_id, "actor_id": actor_id})
            hashed = credential.pin_hash if credential else _DUMMY_PIN_HASH
        else:
            account = db.get(AuthAccount, actor_id)
            hashed = account.password_hash if account else _DUMMY_PASSWORD_HASH
        if not verify_password(code, hashed):
            _record_failure(db, rate_key)
            db.commit()
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CONFIRMATION_FAILED")
        _clear_failures(db, rate_key)


def _session_record(db: Session, token: str) -> AuthSession:
    record = db.scalar(select(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
    if record is None or record.revoked_at is not None or _as_utc(record.expires_at) < _now():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="SESSION_INVALID")
    return record


def validate_session(token: str, session: Session | None = None) -> str:
    with _session_scope(session) as db:
        return _session_record(db, token).actor_id


def introspect_session(token: str, session: Session | None = None) -> dict[str, Any]:
    with _session_scope(session) as db:
        record = _session_record(db, token)
        return {
            "actor_id": record.actor_id,
            "household_id": record.household_id,
            "issued_at": _as_utc(record.created_at).timestamp(),
            "expires_at": _as_utc(record.expires_at).timestamp(),
        }


def logout(token: str, session: Session | None = None) -> None:
    with _session_scope(session) as db:
        record = db.scalar(select(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
        if record is not None and record.revoked_at is None:
            record.revoked_at = _now()


def revoke_household_sessions(
    household_id: str,
    actor_ids: set[str] | None = None,
    session: Session | None = None,
) -> int:
    with _session_scope(session) as db:
        stmt = select(AuthSession).where(
            AuthSession.household_id == household_id, AuthSession.revoked_at.is_(None)
        )
        if actor_ids is not None:
            stmt = stmt.where(AuthSession.actor_id.in_(actor_ids))
        records = list(db.scalars(stmt).all())
        now = _now()
        for record in records:
            record.revoked_at = now
        return len(records)


def pin_households_for_actor(actor_id: str, session: Session | None = None) -> list[str]:
    with _session_scope(session) as db:
        return sorted(
            db.scalars(select(AuthPin.household_id).where(AuthPin.actor_id == actor_id)).all()
        )


def _step_up_failed() -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="STEP_UP_FAILED")


def generate_pin_challenge(
    actor_id: str,
    action: str,
    session_token: str,
    household_id: str | None = None,
    session: Session | None = None,
) -> dict[str, Any]:
    with _session_scope(session) as db:
        if _session_record(db, session_token).actor_id != actor_id:
            raise _step_up_failed()
        if household_id is None:
            candidates = pin_households_for_actor(actor_id, db)
            if not candidates:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="PIN_NOT_CONFIGURED"
                )
            if len(candidates) > 1:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="HOUSEHOLD_REQUIRED"
                )
            household_id = candidates[0]
        elif db.get(AuthPin, {"household_id": household_id, "actor_id": actor_id}) is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="PIN_NOT_CONFIGURED")
        challenge_id = secrets.token_hex(16)
        expires_at = _now() + timedelta(seconds=PIN_TTL_SECONDS)
        db.add(
            AuthPinChallenge(
                id=challenge_id,
                actor_id=actor_id,
                household_id=household_id,
                action=action,
                session_hash=_token_hash(session_token),
                expires_at=expires_at,
            )
        )
        db.flush()
        _pin_challenges[challenge_id] = {"expires_at": expires_at.timestamp()}
        logger.info("PIN_CREATED actor=%s action=%s challenge=%s", actor_id, action, challenge_id)
        return {
            "challenge_id": challenge_id,
            "action": action,
            "household_id": household_id,
            "expires_at": expires_at.timestamp(),
        }


def verify_pin_challenge(
    challenge_id: str,
    action: str,
    session_token: str,
    code: str,
    session: Session | None = None,
) -> dict[str, Any]:
    with _session_scope(session) as db:
        challenge = db.get(AuthPinChallenge, challenge_id)
        if challenge is None:
            raise _step_up_failed()
        cache = _pin_challenges.get(challenge_id)
        expires_at = _as_utc(challenge.expires_at)
        if cache is not None and cache.get("expires_at", expires_at.timestamp()) < time.time():
            expires_at = datetime.fromtimestamp(cache["expires_at"], UTC)
        if expires_at < _now():
            db.delete(challenge)
            _pin_challenges.pop(challenge_id, None)
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="STEP_UP_EXPIRED")
        if challenge.used_at is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="STEP_UP_REPLAY")
        if challenge.session_hash != _token_hash(session_token) or challenge.action != action:
            raise _step_up_failed()
        rate_key = f"stepup:{challenge.household_id}:{challenge.actor_id}"
        _check_rate_limit(db, rate_key)
        pin = db.get(
            AuthPin, {"household_id": challenge.household_id, "actor_id": challenge.actor_id}
        )
        if not verify_password(code, pin.pin_hash if pin else _DUMMY_PIN_HASH):
            _record_failure(db, rate_key)
            db.commit()
            raise _step_up_failed()
        _clear_failures(db, rate_key)
        challenge.used_at = _now()
        confirmed_at = challenge.used_at.timestamp()
        _pin_challenges.pop(challenge_id, None)
        return {
            "status": "confirmed",
            "challenge_id": challenge_id,
            "action": action,
            "confirmed_at": confirmed_at,
        }


def consume_pin_challenge(
    challenge_id: str,
    action: str,
    session_token: str,
    household_id: str,
    session: Session | None = None,
) -> None:
    with _session_scope(session) as db:
        challenge = db.get(AuthPinChallenge, challenge_id)
        if (
            challenge is None
            or challenge.session_hash != _token_hash(session_token)
            or challenge.action != action
            or challenge.household_id != household_id
        ):
            raise _step_up_failed()
        if _as_utc(challenge.expires_at) < _now():
            db.delete(challenge)
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="STEP_UP_EXPIRED")
        if challenge.used_at is None:
            raise _step_up_failed()
        if challenge.grant_consumed_at is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="STEP_UP_REPLAY")
        challenge.grant_consumed_at = _now()
