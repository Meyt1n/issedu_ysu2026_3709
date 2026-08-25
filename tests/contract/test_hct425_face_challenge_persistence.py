"""HCT-425 face-login challenges must be durable, single-use and DB-visible.

Challenges used to live in a process-local dict, which blocked multi-worker
and restart deployments (the production configuration gate failed closed).
These tests pin the durable contract: rows are stored in
``auth_face_challenge`` with opaque metadata only, are consumable from a
different DB session (simulating another API worker), expire server-side and
never survive a second use.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import (
    FAMILY_FACE_ACTOR_SENTINEL,
    MAX_FACE_CHALLENGES_PER_HOUSEHOLD,
    consume_face_challenge,
    create_face_challenge,
)
from app.models import AuthFaceChallenge

HOUSEHOLD = "persist-household"
ACTOR = "persist-actor"


def test_challenge_row_is_persisted_with_opaque_metadata_only(
    client: TestClient, db_session: Session
) -> None:
    response = client.post(
        "/api/v1/auth/face-challenge",
        json={"household_id": HOUSEHOLD, "actor_id": ACTOR},
    )
    assert response.status_code == 200, response.text
    challenge_id = response.json()["challenge_id"]

    row = db_session.get(AuthFaceChallenge, challenge_id)
    assert row is not None, "challenge must be stored in the database"
    assert row.actor_id == ACTOR
    assert row.household_id == HOUSEHOLD
    assert row.used_at is None
    # 只有 opaque 元数据：无帧、无模板、无相似度字段。
    column_names = {column.name for column in AuthFaceChallenge.__table__.columns}
    assert column_names == {
        "id",
        "actor_id",
        "household_id",
        "expires_at",
        "used_at",
        "created_at",
    }


def test_challenge_issued_in_one_session_is_consumable_from_another(
    db_session: Session,
) -> None:
    """Simulate one worker issuing and a different worker consuming."""
    issued = create_face_challenge(ACTOR, HOUSEHOLD, db_session)
    db_session.commit()

    # 另一个"进程"：同一数据库上的新 ORM 会话。
    other_worker = Session(bind=db_session.get_bind(), expire_on_commit=False)
    try:
        consume_face_challenge(issued["challenge_id"], ACTOR, HOUSEHOLD, other_worker)
    finally:
        other_worker.close()

    db_session.expire_all()
    row = db_session.get(AuthFaceChallenge, issued["challenge_id"])
    assert row is not None and row.used_at is not None


def test_consumed_challenge_cannot_be_replayed_from_any_session(
    db_session: Session,
) -> None:
    issued = create_face_challenge(ACTOR, HOUSEHOLD, db_session)
    db_session.commit()
    consume_face_challenge(issued["challenge_id"], ACTOR, HOUSEHOLD, db_session)

    replay_worker = Session(bind=db_session.get_bind(), expire_on_commit=False)
    try:
        import pytest
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as excinfo:
            consume_face_challenge(issued["challenge_id"], ACTOR, HOUSEHOLD, replay_worker)
        assert excinfo.value.status_code == 401
        assert excinfo.value.detail == "FACE_AUTH_FAILED"
    finally:
        replay_worker.close()


def test_expired_challenge_is_rejected_and_deleted(client: TestClient, db_session: Session) -> None:
    response = client.post(
        "/api/v1/auth/face-challenge",
        json={"household_id": HOUSEHOLD, "actor_id": ACTOR},
    )
    challenge_id = response.json()["challenge_id"]

    row = db_session.get(AuthFaceChallenge, challenge_id)
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    files = [("frames", ("frame.jpg", b"\xff\xd8\xff", "image/jpeg"))]
    rejected = client.post(
        "/api/v1/auth/face-login",
        data={
            "household_id": HOUSEHOLD,
            "actor_id": ACTOR,
            "challenge_id": challenge_id,
        },
        files=files,
    )
    assert rejected.status_code == 401
    assert rejected.json()["detail"] == "FACE_AUTH_FAILED"
    db_session.expire_all()
    assert db_session.get(AuthFaceChallenge, challenge_id) is None


def test_challenge_binding_mismatch_is_rejected_without_burning(
    db_session: Session,
) -> None:
    issued = create_face_challenge(ACTOR, HOUSEHOLD, db_session)
    db_session.commit()

    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        consume_face_challenge(issued["challenge_id"], "other-actor", HOUSEHOLD, db_session)
    with pytest.raises(HTTPException):
        consume_face_challenge(issued["challenge_id"], ACTOR, "other-household", db_session)

    # 绑定不匹配不烧掉 challenge，正确绑定仍可一次性使用。
    consume_face_challenge(issued["challenge_id"], ACTOR, HOUSEHOLD, db_session)


def test_household_scoped_eviction_cannot_evict_other_families(
    db_session: Session,
) -> None:
    other = create_face_challenge("other-actor", "other-household", db_session)
    db_session.commit()

    for _ in range(MAX_FACE_CHALLENGES_PER_HOUSEHOLD + 3):
        create_face_challenge(ACTOR, HOUSEHOLD, db_session)
    db_session.commit()

    flooded_count = len(
        db_session.scalars(
            select(AuthFaceChallenge.id).where(AuthFaceChallenge.household_id == HOUSEHOLD)
        ).all()
    )
    assert flooded_count <= MAX_FACE_CHALLENGES_PER_HOUSEHOLD
    assert db_session.get(AuthFaceChallenge, other["challenge_id"]) is not None


def test_family_face_challenge_uses_sentinel_actor(db_session: Session) -> None:
    from app.auth import create_family_face_challenge

    issued = create_family_face_challenge(HOUSEHOLD, db_session)
    db_session.commit()
    row = db_session.get(AuthFaceChallenge, issued["challenge_id"])
    assert row is not None
    assert row.actor_id == FAMILY_FACE_ACTOR_SENTINEL
