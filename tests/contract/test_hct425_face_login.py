from fastapi.testclient import TestClient


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
