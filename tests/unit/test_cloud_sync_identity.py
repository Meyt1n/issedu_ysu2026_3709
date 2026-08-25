"""Tests for PR and approved direct-maintenance identity resolution."""

from __future__ import annotations

import importlib.util
import os
import subprocess
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
    message: str = "",
) -> dict:
    return {
        "sha": sha,
        "author": {"login": login} if login else None,
        "commit": {"author": {"name": name, "email": email}, "message": message},
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
        "files_complete": True,
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


def test_accepts_cursor_agent_commit_with_registered_pr_owner_coauthor() -> None:
    result = IDENTITY.resolve_identity(
        "Meyt1n",
        [
            commit(
                login="cursoragent",
                name="Cursor Agent",
                email="cursoragent@cursor.com",
                message=(
                    "feat: delegated change\n\n"
                    "Co-authored-by: Meyt1n <Meyt1n@users.noreply.github.com>"
                ),
            )
        ],
    )

    assert result["token_env"] == "CLOUD_REPO_PASSWORD"


def test_rejects_cursor_agent_commit_without_registered_coauthor() -> None:
    with pytest.raises(IDENTITY.IdentityError, match="提交账号不一致"):
        IDENTITY.resolve_identity(
            "Meyt1n",
            [
                commit(
                    login="cursoragent",
                    name="Cursor Agent",
                    email="cursoragent@cursor.com",
                    message="feat: delegated change",
                )
            ],
        )


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


def test_rejects_direct_metadata_without_complete_manifest() -> None:
    commit_metadata = direct_maintenance_commit()
    del commit_metadata["files_complete"]

    with pytest.raises(IDENTITY.IdentityError, match="未证明完整"):
        IDENTITY.resolve_direct_maintenance_identity(commit_metadata)


@pytest.mark.parametrize(
    "filename",
    [
        r"docs\\meeting-record.md",
        "docs/../src/api/main.py",
        "docs2/meeting-record.md",
        "docs/meeting-record.md/../secret.txt",
    ],
)
def test_rejects_noncanonical_direct_maintenance_paths(filename: str) -> None:
    with pytest.raises(IDENTITY.IdentityError, match="非维护文档路径"):
        IDENTITY.resolve_direct_maintenance_identity(
            direct_maintenance_commit(filename=filename)
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


def _git(repo: Path, *args: str) -> str:
    process = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Shen-huang-123",
            "GIT_AUTHOR_EMAIL": "z85963541@qq.com",
            "GIT_COMMITTER_NAME": "Shen-huang-123",
            "GIT_COMMITTER_EMAIL": "z85963541@qq.com",
        },
        check=False,
    )
    assert process.returncode == 0, process.stderr
    return process.stdout.strip()


def test_complete_manifest_catches_mixed_change_beyond_api_page_limit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "master")
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "base.txt")
    _git(repo, "commit", "-m", "base")
    parent = _git(repo, "rev-parse", "HEAD")

    for index in range(301):
        path = repo / "docs" / f"record-{index:03d}.md"
        path.parent.mkdir(exist_ok=True)
        path.write_text(f"record {index}\n", encoding="utf-8")
    source_path = repo / "src" / "api" / "unexpected.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("unexpected = True\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "large-direct-maintenance")
    commit_sha = _git(repo, "rev-parse", "HEAD")
    metadata = {
        "sha": commit_sha,
        "author": {"login": "Shen-huang-123"},
        "committer": {"login": "Shen-huang-123"},
        "commit": {
            "author": {"name": "Shen-huang-123", "email": "z85963541@qq.com"},
            "committer": {"name": "Shen-huang-123", "email": "z85963541@qq.com"},
        },
    }

    complete = IDENTITY.build_complete_direct_commit_metadata(
        metadata, repo, commit_sha, parent
    )

    assert complete["files_complete"] is True
    assert complete["file_count"] == 302
    with pytest.raises(IDENTITY.IdentityError, match="非维护文档路径"):
        IDENTITY.resolve_direct_maintenance_identity(complete)
