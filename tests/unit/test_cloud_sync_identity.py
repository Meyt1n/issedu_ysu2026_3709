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
