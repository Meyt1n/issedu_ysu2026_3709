from datetime import UTC, datetime

from ai.vision import quality_gate
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import routes
from app.face_credentials import encrypt_template
from app.models import FaceCredential


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
    for _ in range(6):
        challenge = client.post(
            "/api/v1/auth/face-challenge",
            json={"household_id": household_id, "actor_id": actor_id},
        ).json()
        responses.append(
            client.post(
                "/api/v1/auth/face-login",
                data={
                    "household_id": household_id,
                    "actor_id": actor_id,
                    "challenge_id": challenge["challenge_id"],
                },
                files=files,
            )
        )

    assert [response.status_code for response in responses[:5]] == [401] * 5
    assert responses[5].status_code == 429


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

    template = b"\x00\x00\x80\x3f" * (64 * 64)
    monkeypatch.setattr(quality_gate, "decode_image", lambda _data: object())
    monkeypatch.setattr(
        quality_gate,
        "assess_image",
        lambda *_args, **_kwargs: {"allow_downstream": True},
    )
    monkeypatch.setattr(
        routes,
        "extract_face_template",
        lambda _data: (
            template,
            {
                "algorithm_version": "opencv-haar-grayscale-v2",
                "feature_version": "face-template-v2",
            },
        ),
    )
    monkeypatch.setattr(routes, "check_face_liveness", lambda _templates: None)

    files = [
        ("frames", (f"frame-{index}.jpg", b"\xff\xd8\xffdemo", "image/jpeg"))
        for index in range(1, 4)
    ]
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
    assert registered.json()["algorithm_version"] == "opencv-haar-grayscale-v2"

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

    negative_template = b"\x00\x00\x80\xbf" * (64 * 64)
    positive_template = b"\x00\x00\x80\x3f" * (64 * 64)
    now = datetime.now(UTC)
    db_session.add_all(
        [
            FaceCredential(
                household_id=household,
                actor_id=grandpa["actor_id"],
                encrypted_template=encrypt_template(negative_template),
                algorithm_version="opencv-haar-grayscale-v2",
                feature_version="face-template-v2",
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
                algorithm_version="opencv-haar-grayscale-v2",
                feature_version="face-template-v2",
                credential_version=1,
                consent_version="face-registration-consent-v1",
                status="ACTIVE",
                created_by=owner,
                consented_at=now,
            ),
        ]
    )
    db_session.commit()

    monkeypatch.setattr(quality_gate, "decode_image", lambda _data: object())
    monkeypatch.setattr(
        quality_gate,
        "assess_image",
        lambda *_args, **_kwargs: {"allow_downstream": True},
    )
    monkeypatch.setattr(routes, "extract_face_template", lambda _data: (positive_template, {}))
    monkeypatch.setattr(routes, "check_face_liveness", lambda _templates: None)

    challenge = client.post(
        "/api/v1/auth/family-face-challenge",
        json={"household_id": household},
    )
    assert challenge.status_code == 200, challenge.text
    files = [
        ("frames", (f"family-frame-{index}.jpg", b"\xff\xd8\xffdemo", "image/jpeg"))
        for index in range(1, 4)
    ]
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

    template = b"\x00\x00\x80\x3f" * (64 * 64)
    now = datetime.now(UTC)
    db_session.add_all(
        [
            FaceCredential(
                household_id=household,
                actor_id=member["actor_id"],
                encrypted_template=encrypt_template(template),
                algorithm_version="opencv-haar-grayscale-v2",
                feature_version="face-template-v2",
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

    monkeypatch.setattr(quality_gate, "decode_image", lambda _data: object())
    monkeypatch.setattr(
        quality_gate,
        "assess_image",
        lambda *_args, **_kwargs: {"allow_downstream": True},
    )
    monkeypatch.setattr(routes, "extract_face_template", lambda _data: (template, {}))
    monkeypatch.setattr(routes, "check_face_liveness", lambda _templates: None)

    challenge = client.post(
        "/api/v1/auth/family-face-challenge",
        json={"household_id": household},
    )
    files = [
        ("frames", (f"ambiguous-frame-{index}.jpg", b"\xff\xd8\xffdemo", "image/jpeg"))
        for index in range(1, 4)
    ]
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
