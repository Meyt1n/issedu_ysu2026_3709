from datetime import UTC, datetime

import cv2
import numpy as np
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import routes
from app.face_credentials import encrypt_template
from app.models import FaceCredential


def _webcam_selfie_jpeg(width: int = 960, height: int = 540, *, seed: int = 7) -> bytes:
    """Guided-capture style frame: one person in front of a plain wall.

    Low edge density on purpose — the exact kind of valid frame the
    medicine-carton OCR gate used to reject before HCT-424 gave face frames
    their own gate.  These frames must flow through the *real* gate.
    """
    rng = np.random.default_rng(seed)
    frame = np.full((height, width, 3), 160.0, dtype=np.float32)
    frame += rng.normal(0.0, 2.0, frame.shape).astype(np.float32)
    center_x, center_y = width // 2, int(height * 0.45)
    short = min(width, height)
    cv2.ellipse(
        frame,
        (center_x, height),
        (int(width * 0.30), int(height * 0.45)),
        0, 180, 360, (70, 60, 55), -1,
    )
    axes = (int(short * 0.20), int(short * 0.28))
    cv2.ellipse(frame, (center_x, center_y), axes, 0, 0, 360, (150, 170, 205), -1)
    eye_y = center_y - axes[1] // 5
    for dx in (-axes[0] // 2, axes[0] // 2):
        cv2.circle(frame, (center_x + dx, eye_y), 6, (30, 30, 30), -1)
    cv2.ellipse(frame, (center_x, center_y + axes[1] // 2), (20, 8), 0, 0, 180, (80, 80, 140), 2)
    ok, encoded = cv2.imencode(
        ".jpg",
        np.clip(frame, 0, 255).astype(np.uint8),
        [cv2.IMWRITE_JPEG_QUALITY, 90],
    )
    assert ok
    return encoded.tobytes()


def _webcam_frames(
    prefix: str,
    count: int = 3,
    *,
    width: int = 960,
    height: int = 540,
) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [
        (
            "frames",
            (
                f"{prefix}-{index}.jpg",
                _webcam_selfie_jpeg(width, height, seed=index),
                "image/jpeg",
            ),
        )
        for index in range(1, count + 1)
    ]


def test_face_challenge_is_opaque_and_single_use(client: TestClient) -> None:
    challenge_response = client.post(
        "/api/v1/auth/face-challenge",
        json={"household_id": "household-1", "actor_id": "owner"},
    )

    assert challenge_response.status_code == 200
    payload = challenge_response.json()
    assert set(payload) == {"challenge_id", "expires_at"}
    assert len(payload["challenge_id"]) >= 16

    form = {
        "household_id": "household-1",
        "actor_id": "owner",
        "challenge_id": payload["challenge_id"],
    }
    files = [("frames", ("frame.jpg", b"\xff\xd8\xff", "image/jpeg"))]
    first = client.post("/api/v1/auth/face-login", data=form, files=files)
    second = client.post("/api/v1/auth/face-login", data=form, files=files)

    assert first.status_code == 401
    assert second.status_code == 401
    assert first.json()["detail"] == "FACE_AUTH_FAILED"
    assert second.json()["detail"] == "FACE_AUTH_FAILED"


def test_face_failures_are_rate_limited(client: TestClient) -> None:
    household_id = "rate-limit-household"
    actor_id = "rate-limit-actor"
    files = [("frames", ("frame.jpg", b"\xff\xd8\xff", "image/jpeg"))]

    responses = []
    for _ in range(5):
        challenge_response = client.post(
            "/api/v1/auth/face-challenge",
            json={"household_id": household_id, "actor_id": actor_id},
        )
        assert challenge_response.status_code == 200, challenge_response.text
        responses.append(
            client.post(
                "/api/v1/auth/face-login",
                data={
                    "household_id": household_id,
                    "actor_id": actor_id,
                    "challenge_id": challenge_response.json()["challenge_id"],
                },
                files=files,
            )
        )

    assert [response.status_code for response in responses] == [401] * 5

    # challenge 签发有独立的匿名限流：第 6 次签发直接 429。
    throttled_challenge = client.post(
        "/api/v1/auth/face-challenge",
        json={"household_id": household_id, "actor_id": actor_id},
    )
    assert throttled_challenge.status_code == 429
    assert throttled_challenge.json()["detail"] == "FACE_CHALLENGE_RATE_LIMITED"

    # 登录失败限流独立生效：即使拿不到新 challenge，第 6 次登录也被锁定。
    sixth_login = client.post(
        "/api/v1/auth/face-login",
        data={
            "household_id": household_id,
            "actor_id": actor_id,
            "challenge_id": "0" * 32,
        },
        files=files,
    )
    assert sixth_login.status_code == 429


def test_member_account_can_discover_household_and_be_bound(client: TestClient) -> None:
    owner = "hct425-account-owner"
    household = client.post(
        "/api/v1/households",
        headers={"X-Actor-Id": owner},
        json={"name": "成员账号家庭"},
    ).json()["id"]
    member = client.post(
        f"/api/v1/households/{household}/members",
        headers={"X-Actor-Id": owner},
        json={"display_name": "爷爷", "role": "DEPENDENT"},
    ).json()

    bound = client.patch(
        f"/api/v1/households/{household}/members/{member['id']}/account",
        headers={"X-Actor-Id": owner},
        json={"actor_id": "grandpa-local"},
    )
    assert bound.status_code == 200, bound.text
    assert bound.json()["actor_id"] == "grandpa-local"

    discovered = client.get(
        "/api/v1/households",
        headers={"X-Actor-Id": "grandpa-local", "X-Access-Purpose": "family-care"},
    )
    assert discovered.status_code == 200, discovered.text
    assert [item["id"] for item in discovered.json()] == [household]


def test_dynamic_face_registration_can_be_used_for_local_login(
    client: TestClient,
    monkeypatch,
) -> None:
    owner = "hct425-dynamic-owner"
    password = "hct425-dynamic-owner-pass"
    client.post("/api/v1/auth/register", json={"actor_id": owner, "password": password})
    owner_login = client.post(
        "/api/v1/auth/login",
        json={"actor_id": owner, "password": password},
    )
    assert owner_login.status_code == 200
    owner_token = owner_login.json()["session_token"]
    household = client.post(
        "/api/v1/households",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"name": "动态人脸家庭"},
    ).json()["id"]
    member = client.post(
        f"/api/v1/households/{household}/members",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"display_name": "奶奶", "actor_id": "grandma-dynamic"},
    ).json()

    template = b"\x00\x00\x80\x3f" * 128
    monkeypatch.setattr(
        routes,
        "extract_face_template",
        lambda _data, **_kwargs: (
            template,
            {
                "algorithm_version": "opencv-yunet-sface-v3",
                "feature_version": "face-embedding-sface-v3",
            },
        ),
    )
    monkeypatch.setattr(routes, "check_face_liveness", lambda *_args, **_kwargs: None)

    # Regression HCT-424: plain-background webcam frames must pass the real
    # face frame gate (the old carton OCR gate rejected them as low quality).
    files = _webcam_frames("frame")
    registered = client.post(
        f"/api/v1/households/{household}/face-credentials",
        headers={"Authorization": f"Bearer {owner_token}"},
        data={
            "consent": "true",
            "target_actor_id": member["actor_id"],
            "confirmation_method": "password",
            "confirmation_code": password,
        },
        files=files,
    )
    assert registered.status_code == 201, registered.text
    assert registered.json()["algorithm_version"] == "opencv-yunet-sface-v3"

    challenge = client.post(
        "/api/v1/auth/face-challenge",
        json={"household_id": household, "actor_id": member["actor_id"]},
    )
    assert challenge.status_code == 200
    logged_in = client.post(
        "/api/v1/auth/face-login",
        data={
            "household_id": household,
            "actor_id": member["actor_id"],
            "challenge_id": challenge.json()["challenge_id"],
        },
        files=files,
    )
    assert logged_in.status_code == 200, logged_in.text
    assert logged_in.json()["actor_id"] == member["actor_id"]
    assert logged_in.json()["household_id"] == household


def test_family_face_login_identifies_the_best_member_inside_bound_household(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    owner = "hct425-family-owner"
    household = client.post(
        "/api/v1/households",
        headers={"X-Actor-Id": owner},
        json={"name": "家庭内一对多识别"},
    ).json()["id"]
    grandpa = client.post(
        f"/api/v1/households/{household}/members",
        headers={"X-Actor-Id": owner},
        json={"display_name": "爷爷", "actor_id": "hct425-grandpa"},
    ).json()
    grandma = client.post(
        f"/api/v1/households/{household}/members",
        headers={"X-Actor-Id": owner},
        json={"display_name": "奶奶", "actor_id": "hct425-grandma"},
    ).json()

    negative_template = b"\x00\x00\x80\xbf" * 128
    positive_template = b"\x00\x00\x80\x3f" * 128
    now = datetime.now(UTC)
    db_session.add_all(
        [
            FaceCredential(
                household_id=household,
                actor_id=grandpa["actor_id"],
                encrypted_template=encrypt_template(negative_template),
                algorithm_version="opencv-yunet-sface-v3",
                feature_version="face-embedding-sface-v3",
                credential_version=1,
                consent_version="face-registration-consent-v1",
                status="ACTIVE",
                created_by=owner,
                consented_at=now,
            ),
            FaceCredential(
                household_id=household,
                actor_id=grandma["actor_id"],
                encrypted_template=encrypt_template(positive_template),
                algorithm_version="opencv-yunet-sface-v3",
                feature_version="face-embedding-sface-v3",
                credential_version=1,
                consent_version="face-registration-consent-v1",
                status="ACTIVE",
                created_by=owner,
                consented_at=now,
            ),
        ]
    )
    db_session.commit()

    monkeypatch.setattr(
        routes,
        "extract_face_template",
        lambda _data, **_kwargs: (positive_template, {}))
    monkeypatch.setattr(routes, "check_face_liveness", lambda *_args, **_kwargs: None)

    challenge = client.post(
        "/api/v1/auth/family-face-challenge",
        json={"household_id": household},
    )
    assert challenge.status_code == 200, challenge.text
    files = _webcam_frames("family-frame")
    logged_in = client.post(
        "/api/v1/auth/family-face-login",
        data={
            "household_id": household,
            "challenge_id": challenge.json()["challenge_id"],
        },
        files=files,
    )

    assert logged_in.status_code == 200, logged_in.text
    assert logged_in.json()["actor_id"] == grandma["actor_id"]
    assert logged_in.json()["household_id"] == household


def test_face_login_rejects_a_single_injected_matching_frame(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    """Every frame must match: victim-photo + attacker motion frames fails."""
    owner = "hct425-inject-owner"
    household = client.post(
        "/api/v1/households",
        headers={"X-Actor-Id": owner},
        json={"name": "单帧注入防护"},
    ).json()["id"]
    member = client.post(
        f"/api/v1/households/{household}/members",
        headers={"X-Actor-Id": owner},
        json={"display_name": "爷爷", "actor_id": "hct425-inject-grandpa"},
    ).json()

    victim_template = b"\x00\x00\x80\x3f" * 128
    attacker_template = b"\x00\x00\x80\xbf" * 128
    db_session.add(
        FaceCredential(
            household_id=household,
            actor_id=member["actor_id"],
            encrypted_template=encrypt_template(victim_template),
            algorithm_version="opencv-yunet-sface-v3",
            feature_version="face-embedding-sface-v3",
            credential_version=1,
            consent_version="face-registration-consent-v1",
            status="ACTIVE",
            created_by=owner,
            consented_at=datetime.now(UTC),
        )
    )
    db_session.commit()

    # First frame is a stolen photo of the account holder; the remaining
    # frames belong to the attacker and provide the motion for liveness.
    extracted = iter([victim_template, attacker_template, attacker_template])
    monkeypatch.setattr(
        routes,
        "extract_face_template",
        lambda _data, **_kwargs: (next(extracted), {}))
    monkeypatch.setattr(routes, "check_face_liveness", lambda *_args, **_kwargs: None)

    challenge = client.post(
        "/api/v1/auth/face-challenge",
        json={"household_id": household, "actor_id": member["actor_id"]},
    )
    files = _webcam_frames("inject-frame")
    rejected = client.post(
        "/api/v1/auth/face-login",
        data={
            "household_id": household,
            "actor_id": member["actor_id"],
            "challenge_id": challenge.json()["challenge_id"],
        },
        files=files,
    )

    assert rejected.status_code == 401
    assert rejected.json()["detail"] == "FACE_AUTH_FAILED"


def test_deleting_a_face_credential_revokes_household_sessions(
    client: TestClient,
    monkeypatch,
) -> None:
    owner = "hct425-revoke-owner"
    password = "hct425-revoke-owner-pass"
    client.post("/api/v1/auth/register", json={"actor_id": owner, "password": password})
    owner_token = client.post(
        "/api/v1/auth/login",
        json={"actor_id": owner, "password": password},
    ).json()["session_token"]
    household = client.post(
        "/api/v1/households",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"name": "删除即撤销会话"},
    ).json()["id"]
    member = client.post(
        f"/api/v1/households/{household}/members",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"display_name": "奶奶", "actor_id": "hct425-revoke-grandma"},
    ).json()

    template = b"\x00\x00\x80\x3f" * 128
    monkeypatch.setattr(
        routes,
        "extract_face_template",
        lambda _data, **_kwargs: (
            template,
            {
                "algorithm_version": "opencv-yunet-sface-v3",
                "feature_version": "face-embedding-sface-v3",
            },
        ),
    )
    monkeypatch.setattr(routes, "check_face_liveness", lambda *_args, **_kwargs: None)

    files = _webcam_frames("revoke-frame")
    credential = client.post(
        f"/api/v1/households/{household}/face-credentials",
        headers={"Authorization": f"Bearer {owner_token}"},
        data={
            "consent": "true",
            "target_actor_id": member["actor_id"],
            "confirmation_method": "password",
            "confirmation_code": password,
        },
        files=files,
    )
    assert credential.status_code == 201, credential.text

    challenge = client.post(
        "/api/v1/auth/face-challenge",
        json={"household_id": household, "actor_id": member["actor_id"]},
    )
    face_login = client.post(
        "/api/v1/auth/face-login",
        data={
            "household_id": household,
            "actor_id": member["actor_id"],
            "challenge_id": challenge.json()["challenge_id"],
        },
        files=files,
    )
    assert face_login.status_code == 200, face_login.text
    face_token = face_login.json()["session_token"]
    assert client.post(
        "/api/v1/auth/session",
        headers={"Authorization": f"Bearer {face_token}"},
    ).status_code == 200

    deleted = client.delete(
        f"/api/v1/households/{household}/face-credentials/{credential.json()['id']}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["status"] == "DELETED"

    # The session issued from the deleted credential must stop working now.
    assert client.post(
        "/api/v1/auth/session",
        headers={"Authorization": f"Bearer {face_token}"},
    ).status_code == 401
    # The owner's password session (no household scope) is unaffected.
    assert client.post(
        "/api/v1/auth/session",
        headers={"Authorization": f"Bearer {owner_token}"},
    ).status_code == 200


def test_face_registration_verifies_confirmation_before_processing_frames(
    client: TestClient,
) -> None:
    owner = "hct425-oracle-owner"
    password = "hct425-oracle-owner-pass"
    client.post("/api/v1/auth/register", json={"actor_id": owner, "password": password})
    owner_token = client.post(
        "/api/v1/auth/login",
        json={"actor_id": owner, "password": password},
    ).json()["session_token"]
    household = client.post(
        "/api/v1/households",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"name": "先确认后处理"},
    ).json()["id"]

    files = [
        ("frames", (f"oracle-frame-{index}.jpg", b"\xff\xd8\xffnot-a-real-face", "image/jpeg"))
        for index in range(1, 3)
    ]
    rejected = client.post(
        f"/api/v1/households/{household}/face-credentials",
        headers={"Authorization": f"Bearer {owner_token}"},
        data={
            "consent": "true",
            "confirmation_method": "password",
            "confirmation_code": "wrong-password-guess",
        },
        files=files,
    )

    # Without a valid second factor the endpoint must not act as a face
    # quality/liveness oracle: the failure is the confirmation, never a
    # FACE_* frame-processing detail.
    assert rejected.status_code == 403
    assert rejected.json()["detail"] == "CONFIRMATION_FAILED"


def test_face_registration_still_rejects_truly_low_quality_frames(
    client: TestClient,
    monkeypatch,
) -> None:
    """The face gate keeps rejecting tiny frames as FACE_FRAME_LOW_QUALITY."""
    owner = "hct424-lowq-owner"
    password = "hct424-lowq-owner-pass"
    client.post("/api/v1/auth/register", json={"actor_id": owner, "password": password})
    owner_token = client.post(
        "/api/v1/auth/login",
        json={"actor_id": owner, "password": password},
    ).json()["session_token"]
    household = client.post(
        "/api/v1/households",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"name": "低质量帧拒绝"},
    ).json()["id"]

    # Extraction must never be reached when the frame gate rejects first.
    monkeypatch.setattr(
        routes,
        "extract_face_template",
        lambda _data, **_kwargs: (_ for _ in ()).throw(AssertionError("gate must reject first")),
    )

    rejected = client.post(
        f"/api/v1/households/{household}/face-credentials",
        headers={"Authorization": f"Bearer {owner_token}"},
        data={
            "consent": "true",
            "confirmation_method": "password",
            "confirmation_code": password,
        },
        files=_webcam_frames("tiny-frame", width=320, height=240),
    )

    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["detail"] == "FACE_FRAME_LOW_QUALITY"


