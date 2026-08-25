"""安全审计回归测试（八大注意点专项加固）。

覆盖本次防御性审计修复的四类问题：

1. 模型版本绑定治理端点（发布/回滚/读取）必须携带身份，回滚必须归因真实操作者；
2. 文件下载/删除按上传者与视觉任务授权范围收口（IDOR / 越权删除）；
3. 上传边界值：空文件（0KB）拒绝；路径遏制使用严格包含判断，兄弟目录前缀不能逃逸；
4. 认证输入：注册 actor_id 与开发身份头必须符合受控字符集（日志注入 / STRIDE S-01）。

绑定 Story：HCT-102（授权）、HCT-104（安全上传）、HCT-004（威胁基线）、HCT-404（模型发布）。
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import get_settings
from app.file_upload import delete_file_tree, file_owner, store_file, validate_size
from app.models import VisionTask

OWNER = {"X-Actor-Id": "audit-owner"}
MEMBER = {"X-Actor-Id": "audit-member"}
STRANGER = {"X-Actor-Id": "audit-stranger"}

JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x00synthetic-jpeg-body"


def _upload_jpeg(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post(
        "/api/v1/files/upload",
        headers=headers,
        files={"file": ("evidence.jpg", io.BytesIO(JPEG_BYTES), "image/jpeg")},
    )
    assert response.status_code == 201, response.text
    return response.json()["storage_key"]


@pytest.fixture()
def file_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(get_settings(), "file_root", str(tmp_path))
    return tmp_path


# ── 1. 模型版本绑定治理端点 ────────────────────────────────────────────


def _create_binding(client: TestClient) -> str:
    response = client.post(
        "/api/v1/model-version-bindings",
        headers=OWNER,
        json={
            "model_id": "audit-model-v1",
            "dataset_version": "ds-v1",
            "fixed_set_hash": "abc",
            "comparison_report_hash": "report-v1",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_model_binding_governance_requires_identity(client: TestClient) -> None:
    binding_id = _create_binding(client)

    unauthenticated = [
        client.get("/api/v1/model-version-bindings"),
        client.get(f"/api/v1/model-version-bindings/{binding_id}"),
        client.get(f"/api/v1/model-version-bindings/{binding_id}/comparison"),
        client.post(
            f"/api/v1/model-version-bindings/{binding_id}/activate",
            json={"approved_by": "anyone"},
        ),
        client.post(
            f"/api/v1/model-version-bindings/{binding_id}/rollback",
            json={"reason": "no identity"},
        ),
    ]
    for response in unauthenticated:
        assert response.status_code == 401, response.text

    # 绑定仍是 inactive：匿名激活/回滚都没有生效。
    state = client.get(f"/api/v1/model-version-bindings/{binding_id}", headers=OWNER)
    assert state.status_code == 200
    assert state.json()["release_status"] == "inactive"


def test_model_binding_rollback_attributes_real_actor(client: TestClient) -> None:
    binding_id = _create_binding(client)
    activated = client.post(
        f"/api/v1/model-version-bindings/{binding_id}/activate",
        headers=OWNER,
        json={"approved_by": "independent-reviewer"},
    )
    assert activated.status_code == 200, activated.text

    rolled_back = client.post(
        f"/api/v1/model-version-bindings/{binding_id}/rollback",
        headers={"X-Actor-Id": "release-admin"},
        json={"reason": "audit drill"},
    )
    assert rolled_back.status_code == 200, rolled_back.text
    body = rolled_back.json()
    assert body["release_status"] == "revoked"
    # 回滚不再硬编码为 "admin"，必须归因到真实认证身份。
    assert body["revoked_by"] == "release-admin"


# ── 2. 文件所有权与越权访问 ───────────────────────────────────────────


def test_upload_records_owner_and_blocks_cross_actor_delete(
    client: TestClient, file_root: Path
) -> None:
    storage_key = _upload_jpeg(client, OWNER)
    assert file_owner(storage_key) == "audit-owner"

    stolen_delete = client.delete(f"/api/v1/files/{storage_key}", headers=STRANGER)
    assert stolen_delete.status_code == 404
    assert (file_root / storage_key).exists()

    owner_delete = client.delete(f"/api/v1/files/{storage_key}", headers=OWNER)
    assert owner_delete.status_code == 200
    assert not (file_root / storage_key).exists()
    assert file_owner(storage_key) is None


def test_unlinked_file_download_is_uploader_scoped(
    client: TestClient, file_root: Path
) -> None:
    storage_key = _upload_jpeg(client, OWNER)

    assert client.get(f"/api/v1/files/{storage_key}", headers=OWNER).status_code == 200
    assert client.get(f"/api/v1/files/{storage_key}", headers=STRANGER).status_code == 404


def test_household_owner_reads_member_evidence_via_vision_task(
    client: TestClient, file_root: Path, db_session: Session
) -> None:
    household = client.post(
        "/api/v1/households", headers=OWNER, json={"name": "Audit household"}
    )
    assert household.status_code == 201
    household_id = household.json()["id"]
    member = client.post(
        f"/api/v1/households/{household_id}/members",
        headers=OWNER,
        json={"display_name": "Member", "role": "SELF", "actor_id": "audit-member"},
    )
    assert member.status_code == 201
    member_id = member.json()["id"]

    storage_key = _upload_jpeg(client, MEMBER)
    db_session.add(
        VisionTask(
            household_id=household_id,
            member_id=member_id,
            file_id=storage_key,
            task_type="ocr",
            status="queued",
            created_by="audit-member",
        )
    )
    db_session.commit()

    # 复核流：家庭 owner 可以查看成员提交的证据原图。
    assert client.get(f"/api/v1/files/{storage_key}", headers=OWNER).status_code == 200
    # 未授权外人仍然不可见，也不能替成员删除。
    assert client.get(f"/api/v1/files/{storage_key}", headers=STRANGER).status_code == 404
    assert client.delete(f"/api/v1/files/{storage_key}", headers=OWNER).status_code == 404
    assert (file_root / storage_key).exists()


def test_legacy_file_without_owner_metadata_keeps_working(
    client: TestClient, file_root: Path
) -> None:
    (file_root / "legacy-object.bin").write_bytes(b"legacy-bytes")
    response = client.get("/api/v1/files/legacy-object.bin", headers=OWNER)
    assert response.status_code == 200


# ── 3. 上传边界值与路径遏制 ───────────────────────────────────────────


def test_empty_upload_rejected(client: TestClient, file_root: Path) -> None:
    response = client.post(
        "/api/v1/files/upload",
        headers=OWNER,
        files={"file": ("empty.jpg", io.BytesIO(b""), "image/jpeg")},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "UPLOAD_EMPTY"


def test_validate_size_rejects_zero_bytes() -> None:
    with pytest.raises(HTTPException) as exc:
        validate_size(io.BytesIO(b""), max_bytes=1024)
    assert exc.value.detail == "UPLOAD_EMPTY"


def test_sibling_directory_prefix_cannot_escape_containment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "files"
    root.mkdir()
    monkeypatch.setattr(get_settings(), "file_root", str(root))

    sibling = tmp_path / "files-evil"
    sibling.mkdir()
    victim = sibling / "victim.bin"
    victim.write_bytes(b"do-not-delete")

    # "../files-evil/victim.bin" 解析后以 "<root>-evil" 开头：字符串前缀判断会误放行。
    deleted = delete_file_tree("../files-evil/victim.bin")
    assert deleted == []
    assert victim.exists()

    with pytest.raises(HTTPException) as exc:
        store_file(io.BytesIO(b"x"), "../files-evil/planted.bin")
    assert exc.value.detail == "UPLOAD_PATH_TRAVERSAL"
    assert not (sibling / "planted.bin").exists()


@pytest.mark.anyio
async def test_validate_and_store_records_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.file_upload import validate_and_store

    settings = get_settings()
    monkeypatch.setattr(settings, "file_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_allowed_extensions", ".jpg")
    upload = UploadFile(
        filename="owned.jpg", file=io.BytesIO(JPEG_BYTES), size=len(JPEG_BYTES)
    )
    result = await validate_and_store(upload, owner="unit-owner")
    assert file_owner(result["storage_key"]) == "unit-owner"


# ── 4. 认证输入字符集 ────────────────────────────────────────────────


def test_register_rejects_malformed_actor_ids(client: TestClient) -> None:
    for bad_actor in ("actor with spaces", "../../etc/passwd", ".hidden", "名字"):
        response = client.post(
            "/api/v1/auth/register",
            json={"actor_id": bad_actor, "password": "long-enough-password"},
        )
        assert response.status_code == 422, (bad_actor, response.text)


def test_dev_actor_header_rejects_malformed_identity(client: TestClient) -> None:
    response = client.get(
        "/api/v1/households", headers={"X-Actor-Id": "actor with spaces"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "ACTOR_ID_INVALID"

    well_formed = client.get("/api/v1/households", headers={"X-Actor-Id": "actor-ok.1"})
    assert well_formed.status_code == 200
