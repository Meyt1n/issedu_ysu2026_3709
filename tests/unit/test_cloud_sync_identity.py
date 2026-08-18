"""Tests for PR and approved direct-maintenance identity resolution."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "cloud_sync_identity.py"
SPEC = importlib.util.spec_from_file_location("cloud_sync_identity", SCRIPT)
assert SPEC and SPEC.loader
IDENTITY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IDENTITY)


def commit(
    *,
    login: str | None,
    name: str,
    email: str,
    sha: str = "0123456789abcdef",
) -> dict:
    return {
        "sha": sha,
        "author": {"login": login} if login else None,
        "commit": {"author": {"name": name, "email": email}},
    }


def direct_maintenance_commit(
    *,
    author_login: str = "Shen-huang-123",
    committer_login: str = "Shen-huang-123",
    status: str = "added",
    filename: str = "doc/07.会议记录/会议记录_8.18.docx",
) -> dict:
    return {
        "sha": "abcdef0123456789",
        "author": {"login": author_login},
        "committer": {"login": committer_login},
        "parents": [{"sha": "parent"}],
        "commit": {
            "author": {"name": "Wind", "email": "z85963541@qq.com"},
            "committer": {"name": "Wind", "email": "z85963541@qq.com"},
        },
        "files": [{"filename": filename, "status": status}],
    }


def test_resolves_shen_huang_token_when_pr_and_commit_login_match() -> None:
    result = IDENTITY.resolve_identity(
        "Shen-huang-123",
        [commit(login="Shen-huang-123", name="zhang", email="z85963541@qq.com")],
    )

    assert result["token_env"] == "CLOUD_TOKEN_SHEN_HUANG_123"
    assert result["cloud_username"] == "zhang"
    assert result["commit_count"] == 1


def test_accepts_unlinked_commit_only_when_git_email_matches_mapping() -> None:
    result = IDENTITY.resolve_identity(
        "Shen-huang-123",
        [commit(login=None, name="zhang", email="z85963541@qq.com")],
    )

    assert result["github_login"] == "Shen-huang-123"


@pytest.mark.parametrize(
    ("pr_login", "name", "email", "token_env", "cloud_username"),
    [
        ("ry12-20", "ry12-20", "unknown@example.com", "CLOUD_TOKEN_RY12_20", "ry12-20"),
        (
            "389883656-lgtm",
            "389883656-lgtm",
            "389883656@qq.com",
            "CLOUD_TOKEN_389883656_LGTM",
            "yanghuan",
        ),
        (
            "jin-123-zip",
            "jin-123-zip",
            "3487355487@qq.com",
            "CLOUD_TOKEN_JIN_123_ZIP",
            "jin-123-zip",
        ),
    ],
)
def test_resolves_new_contributor_when_linked_github_login_matches(
    pr_login: str,
    name: str,
    email: str,
    token_env: str,
    cloud_username: str,
) -> None:
    result = IDENTITY.resolve_identity(
        pr_login,
        [commit(login=pr_login, name=name, email=email)],
    )

    assert result["token_env"] == token_env
    assert result["cloud_username"] == cloud_username


@pytest.mark.parametrize(
    ("pr_login", "name", "email", "token_env"),
    [
        (
            "389883656-lgtm",
            "389883656-lgtm",
            "389883656@qq.com",
            "CLOUD_TOKEN_389883656_LGTM",
        ),
        (
            "jin-123-zip",
            "jin-123-zip",
            "3487355487@qq.com",
            "CLOUD_TOKEN_JIN_123_ZIP",
        ),
    ],
)
def test_accepts_new_contributor_unlinked_commit_by_registered_email(
    pr_login: str,
    name: str,
    email: str,
    token_env: str,
) -> None:
    result = IDENTITY.resolve_identity(
        pr_login,
        [commit(login=None, name=name, email=email)],
    )

    assert result["token_env"] == token_env


def test_ry12_requires_linked_github_login_until_email_is_registered() -> None:
    with pytest.raises(IDENTITY.IdentityError, match="提交账号不一致"):
        IDENTITY.resolve_identity(
            "ry12-20",
            [commit(login=None, name="ry12-20", email="unknown@example.com")],
        )


def test_resolves_owner_pr_to_owner_credentials() -> None:
    result = IDENTITY.resolve_identity(
        "Meyt1n",
        [commit(login="Meyt1n", name="Meyt1n", email="3214037940@qq.com")],
    )

    assert result["token_env"] == "CLOUD_REPO_PASSWORD"
    assert result["cloud_username_env"] == "CLOUD_REPO_USERNAME"


def test_rejects_unmapped_pr_author_without_fallback() -> None:
    with pytest.raises(IDENTITY.IdentityError, match="禁止回退"):
        IDENTITY.resolve_identity(
            "unknown-user",
            [commit(login="unknown-user", name="unknown", email="unknown@example.com")],
        )


def test_rejects_mixed_pr_commit_accounts() -> None:
    commits = [
        commit(login="Shen-huang-123", name="zhang", email="z85963541@qq.com"),
        commit(
            login="Meyt1n",
            name="Meyt1n",
            email="3214037940@qq.com",
            sha="fedcba9876543210",
        ),
    ]

    with pytest.raises(IDENTITY.IdentityError, match="拆分 PR.*更正提交身份"):
        IDENTITY.resolve_identity("Shen-huang-123", commits)


def test_rejects_unlinked_commit_with_unknown_email() -> None:
    with pytest.raises(IDENTITY.IdentityError, match="提交账号不一致"):
        IDENTITY.resolve_identity(
            "Shen-huang-123",
            [commit(login=None, name="zhang", email="other@example.com")],
        )


def test_resolves_registered_direct_document_commit() -> None:
    result = IDENTITY.resolve_direct_maintenance_identity(direct_maintenance_commit())

    assert result["github_login"] == "Shen-huang-123"
    assert result["token_env"] == "CLOUD_TOKEN_SHEN_HUANG_123"
    assert result["kind"] == "direct-maintenance"


def test_rejects_direct_commit_when_github_author_and_committer_differ() -> None:
    with pytest.raises(IDENTITY.IdentityError, match="author 与 committer 不一致"):
        IDENTITY.resolve_direct_maintenance_identity(
            direct_maintenance_commit(committer_login="Meyt1n")
        )


def test_rejects_direct_commit_with_merge_topology() -> None:
    commit_metadata = direct_maintenance_commit()
    commit_metadata["parents"] = [{"sha": "one"}, {"sha": "two"}]

    with pytest.raises(IDENTITY.IdentityError, match="不是普通单父提交"):
        IDENTITY.resolve_direct_maintenance_identity(commit_metadata)


def test_rejects_direct_commit_outside_document_directories() -> None:
    with pytest.raises(IDENTITY.IdentityError, match="非维护文档路径"):
        IDENTITY.resolve_direct_maintenance_identity(
            direct_maintenance_commit(filename="src/api/app/main.py")
        )


def test_rejects_direct_document_deletion() -> None:
    with pytest.raises(IDENTITY.IdentityError, match="不允许的文件状态"):
        IDENTITY.resolve_direct_maintenance_identity(
            direct_maintenance_commit(status="deleted")
        )


def test_rejects_direct_rename_with_previous_filename() -> None:
    commit_metadata = direct_maintenance_commit(status="renamed")
    commit_metadata["files"][0]["previous_filename"] = "src/api/app/main.py"

    with pytest.raises(IDENTITY.IdentityError, match="rename/copy"):
        IDENTITY.resolve_direct_maintenance_identity(commit_metadata)


def test_rejects_direct_metadata_without_parents() -> None:
    commit_metadata = direct_maintenance_commit()
    del commit_metadata["parents"]

    with pytest.raises(IDENTITY.IdentityError, match="不是普通单父提交"):
        IDENTITY.resolve_direct_maintenance_identity(commit_metadata)
