"""HCT-439 跨角色门户边界契约测试。

成员前台账号（绑定 ``Member.actor_id``）只拥有自己的读取范围和
拍照提交能力；所有管理员后台路由必须对成员保持隐藏式 404，
不能泄露资源是否存在。这里固化「一个家庭、两个门户、一个后端
权限中心」的后端边界。
"""

from fastapi.testclient import TestClient

MEMBER_HEADERS = {"X-Actor-Id": "grandma", "X-Access-Purpose": "family-care"}
OWNER_HEADERS = {"X-Actor-Id": "owner"}


def _household_with_bound_member(client: TestClient) -> tuple[str, dict]:
    resp = client.post(
        "/api/v1/households",
        headers=OWNER_HEADERS,
        json={"name": "门户边界家庭"},
    )
    assert resp.status_code == 201, resp.text
    household_id = resp.json()["id"]
    member = client.post(
        f"/api/v1/households/{household_id}/members",
        headers=OWNER_HEADERS,
        json={"display_name": "奶奶", "role": "DEPENDENT", "actor_id": "grandma"},
    )
    assert member.status_code == 201, member.text
    return household_id, member.json()


def test_member_cannot_access_owner_admin_routes(client: TestClient) -> None:
    """成员访问授权管理、审计和家庭级视觉队列时得到隐藏式 404。"""
    household_id, member = _household_with_bound_member(client)

    owner_routes = [
        ("GET", f"/api/v1/households/{household_id}/authorizations"),
        ("GET", f"/api/v1/households/{household_id}/authorization-audits"),
        ("GET", f"/api/v1/households/{household_id}/authorization-audits/summary"),
        ("GET", f"/api/v1/households/{household_id}/vision-tasks"),
        ("GET", f"/api/v1/households/{household_id}/outbox"),
        ("DELETE", f"/api/v1/households/{household_id}"),
    ]
    for method, path in owner_routes:
        resp = client.request(method, path, headers=MEMBER_HEADERS)
        assert resp.status_code == 404, f"{method} {path} -> {resp.status_code}: {resp.text}"
        assert member["id"] not in resp.text

    # 管理员本人仍可访问，证明 404 来自权限而不是路由缺失。
    owner_ok = client.get(
        f"/api/v1/households/{household_id}/authorizations",
        headers=OWNER_HEADERS,
    )
    assert owner_ok.status_code == 200, owner_ok.text


def test_member_cannot_manage_members_or_read_review_queue(client: TestClient) -> None:
    """成员不能新增成员，也看不到带 OCR 原始候选的复核队列。"""
    household_id, member = _household_with_bound_member(client)

    create_member = client.post(
        f"/api/v1/households/{household_id}/members",
        headers=MEMBER_HEADERS,
        json={"display_name": "陌生成员", "role": "DEPENDENT"},
    )
    assert create_member.status_code == 404

    # 复核队列包含 OCR 原始候选，属于管理员/授权照护者路由；
    # 成员即使查询自己的队列也保持 404，前台只能看确认后的记录。
    review = client.get(
        f"/api/v1/households/{household_id}/members/{member['id']}/review-tasks",
        headers=MEMBER_HEADERS,
    )
    assert review.status_code == 404

    owner_review = client.get(
        f"/api/v1/households/{household_id}/members/{member['id']}/review-tasks",
        headers={**OWNER_HEADERS, "X-Access-Purpose": "family-care"},
    )
    assert owner_review.status_code == 200, owner_review.text


def test_member_vision_capture_is_limited_to_self(client: TestClient) -> None:
    """成员只能给自己创建视觉任务；指向他人时在权限层就被 404。"""
    household_id, member = _household_with_bound_member(client)
    other = client.post(
        f"/api/v1/households/{household_id}/members",
        headers=OWNER_HEADERS,
        json={"display_name": "爷爷", "role": "DEPENDENT", "actor_id": "grandpa"},
    ).json()

    denied = client.post(
        "/api/v1/vision-tasks",
        headers=MEMBER_HEADERS,
        json={"file_id": "missing.jpg", "media_type": "image", "member_id": other["id"]},
    )
    assert denied.status_code == 404
    assert denied.json()["detail"] == "RESOURCE_NOT_FOUND"

    # 指向自己时可以通过权限层，失败点后移到文件校验，
    # 证明 self-member 提交路径是打开的。
    self_scope = client.post(
        "/api/v1/vision-tasks",
        headers=MEMBER_HEADERS,
        json={"file_id": "missing.jpg", "media_type": "image", "member_id": member["id"]},
    )
    assert self_scope.status_code == 404
    assert self_scope.json()["detail"] == "FILE_NOT_FOUND"

    # 成员自己的任务列表是 actor 范围的，看不到别人提交的任务。
    my_tasks = client.get("/api/v1/vision-tasks", headers=MEMBER_HEADERS)
    assert my_tasks.status_code == 200
    assert my_tasks.json() == []


def test_member_cannot_read_other_member_scope(client: TestClient) -> None:
    """成员读取别人时间线/状态时得到隐藏式 404，且响应不泄露数据。"""
    household_id, _member = _household_with_bound_member(client)
    other = client.post(
        f"/api/v1/households/{household_id}/members",
        headers=OWNER_HEADERS,
        json={"display_name": "爷爷", "role": "DEPENDENT", "actor_id": "grandpa"},
    ).json()

    timeline = client.get(
        f"/api/v1/households/{household_id}/members/{other['id']}/timeline",
        headers=MEMBER_HEADERS,
    )
    assert timeline.status_code == 404
    assert "爷爷" not in timeline.text

    state = client.get(
        f"/api/v1/households/{household_id}/members/{other['id']}/state",
        headers=MEMBER_HEADERS,
    )
    assert state.status_code == 404
