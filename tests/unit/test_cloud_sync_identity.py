"""Tests for PR-to-cloud-token identity resolution."""

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

    with pytest.raises(IDENTITY.IdentityError, match="提交账号不一致"):
        IDENTITY.resolve_identity("Shen-huang-123", commits)


def test_rejects_unlinked_commit_with_unknown_email() -> None:
    with pytest.raises(IDENTITY.IdentityError, match="提交账号不一致"):
        IDENTITY.resolve_identity(
            "Shen-huang-123",
            [commit(login=None, name="zhang", email="other@example.com")],
        )


def test_excludes_commit_already_present_on_internal_master() -> None:
    commits = [
        commit(
            login="jin-123-zip",
            name="jin-123-zip",
            email="3487355487@qq.com",
            sha="already-present",
        ),
        commit(
            login="Shen-huang-123",
            name="zhang",
            email="z85963541@qq.com",
            sha="new-reconciliation",
        ),
    ]

    filtered, excluded_count = IDENTITY.filter_already_present_commits(
        commits,
        lambda sha: sha == "already-present",
    )
    result = IDENTITY.resolve_identity("Shen-huang-123", filtered)

    assert excluded_count == 1
    assert result["commit_count"] == 1
    assert result["token_env"] == "CLOUD_TOKEN_SHEN_HUANG_123"


def test_rejects_pr_when_every_commit_is_already_present() -> None:
    commits = [
        commit(
            login="jin-123-zip",
            name="jin-123-zip",
            email="3487355487@qq.com",
            sha="already-present",
        )
    ]

    filtered, excluded_count = IDENTITY.filter_already_present_commits(
        commits,
        lambda _sha: True,
    )

    assert excluded_count == 1
    with pytest.raises(IDENTITY.IdentityError, match="没有可核对的提交"):
        IDENTITY.resolve_identity("Shen-huang-123", filtered)
