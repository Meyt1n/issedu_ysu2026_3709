"""HCT-427 契约测试：二次确认与会话续验的 HTTP 边界。

重点保证三件事：
1. 一次性口令与会话 token 只走请求体，query 参数形态被拒绝（否则会落进访问日志）；
2. challenge 响应不含任何秘密，且绑定发起它的登录会话与动作；
3. 会话续验端点存在，并在登出/撤销后立即返回 401。
"""

from fastapi.testclient import TestClient

ACTOR = "hct427-owner"
PASSWORD = "hct427-strong-pass"
PIN = "135790"
ACTION = "confirm_high_risk"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Access-Purpose": "family-care"}


def _sign_in(client: TestClient, actor: str = ACTOR, password: str = PASSWORD) -> str:
    client.post("/api/v1/auth/register", json={"actor_id": actor, "password": password})
    resp = client.post(
        "/api/v1/auth/login",
        json={"actor_id": actor, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["session_token"]


def _household_with_pin(client: TestClient, token: str, name: str = "HCT-427 家庭") -> str:
    created = client.post("/api/v1/households", headers=_bearer(token), json={"name": name})
    assert created.status_code == 201, created.text
    household_id = created.json()["id"]
    configured = client.post(
        "/api/v1/auth/pin",
        headers=_bearer(token),
        json={"household_id": household_id, "pin": PIN},
    )
    assert configured.status_code == 200, configured.text
    return household_id


def _open_challenge(
    client: TestClient,
    token: str,
    household_id: str,
    action: str = ACTION,
) -> str:
    """PIN 归属按家庭划分，因此这里总是显式指定家庭，避免多家庭时的歧义分支。"""
    resp = client.post(
        "/api/v1/auth/pin-challenge",
        headers=_bearer(token),
        json={"action": action, "household_id": household_id},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["challenge_id"]


# ── 会话续验 ────────────────────────────────────────────

def test_session_endpoint_reports_the_live_session(client: TestClient) -> None:
    token = _sign_in(client)
    resp = client.post("/api/v1/auth/session", headers=_bearer(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["actor_id"] == ACTOR
    assert body["expires_at"] > 0
    # 续验响应不得回传任何凭据。
    assert "session_token" not in body


def test_session_endpoint_rejects_logged_out_token(client: TestClient) -> None:
    token = _sign_in(client)
    assert client.post("/api/v1/auth/logout", json={"session_token": token}).status_code == 200
    assert client.post("/api/v1/auth/session", headers=_bearer(token)).status_code == 401


def test_session_endpoint_requires_a_real_session(client: TestClient) -> None:
    # 开发期 X-Actor-Id 不能用于会话续验。
    assert client.post("/api/v1/auth/session", headers={"X-Actor-Id": ACTOR}).status_code == 401
    assert client.post("/api/v1/auth/session").status_code == 401


# ── 二次确认 ────────────────────────────────────────────

def test_challenge_response_carries_no_secret(client: TestClient) -> None:
    token = _sign_in(client)
    household_id = _household_with_pin(client, token)

    resp = client.post(
        "/api/v1/auth/pin-challenge",
        headers=_bearer(token),
        json={"action": ACTION, "method": "pin", "household_id": household_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"challenge_id", "action", "household_id", "expires_at"}
    assert body["action"] == ACTION
    assert body["household_id"] == household_id
    assert PIN not in resp.text


def test_challenge_resolves_the_only_household_with_a_pin(client: TestClient) -> None:
    """单家庭部署下客户端不必知道 household_id，服务端自行解析。"""
    token = _sign_in(client, actor="hct427-solo", password="hct427-solo-pass")
    household_id = _household_with_pin(client, token, name="唯一家庭")
    resp = client.post(
        "/api/v1/auth/pin-challenge",
        headers=_bearer(token),
        json={"action": ACTION},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["household_id"] == household_id


def test_step_up_round_trip_and_replay(client: TestClient) -> None:
    token = _sign_in(client)
    household_id = _household_with_pin(client, token)
    challenge_id = _open_challenge(client, token, household_id)

    confirmed = client.post(
        "/api/v1/auth/pin-verify",
        headers=_bearer(token),
        json={"challenge_id": challenge_id, "action": ACTION, "code": PIN},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["challenge_id"] == challenge_id
    # MOB-133 的移动端适配器以 status=="confirmed" 判定通过，契约需保持兼容。
    assert confirmed.json()["status"] == "confirmed"

    replayed = client.post(
        "/api/v1/auth/pin-verify",
        headers=_bearer(token),
        json={"challenge_id": challenge_id, "action": ACTION, "code": PIN},
    )
    assert replayed.status_code == 409
    assert replayed.json()["detail"] == "STEP_UP_REPLAY"


def test_pin_verify_refuses_query_parameters(client: TestClient) -> None:
    """回归防护：凭据一旦能走 query，就会出现在访问日志和浏览器历史里。"""
    token = _sign_in(client)
    _household_with_pin(client, token)
    resp = client.post(
        f"/api/v1/auth/pin-verify?pin={PIN}&action={ACTION}&session_token={token}",
        headers=_bearer(token),
    )
    assert resp.status_code == 422


def test_step_up_rejects_foreign_session_and_wrong_action(client: TestClient) -> None:
    token = _sign_in(client)
    household_id = _household_with_pin(client, token)
    challenge_id = _open_challenge(client, token, household_id)

    other = _sign_in(client, actor="hct427-other", password="hct427-other-pass")
    foreign = client.post(
        "/api/v1/auth/pin-verify",
        headers=_bearer(other),
        json={"challenge_id": challenge_id, "action": ACTION, "code": PIN},
    )
    assert foreign.status_code == 403
    assert foreign.json()["detail"] == "STEP_UP_FAILED"

    mismatched = client.post(
        "/api/v1/auth/pin-verify",
        headers=_bearer(token),
        json={"challenge_id": challenge_id, "action": "delete_record", "code": PIN},
    )
    assert mismatched.status_code == 403
    assert mismatched.json()["detail"] == "STEP_UP_FAILED"


def test_step_up_requires_a_real_session(client: TestClient) -> None:
    assert client.post(
        "/api/v1/auth/pin-challenge",
        headers={"X-Actor-Id": ACTOR},
        json={"action": ACTION},
    ).status_code == 401


def test_challenge_rejects_a_household_the_actor_does_not_belong_to(client: TestClient) -> None:
    token = _sign_in(client)
    _household_with_pin(client, token)
    outsider = _sign_in(client, actor="hct427-outsider", password="hct427-outsider-pass")
    foreign_household = _household_with_pin(client, token, name="别人家的家庭")

    resp = client.post(
        "/api/v1/auth/pin-challenge",
        headers=_bearer(outsider),
        json={"action": ACTION, "household_id": foreign_household},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "RESOURCE_NOT_FOUND"


def test_challenge_rejects_invalid_action_code(client: TestClient) -> None:
    token = _sign_in(client)
    _household_with_pin(client, token)
    resp = client.post(
        "/api/v1/auth/pin-challenge",
        headers=_bearer(token),
        json={"action": "Delete Record; DROP TABLE"},
    )
    assert resp.status_code == 422


def test_pin_verify_rejects_malformed_code(client: TestClient) -> None:
    token = _sign_in(client)
    household_id = _household_with_pin(client, token)
    challenge_id = _open_challenge(client, token, household_id)

    resp = client.post(
        "/api/v1/auth/pin-verify",
        headers=_bearer(token),
        json={"challenge_id": challenge_id, "action": ACTION, "code": "12345"},
    )
    assert resp.status_code == 422
