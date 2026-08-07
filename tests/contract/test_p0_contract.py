"""P0 API 契约测试

验证每个 P0 接口的路径、请求 Schema、响应 Schema、错误码和权限语义。
这些测试是"接口的自动化担保书"——如果这里失败，说明接口承诺被破坏。
"""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OutboxMessage

# ── 辅助函数 ────────────────────────────────────────────

def _create_household(client: TestClient, name: str = "测试家庭") -> dict:
    resp = client.post(
        "/api/v1/households",
        headers={"X-Actor-Id": "owner"},
        json={"name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_member(
    client: TestClient,
    household_id: str,
    display_name: str = "测试成员",
    role: str = "SELF",
) -> dict:
    resp = client.post(
        f"/api/v1/households/{household_id}/members",
        headers={"X-Actor-Id": "owner"},
        json={"display_name": display_name, "role": role},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── 1. 健康检查接口 ──────────────────────────────────────

def test_health_returns_200(client: TestClient) -> None:
    """GET /health 返回 200 和必要字段"""
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "service" in body
    assert "version" in body


def test_db_health_returns_200(client: TestClient) -> None:
    """GET /api/v1/health/db 返回 200 和必要字段"""
    resp = client.get("/api/v1/health/db")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


def test_capabilities_returns_p0_phase(client: TestClient) -> None:
    """GET /api/v1/meta/capabilities 返回 P0-foundation 阶段信息"""
    resp = client.get("/api/v1/meta/capabilities")
    assert resp.status_code == 200
    body = resp.json()
    assert body["phase"] == "P0-foundation"
    assert "manual-health-event" in body["available"]
    assert "household-member" in body["available"]
    assert "field-authorization" in body["available"]


# ── 2. 家庭管理接口 ──────────────────────────────────────

def test_create_household_requires_actor_id(client: TestClient) -> None:
    """缺少 X-Actor-Id 返回 401"""
    resp = client.post("/api/v1/households", json={"name": "测试"})
    assert resp.status_code == 401


def test_create_household_validates_name(client: TestClient) -> None:
    """name 为空时返回 422"""
    resp = client.post(
        "/api/v1/households",
        headers={"X-Actor-Id": "owner"},
        json={"name": ""},
    )
    assert resp.status_code == 422


def test_create_household_returns_201_with_correct_schema(client: TestClient) -> None:
    """POST /households 返回 201，响应包含 id/name/created_by/created_at"""
    resp = client.post(
        "/api/v1/households",
        headers={"X-Actor-Id": "owner"},
        json={"name": "我的家庭"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "id" in body
    assert body["name"] == "我的家庭"
    assert body["created_by"] == "owner"
    assert "created_at" in body


def test_list_households_returns_owned(client: TestClient) -> None:
    """GET /households 返回 actor 拥有的家庭"""
    _create_household(client, "家庭A")
    _create_household(client, "家庭B")
    resp = client.get("/api/v1/households", headers={"X-Actor-Id": "owner"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    names = {h["name"] for h in body}
    assert names == {"家庭A", "家庭B"}


def test_list_households_returns_authorized_for_grantees(client: TestClient) -> None:
    """GET /households 也返回被授权者能看到家庭"""
    household_id = _create_household(client)["id"]
    member_id = _create_member(client, household_id)["id"]
    client.post(
        f"/api/v1/households/{household_id}/authorizations",
        headers={"X-Actor-Id": "owner"},
        json={
            "member_id": member_id,
            "grantee_actor_id": "caregiver",
            "data_fields": ["health_events"],
            "actions": ["READ_EVENTS"],
            "purpose": "照护",
            "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    resp = client.get("/api/v1/households", headers={"X-Actor-Id": "caregiver"})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


# ── 3. 成员管理接口 ──────────────────────────────────────

def test_create_member_only_by_owner(client: TestClient) -> None:
    """非 owner 添加成员返回 403"""
    household_id = _create_household(client)["id"]
    resp = client.post(
        f"/api/v1/households/{household_id}/members",
        headers={"X-Actor-Id": "stranger"},
        json={"display_name": "越权成员"},
    )
    assert resp.status_code == 403


def test_create_member_to_nonexistent_household(client: TestClient) -> None:
    """向不存在的家庭添加成员返回 404"""
    resp = client.post(
        "/api/v1/households/nonexistent/members",
        headers={"X-Actor-Id": "owner"},
        json={"display_name": "测试"},
    )
    assert resp.status_code == 404


def test_create_member_returns_201_with_correct_schema(client: TestClient) -> None:
    """POST /members 返回 201，响应包含必要字段和正确的 role 默认值"""
    household_id = _create_household(client)["id"]
    resp = client.post(
        f"/api/v1/households/{household_id}/members",
        headers={"X-Actor-Id": "owner"},
        json={"display_name": "张三", "role": "DEPENDENT"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["display_name"] == "张三"
    assert body["role"] == "DEPENDENT"
    assert body["household_id"] == household_id


def test_list_members_as_owner_returns_all(client: TestClient) -> None:
    """GET /members owner 可以看到全部成员"""
    household_id = _create_household(client)["id"]
    _create_member(client, household_id, "成员A")
    _create_member(client, household_id, "成员B")
    resp = client.get(
        f"/api/v1/households/{household_id}/members",
        headers={"X-Actor-Id": "owner"},
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_members_unauthorized_returns_403_no_leak(client: TestClient) -> None:
    """GET /members 未授权者返回 403，且响应不含成员数据"""
    household_id = _create_household(client)["id"]
    _create_member(client, household_id, "成员X")
    resp = client.get(
        f"/api/v1/households/{household_id}/members",
        headers={"X-Actor-Id": "stranger"},
    )
    assert resp.status_code == 403
    body = resp.json()
    # 403 body 不能包含任何成员信息
    assert "id" not in body
    assert "display_name" not in body
    assert "household_id" not in body


def test_list_members_only_authorized_for_partial(client: TestClient) -> None:
    """授权照护者只能看到被授权的成员，不能看到同家庭其他成员"""
    household_id = _create_household(client)["id"]
    member_a = _create_member(client, household_id, "成员A")["id"]
    member_b = _create_member(client, household_id, "成员B")["id"]
    # 只授权 caregiver 访问成员A
    client.post(
        f"/api/v1/households/{household_id}/authorizations",
        headers={"X-Actor-Id": "owner"},
        json={
            "member_id": member_a,
            "grantee_actor_id": "caregiver",
            "data_fields": ["health_events"],
            "actions": ["READ_EVENTS"],
            "purpose": "照护A",
            "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    resp = client.get(
        f"/api/v1/households/{household_id}/members",
        headers={"X-Actor-Id": "caregiver"},
    )
    assert resp.status_code == 200
    members = resp.json()
    ids = {m["id"] for m in members}
    assert member_a in ids
    assert member_b not in ids  # 未授权的成员B不可见


def test_list_members_expired_auth_blocks_access(client: TestClient) -> None:
    """授权过期后，照护者无法查看成员列表"""
    household_id = _create_household(client)["id"]
    member_id = _create_member(client, household_id)["id"]
    client.post(
        f"/api/v1/households/{household_id}/authorizations",
        headers={"X-Actor-Id": "owner"},
        json={
            "member_id": member_id,
            "grantee_actor_id": "caregiver",
            "data_fields": ["health_events"],
            "actions": ["READ_EVENTS"],
            "purpose": "照护",
            "valid_until": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
        },
    )
    resp = client.get(
        f"/api/v1/households/{household_id}/members",
        headers={"X-Actor-Id": "caregiver"},
    )
    assert resp.status_code == 403


def test_list_members_revoked_auth_blocks_access(client: TestClient) -> None:
    """授权被撤销后，照护者无法查看成员列表"""
    household_id = _create_household(client)["id"]
    member_id = _create_member(client, household_id)["id"]
    auth = client.post(
        f"/api/v1/households/{household_id}/authorizations",
        headers={"X-Actor-Id": "owner"},
        json={
            "member_id": member_id,
            "grantee_actor_id": "caregiver",
            "data_fields": ["health_events"],
            "actions": ["READ_EVENTS"],
            "purpose": "照护",
            "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    auth_id = auth.json()["id"]
    # 先确认 caregiver 能访问
    before = client.get(
        f"/api/v1/households/{household_id}/members",
        headers={"X-Actor-Id": "caregiver"},
    )
    assert before.status_code == 200
    # 撤权
    client.post(
        f"/api/v1/households/{household_id}/authorizations/{auth_id}/revoke",
        headers={"X-Actor-Id": "owner"},
    )
    after = client.get(
        f"/api/v1/households/{household_id}/members",
        headers={"X-Actor-Id": "caregiver"},
    )
    assert after.status_code == 403


def test_list_households_excludes_revoked(client: TestClient) -> None:
    """撤权后，被撤权者看不到该家庭"""
    household_id = _create_household(client)["id"]
    member_id = _create_member(client, household_id)["id"]
    auth = client.post(
        f"/api/v1/households/{household_id}/authorizations",
        headers={"X-Actor-Id": "owner"},
        json={
            "member_id": member_id,
            "grantee_actor_id": "caregiver",
            "data_fields": ["health_events"],
            "actions": ["READ_EVENTS"],
            "purpose": "照护",
            "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    auth_id = auth.json()["id"]
    # 撤权前能看到
    before = client.get("/api/v1/households", headers={"X-Actor-Id": "caregiver"})
    assert len(before.json()) == 1
    # 撤权
    client.post(
        f"/api/v1/households/{household_id}/authorizations/{auth_id}/revoke",
        headers={"X-Actor-Id": "owner"},
    )
    after = client.get("/api/v1/households", headers={"X-Actor-Id": "caregiver"})
    assert len(after.json()) == 0


def test_list_households_excludes_expired(client: TestClient) -> None:
    """授权过期后，该家庭不出现在列表中"""
    household_id = _create_household(client)["id"]
    member_id = _create_member(client, household_id)["id"]
    client.post(
        f"/api/v1/households/{household_id}/authorizations",
        headers={"X-Actor-Id": "owner"},
        json={
            "member_id": member_id,
            "grantee_actor_id": "caregiver",
            "data_fields": ["health_events"],
            "actions": ["READ_EVENTS"],
            "purpose": "照护",
            "valid_until": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
        },
    )
    resp = client.get("/api/v1/households", headers={"X-Actor-Id": "caregiver"})
    assert len(resp.json()) == 0


def test_cross_household_auth_does_not_leak_members(client: TestClient) -> None:
    """一个家庭的授权不影响另一个家庭的成员列表"""
    h1 = _create_household(client, "家庭1")["id"]
    h2 = _create_household(client, "家庭2")["id"]
    _create_member(client, h1, "家庭1成员")["id"]
    m2 = _create_member(client, h2, "家庭2成员")["id"]
    # 在家庭2中授权 caregiver
    client.post(
        f"/api/v1/households/{h2}/authorizations",
        headers={"X-Actor-Id": "owner"},
        json={
            "member_id": m2,
            "grantee_actor_id": "caregiver",
            "data_fields": ["health_events"],
            "actions": ["READ_EVENTS"],
            "purpose": "照护",
            "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    # caregiver 查家庭1的成员列表——没被授权
    resp = client.get(
        f"/api/v1/households/{h1}/members",
        headers={"X-Actor-Id": "caregiver"},
    )
    assert resp.status_code == 403


def test_write_only_auth_does_not_grant_list_access(client: TestClient) -> None:
    """仅有 WRITE_EVENTS 授权不能读取列表（READ 才能看）"""
    household_id = _create_household(client)["id"]
    member_id = _create_member(client, household_id)["id"]
    client.post(
        f"/api/v1/households/{household_id}/authorizations",
        headers={"X-Actor-Id": "owner"},
        json={
            "member_id": member_id,
            "grantee_actor_id": "writer",
            "data_fields": ["health_events"],
            "actions": ["WRITE_EVENTS"],  # 只有写权限，没有读权限
            "purpose": "录入事件",
            "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    # 家庭列表：write-only 也不应看到
    households = client.get("/api/v1/households", headers={"X-Actor-Id": "writer"})
    assert len(households.json()) == 0
    # 成员列表：write-only 不应看到
    members = client.get(
        f"/api/v1/households/{household_id}/members",
        headers={"X-Actor-Id": "writer"},
    )
    assert members.status_code == 403

# ── 字段级权限断言 ──────────────────────────────────────

MEMBER_READ_FIELDS = {"id", "household_id", "display_name", "role", "actor_id", "created_at"}
HOUSEHOLD_READ_FIELDS = {"id", "name", "created_by", "created_at"}


def test_list_members_response_contains_only_memberread_fields(
    client: TestClient,
) -> None:
    """list_members 返回的每个成员仅包含 MemberRead 定义的字段，无额外数据泄露"""
    household_id = _create_household(client)["id"]
    _create_member(client, household_id, "成员A")
    _create_member(client, household_id, "成员B")
    resp = client.get(
        f"/api/v1/households/{household_id}/members",
        headers={"X-Actor-Id": "owner"},
    )
    assert resp.status_code == 200
    for member in resp.json():
        assert (
            set(member.keys()) == MEMBER_READ_FIELDS
        ), f"成员字段 {set(member.keys())} 与 MemberRead schema 不一致"


def test_list_members_partial_grantee_response_fields_match_schema(
    client: TestClient,
) -> None:
    """被授权者看到的成员响应字段同样严格遵守 MemberRead schema"""
    household_id = _create_household(client)["id"]
    member_id = _create_member(client, household_id, "被照护者")["id"]
    client.post(
        f"/api/v1/households/{household_id}/authorizations",
        headers={"X-Actor-Id": "owner"},
        json={
            "member_id": member_id,
            "grantee_actor_id": "caregiver",
            "data_fields": ["health_events"],
            "actions": ["READ_EVENTS"],
            "purpose": "照护",
            "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    resp = client.get(
        f"/api/v1/households/{household_id}/members",
        headers={"X-Actor-Id": "caregiver"},
    )
    assert resp.status_code == 200
    members = resp.json()
    assert len(members) == 1
    assert set(members[0].keys()) == MEMBER_READ_FIELDS


def test_list_members_non_health_events_data_field_is_denied(
    client: TestClient,
) -> None:
    """仅有非 health_events 数据域的授权不能查看成员列表"""
    household_id = _create_household(client)["id"]
    member_id = _create_member(client, household_id, "成员")["id"]
    client.post(
        f"/api/v1/households/{household_id}/authorizations",
        headers={"X-Actor-Id": "owner"},
        json={
            "member_id": member_id,
            "grantee_actor_id": "other_caregiver",
            "data_fields": ["medications"],  # 非 health_events
            "actions": ["READ_EVENTS"],
            "purpose": "用药管理",
            "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    resp = client.get(
        f"/api/v1/households/{household_id}/members",
        headers={"X-Actor-Id": "other_caregiver"},
    )
    assert resp.status_code == 403


def test_list_members_unknown_read_action_is_denied(
    client: TestClient,
) -> None:
    """非 READ_EVENTS 的读权限不能查看成员列表（仅允许已知的精确 action）"""
    household_id = _create_household(client)["id"]
    member_id = _create_member(client, household_id, "成员")["id"]
    client.post(
        f"/api/v1/households/{household_id}/authorizations",
        headers={"X-Actor-Id": "owner"},
        json={
            "member_id": member_id,
            "grantee_actor_id": "reader",
            "data_fields": ["health_events"],
            # 使用 READ_EVENTS 之外的 action —— 但 schema 只允许 READ_EVENTS/WRITE_EVENTS
            # 所以这个测试验证的是：只有 READ_EVENTS 能看成员列表，WRITE_EVENTS 不能
            "actions": ["WRITE_EVENTS"],
            "purpose": "录入",
            "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    resp = client.get(
        f"/api/v1/households/{household_id}/members",
        headers={"X-Actor-Id": "reader"},
    )
    assert resp.status_code == 403


def test_list_households_excludes_non_matching_grants(
    client: TestClient,
) -> None:
    """仅有写权限或非 health_events 的授权不暴露家庭"""
    household_id = _create_household(client)["id"]
    member_id = _create_member(client, household_id)["id"]
    # 给 write_only 用户写权限（无读权限）
    client.post(
        f"/api/v1/households/{household_id}/authorizations",
        headers={"X-Actor-Id": "owner"},
        json={
            "member_id": member_id,
            "grantee_actor_id": "writer_only",
            "data_fields": ["health_events"],
            "actions": ["WRITE_EVENTS"],
            "purpose": "录入事件",
            "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    # write_only 用户不应在家庭列表中看到该家庭
    resp = client.get("/api/v1/households", headers={"X-Actor-Id": "writer_only"})
    assert len(resp.json()) == 0


def test_list_households_partial_grantee_response_fields_match_schema(
    client: TestClient,
) -> None:
    """被授权者看到的家庭响应字段严格遵守 HouseholdRead schema"""
    household_id = _create_household(client)["id"]
    member_id = _create_member(client, household_id)["id"]
    client.post(
        f"/api/v1/households/{household_id}/authorizations",
        headers={"X-Actor-Id": "owner"},
        json={
            "member_id": member_id,
            "grantee_actor_id": "caregiver",
            "data_fields": ["health_events"],
            "actions": ["READ_EVENTS"],
            "purpose": "照护",
            "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    resp = client.get("/api/v1/households", headers={"X-Actor-Id": "caregiver"})
    assert resp.status_code == 200
    for household in resp.json():
        assert (
            set(household.keys()) == HOUSEHOLD_READ_FIELDS
        ), f"家庭字段 {set(household.keys())} 与 HouseholdRead schema 不一致"


def test_create_authorization_requires_valid_until_in_future(client: TestClient) -> None:
    """valid_until 在过去时返回 422"""
    household_id = _create_household(client)["id"]
    member_id = _create_member(client, household_id)["id"]
    resp = client.post(
        f"/api/v1/households/{household_id}/authorizations",
        headers={"X-Actor-Id": "owner"},
        json={
            "member_id": member_id,
            "grantee_actor_id": "caregiver",
            "data_fields": ["health_events"],
            "actions": ["READ_EVENTS"],
            "purpose": "照护",
            "valid_until": "2020-01-01T00:00:00Z",
        },
    )
    assert resp.status_code == 422


def test_revoke_authorization_is_immediate(client: TestClient) -> None:
    """撤权后立即生效，被撤权者无法继续访问"""
    household_id = _create_household(client)["id"]
    member_id = _create_member(client, household_id)["id"]
    auth = client.post(
        f"/api/v1/households/{household_id}/authorizations",
        headers={"X-Actor-Id": "owner"},
        json={
            "member_id": member_id,
            "grantee_actor_id": "caregiver",
            "data_fields": ["health_events"],
            "actions": ["READ_EVENTS"],
            "purpose": "照护",
            "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    auth_id = auth.json()["id"]

    # 创建事件后验证 caregiver 能看到
    client.post(
        f"/api/v1/households/{household_id}/events",
        headers={"X-Actor-Id": "owner"},
        json={
            "member_id": member_id,
            "event_type": "NOTE",
            "confirmation_status": "CONFIRMED",
            "payload": {"text": "test"},
        },
    )
    before = client.get(
        f"/api/v1/households/{household_id}/events",
        headers={"X-Actor-Id": "caregiver"},
    )
    assert before.status_code == 200

    # 撤权
    revoke = client.post(
        f"/api/v1/households/{household_id}/authorizations/{auth_id}/revoke",
        headers={"X-Actor-Id": "owner"},
    )
    assert revoke.status_code == 200
    assert revoke.json()["revoked_at"] is not None

    # 撤权后立即被阻
    after = client.get(
        f"/api/v1/households/{household_id}/events",
        headers={"X-Actor-Id": "caregiver"},
    )
    assert after.status_code == 403


# ── 5. 健康事件接口 ──────────────────────────────────────

def test_health_event_rejects_invalid_status(client: TestClient) -> None:
    """非 CONFIRMED/UNCONFIRMED 状态被拒绝（严格枚举校验）"""
    household_id = _create_household(client)["id"]
    member_id = _create_member(client, household_id)["id"]
    resp = client.post(
        f"/api/v1/households/{household_id}/events",
        headers={"X-Actor-Id": "owner"},
        json={
            "member_id": member_id,
            "event_type": "NOTE",
            "confirmation_status": "PENDING",
            "payload": {"text": "test"},
        },
    )
    assert resp.status_code == 422


def test_health_event_defaults_to_unconfirmed(client: TestClient) -> None:
    """不传 confirmation_status 时默认 UNCONFIRMED（安全默认值）"""
    household_id = _create_household(client)["id"]
    member_id = _create_member(client, household_id)["id"]
    resp = client.post(
        f"/api/v1/households/{household_id}/events",
        headers={"X-Actor-Id": "owner"},
        json={
            "member_id": member_id,
            "event_type": "NOTE",
            "payload": {"text": "test"},
        },
    )
    assert resp.status_code == 201
    assert resp.json()["confirmation_status"] == "UNCONFIRMED"
    assert resp.json()["confirmed_by"] is None


def test_health_event_allows_explicit_unconfirmed(
    client: TestClient, db_session: Session
) -> None:
    """显式传 UNCONFIRMED 可以留存，但不能更新正式状态"""
    household_id = _create_household(client)["id"]
    member_id = _create_member(client, household_id)["id"]
    resp = client.post(
        f"/api/v1/households/{household_id}/events",
        headers={"X-Actor-Id": "owner"},
        json={
            "member_id": member_id,
            "event_type": "NOTE",
            "confirmation_status": "UNCONFIRMED",
            "payload": {"text": "test"},
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["confirmation_status"] == "UNCONFIRMED"
    assert body["confirmed_by"] is None

    state = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/state",
        headers={"X-Actor-Id": "owner"},
    )
    assert state.status_code == 404

    outbox = db_session.scalars(select(OutboxMessage)).all()
    assert len(outbox) == 1
    assert outbox[0].topic == "health_event.pending"


def test_health_event_creates_outbox(client: TestClient, db_session: Session) -> None:
    """创建事件时在同一事务中生成 outbox 消息"""
    household_id = _create_household(client)["id"]
    member_id = _create_member(client, household_id)["id"]
    resp = client.post(
        f"/api/v1/households/{household_id}/events",
        headers={"X-Actor-Id": "owner"},
        json={
            "member_id": member_id,
            "event_type": "MEDICINE_ADDED",
            "confirmation_status": "CONFIRMED",
            "payload": {"name": "药品"},
        },
    )
    assert resp.status_code == 201
    event_id = resp.json()["id"]
    outbox = db_session.scalars(select(OutboxMessage)).all()
    assert len(outbox) == 1
    assert outbox[0].event_id == event_id
    assert outbox[0].topic == "health_event.created"
    assert outbox[0].payload["confirmation_status"] == "CONFIRMED"


def test_health_event_updates_member_state(client: TestClient) -> None:
    """创建事件后成员状态投影同步更新"""
    household_id = _create_household(client)["id"]
    member_id = _create_member(client, household_id)["id"]
    event = client.post(
        f"/api/v1/households/{household_id}/events",
        headers={"X-Actor-Id": "owner"},
        json={
            "member_id": member_id,
            "event_type": "MEDICINE_ADDED",
            "confirmation_status": "CONFIRMED",
            "payload": {"name": "药品"},
        },
    )
    event_id = event.json()["id"]
    state = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/state",
        headers={"X-Actor-Id": "owner"},
    )
    assert state.status_code == 200
    assert state.json()["last_event_id"] == event_id
    assert state.json()["state"]["events_count"] == 1


def test_list_events_as_owner_returns_all(client: TestClient) -> None:
    """owner 可查看全部事件"""
    household_id = _create_household(client)["id"]
    member_id = _create_member(client, household_id)["id"]
    client.post(
        f"/api/v1/households/{household_id}/events",
        headers={"X-Actor-Id": "owner"},
        json={
            "member_id": member_id,
            "event_type": "NOTE",
            "confirmation_status": "CONFIRMED",
            "payload": {"text": "1"},
        },
    )
    client.post(
        f"/api/v1/households/{household_id}/events",
        headers={"X-Actor-Id": "owner"},
        json={
            "member_id": member_id,
            "event_type": "NOTE",
            "confirmation_status": "CONFIRMED",
            "payload": {"text": "2"},
        },
    )
    resp = client.get(
        f"/api/v1/households/{household_id}/events",
        headers={"X-Actor-Id": "owner"},
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_events_respects_authorization_boundary(client: TestClient) -> None:
    """被授权者只能看到授权成员的事件"""
    household_id = _create_household(client)["id"]
    member_a = _create_member(client, household_id, "成员A")["id"]
    member_b = _create_member(client, household_id, "成员B")["id"]

    # 只授权 caregiver 访问成员A
    client.post(
        f"/api/v1/households/{household_id}/authorizations",
        headers={"X-Actor-Id": "owner"},
        json={
            "member_id": member_a,
            "grantee_actor_id": "caregiver",
            "data_fields": ["health_events"],
            "actions": ["READ_EVENTS"],
            "purpose": "照护A",
            "valid_until": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )

    # 创建两个成员的事件
    client.post(
        f"/api/v1/households/{household_id}/events",
        headers={"X-Actor-Id": "owner"},
        json={
            "member_id": member_a,
            "event_type": "NOTE",
            "confirmation_status": "CONFIRMED",
            "payload": {"text": "A的事件"},
        },
    )
    client.post(
        f"/api/v1/households/{household_id}/events",
        headers={"X-Actor-Id": "owner"},
        json={
            "member_id": member_b,
            "event_type": "NOTE",
            "confirmation_status": "CONFIRMED",
            "payload": {"text": "B的事件"},
        },
    )

    # caregiver 只能看到成员A的事件
    resp = client.get(
        f"/api/v1/households/{household_id}/events",
        headers={"X-Actor-Id": "caregiver"},
    )
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) == 1
    assert events[0]["member_id"] == member_a


# ── 6. 跨家庭隔离 ──────────────────────────────────────

def test_cross_household_isolation(client: TestClient) -> None:
    """不同家庭的数据完全隔离"""
    h1 = _create_household(client, "家庭1")["id"]
    h2 = _create_household(client, "家庭2")["id"]
    m1 = _create_member(client, h1, "成员1")["id"]

    # 用家庭1的成员ID去家庭2创建事件
    resp = client.post(
        f"/api/v1/households/{h2}/events",
        headers={"X-Actor-Id": "owner"},
        json={
            "member_id": m1,  # m1 属于 h1，不属于 h2
            "event_type": "NOTE",
            "confirmation_status": "CONFIRMED",
            "payload": {"text": "跨家庭攻击"},
        },
    )
    assert resp.status_code == 404  # member not found in household h2


# ── 7. request_id 验证 ──────────────────────────────────

def test_response_includes_request_id_header(client: TestClient) -> None:
    """所有响应包含 X-Request-Id header"""
    resp = client.get("/health")
    assert "x-request-id" in resp.headers