def test_family_face_login_rejects_an_ambiguous_member_match(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    owner = "hct425-ambiguous-owner"
    household = client.post(
        "/api/v1/households",
        headers={"X-Actor-Id": owner},
        json={"name": "家庭内模糊匹配"},
    ).json()["id"]
    members = [
        client.post(
            f"/api/v1/households/{household}/members",
            headers={"X-Actor-Id": owner},
            json={"display_name": name, "actor_id": actor_id},
        ).json()
        for name, actor_id in (
            ("爷爷", "hct425-ambiguous-grandpa"),
            ("奶奶", "hct425-ambiguous-grandma"),
        )
    ]

    template = b"\x00\x00\x80\x3f" * 128
    now = datetime.now(UTC)
    db_session.add_all(
        [
            FaceCredential(
                household_id=household,
                actor_id=member["actor_id"],
                encrypted_template=encrypt_template(template),
                algorithm_version="opencv-yunet-sface-v3",
                feature_version="face-embedding-sface-v3",
                credential_version=1,
                consent_version="face-registration-consent-v1",
                status="ACTIVE",
                created_by=owner,
                consented_at=now,
            )
            for member in members
        ]
    )
    db_session.commit()

    monkeypatch.setattr(
        routes,
        "extract_face_template",
        lambda _data, **_kwargs: (template, {}))
    monkeypatch.setattr(routes, "check_face_liveness", lambda *_args, **_kwargs: None)

    challenge = client.post(
        "/api/v1/auth/family-face-challenge",
        json={"household_id": household},
    )
    files = _webcam_frames("ambiguous-frame")
    rejected = client.post(
        "/api/v1/auth/family-face-login",
        data={
            "household_id": household,
            "challenge_id": challenge.json()["challenge_id"],
        },
        files=files,
    )

    assert rejected.status_code == 401
    assert rejected.json()["detail"] == "FACE_AUTH_FAILED"
