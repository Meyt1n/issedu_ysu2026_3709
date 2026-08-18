#!/usr/bin/env python3
"""Resolve GitHub PR and approved direct-maintenance identities."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


class IdentityError(ValueError):
    """Raised when a commit or PR cannot be attributed safely."""


IDENTITIES: dict[str, dict[str, Any]] = {
    "meyt1n": {
        "github_login": "Meyt1n",
        "token_env": "CLOUD_REPO_PASSWORD",
        "cloud_username": "",
        "cloud_username_env": "CLOUD_REPO_USERNAME",
        "git_names": {"meyt1n", "yangtianmu", "杨天慕"},
        "git_emails": {
            "3214037940@qq.com",
            "yangtianmu@stumail.ysu.edu.cn",
        },
    },
    "shen-huang-123": {
        "github_login": "Shen-huang-123",
        "token_env": "CLOUD_TOKEN_SHEN_HUANG_123",
        "cloud_username": "zhang",
        "cloud_username_env": "",
        "git_names": {"shen-huang-123", "zhang", "张子涵"},
        "git_emails": {"z85963541@qq.com"},
    },
    "ry12-20": {
        "github_login": "ry12-20",
        "token_env": "CLOUD_TOKEN_RY12_20",
        "cloud_username": "ry12-20",
        "cloud_username_env": "",
        "git_names": {"ry12-20"},
        "git_emails": set(),
    },
    "389883656-lgtm": {
        "github_login": "389883656-lgtm",
        "token_env": "CLOUD_TOKEN_389883656_LGTM",
        "cloud_username": "yanghuan",
        "cloud_username_env": "",
        "git_names": {"389883656-lgtm", "yanghuan"},
        "git_emails": {"389883656@qq.com"},
    },
    "jin-123-zip": {
        "github_login": "jin-123-zip",
        "token_env": "CLOUD_TOKEN_JIN_123_ZIP",
        "cloud_username": "jin-123-zip",
        "cloud_username_env": "",
        "git_names": {"jin-123-zip"},
        "git_emails": {"3487355487@qq.com"},
    },
}

# Direct master commits are an exception to the normal PR-only sync path.
# Keep this allowlist deliberately narrow: meeting and project documentation are
# maintenance artifacts, while source/configuration changes must still go via PR.
DIRECT_MAINTENANCE_PATH_PREFIXES = ("doc/", "docs/")
DIRECT_MAINTENANCE_FILE_STATUSES = {"added", "modified"}


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _identity_for_login(pr_login: str) -> dict[str, Any]:
    identity = IDENTITIES.get(pr_login.casefold())
    if identity is None:
        raise IdentityError(
            f"GitHub PR 作者 {pr_login!r} 尚未配置内部云端 Token 映射；"
            "禁止回退到其他成员 Token"
        )
    return identity


def resolve_login_identity(github_login: str) -> dict[str, Any]:
    """Return the configured identity for a known GitHub login."""

    normalized_login = _text(github_login)
    if not normalized_login:
        raise IdentityError("提交或 PR 缺少 GitHub 作者账号")
    return _identity_for_login(normalized_login)


def _commit_matches(identity: dict[str, Any], commit: dict[str, Any]) -> bool:
    linked_login = _text((commit.get("author") or {}).get("login"))
    if linked_login:
        return linked_login.casefold() == identity["github_login"].casefold()

    git_author = (commit.get("commit") or {}).get("author") or {}
    git_email = _text(git_author.get("email")).casefold()
    git_name = _text(git_author.get("name")).casefold()
    known_emails = {value.casefold() for value in identity["git_emails"]}
    known_names = {value.casefold() for value in identity["git_names"]}

    if git_email:
        return git_email in known_emails
    return bool(git_name and git_name in known_names)


def resolve_commit_identity(commit: dict[str, Any]) -> dict[str, Any]:
    """Resolve one GitHub commit to exactly one configured internal identity."""

    linked_login = _text((commit.get("author") or {}).get("login"))
    if linked_login:
        identity = _identity_for_login(linked_login)
        if not _commit_matches(identity, commit):
            raise IdentityError(
                f"提交 {_commit_label(commit)} 的 GitHub 关联账号与提交作者不一致"
            )
    else:
        matches = [
            identity
            for identity in IDENTITIES.values()
            if _commit_matches(identity, commit)
        ]
        if len(matches) != 1:
            raise IdentityError(
                f"提交 {_commit_label(commit)} 无法唯一匹配已登记的内部身份；"
                "请补齐 GitHub 关联账号或已审核的姓名/邮箱映射"
            )
        identity = matches[0]

    return {
        "github_login": identity["github_login"],
        "token_env": identity["token_env"],
        "cloud_username": identity["cloud_username"],
        "cloud_username_env": identity["cloud_username_env"],
    }


def _load_direct_commit_files(commit: dict[str, Any]) -> list[dict[str, Any]]:
    if commit.get("files_complete") is not True:
        raise IdentityError(
            f"提交 {_commit_label(commit)} 的文件清单未证明完整；"
            "直接维护提交必须基于本地完整 Git diff，不能直接信任 GitHub API 截断清单"
        )
    files = commit.get("files")
    if not isinstance(files, list) or not files:
        raise IdentityError(
            f"提交 {_commit_label(commit)} 缺少完整文件清单；"
            "直接维护提交必须由 GitHub API 提供文件路径"
        )
    if not all(isinstance(item, dict) for item in files):
        raise IdentityError(f"提交 {_commit_label(commit)} 的文件清单格式无效")
    return files


def _git_path_is_safe_maintenance_path(value: object) -> bool:
    """Validate a Git path without normalizing away traversal evidence."""

    if not isinstance(value, str) or not value or "\\" in value:
        return False
    if value.startswith("/"):
        return False
    parts = value.split("/")
    if len(parts) < 2 or parts[0] not in {"doc", "docs"}:
        return False
    return all(part not in {"", ".", ".."} for part in parts)


def _run_git_bytes(repo: Path, *args: str) -> bytes:
    if shutil.which("git") is None:
        raise IdentityError("当前环境找不到 git，无法生成完整直接提交文件清单")
    process = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        detail = (process.stderr or process.stdout).decode("utf-8", errors="replace").strip()
        raise IdentityError(f"生成直接提交完整 Git diff 失败：{detail or 'unknown git error'}")
    return process.stdout


def _complete_direct_commit_files(
    repo: Path, parent_sha: str, commit_sha: str
) -> list[dict[str, Any]]:
    """Collect every changed path from the local Git object database.

    GitHub's commit endpoint may truncate ``files`` for large commits. The
    sync workflow has a full-history checkout, so the local diff is the
    authoritative, non-truncated manifest for this narrow exception path.
    """

    actual_commit = _run_git_bytes(
        repo, "rev-parse", "--verify", f"{commit_sha}^{{commit}}"
    ).decode().strip()
    actual_parent = _run_git_bytes(
        repo, "rev-parse", "--verify", f"{parent_sha}^{{commit}}"
    ).decode().strip()
    first_parent = _run_git_bytes(
        repo, "rev-parse", "--verify", f"{commit_sha}^"
    ).decode().strip()
    if actual_commit != commit_sha or first_parent != actual_parent:
        raise IdentityError(
            f"直接提交 {commit_sha[:12]} 的本地提交/第一父提交与预检元数据不一致"
        )

    raw = _run_git_bytes(
        repo,
        "diff-tree",
        "--no-commit-id",
        "-r",
        "--name-status",
        "-z",
        "--find-renames",
        parent_sha,
        commit_sha,
    )
    fields = raw.decode("utf-8", errors="surrogateescape").split("\0")
    files: list[dict[str, Any]] = []
    index = 0
    while index < len(fields) - 1:
        status = fields[index]
        index += 1
        if not status:
            continue
        if status[0] in {"R", "C"}:
            if index + 1 >= len(fields):
                raise IdentityError("本地 Git diff 的 rename/copy 条目不完整")
            previous_filename = fields[index]
            filename = fields[index + 1]
            index += 2
            files.append(
                {
                    "filename": filename,
                    "previous_filename": previous_filename,
                    "status": "renamed" if status[0] == "R" else "copied",
                }
            )
            continue
        if index >= len(fields):
            raise IdentityError("本地 Git diff 的文件条目不完整")
        filename = fields[index]
        index += 1
        status_name = {
            "A": "added",
            "M": "modified",
            "D": "deleted",
            "T": "modified",
        }.get(status[0], status)
        files.append({"filename": filename, "status": status_name})
    if not files:
        raise IdentityError(f"直接提交 {commit_sha[:12]} 没有可审计的文件变更")
    return files


def build_complete_direct_commit_metadata(
    commit: dict[str, Any],
    repo: Path,
    commit_sha: str,
    parent_sha: str,
) -> dict[str, Any]:
    """Attach a complete local-Git file manifest to GitHub commit metadata."""

    if _text(commit.get("sha")) != commit_sha:
        raise IdentityError("GitHub 提交元数据 SHA 与本地同步节点不一致")
    result = dict(commit)
    result["parents"] = [{"sha": parent_sha}]
    result["files"] = _complete_direct_commit_files(repo, parent_sha, commit_sha)
    result["files_complete"] = True
    result["file_count"] = len(result["files"])
    return result


def resolve_direct_maintenance_identity(commit: dict[str, Any]) -> dict[str, Any]:
    """Resolve one safe, documentation-only direct master maintenance commit.

    This path intentionally requires both GitHub linked identities. Git author
    text alone is not sufficient because it can be changed locally without a
    corresponding GitHub account association.
    """

    author_login = _text((commit.get("author") or {}).get("login"))
    committer_login = _text((commit.get("committer") or {}).get("login"))
    if not author_login or not committer_login:
        raise IdentityError(
            f"提交 {_commit_label(commit)} 缺少 GitHub author 或 committer 账号；"
            "直接维护提交不得使用未关联身份"
        )
    if author_login.casefold() != committer_login.casefold():
        raise IdentityError(
            f"提交 {_commit_label(commit)} 的 GitHub author 与 committer 不一致；"
            "直接维护提交只能归属一个已登记成员"
        )
    parents = commit.get("parents")
    if not isinstance(parents, list) or len(parents) != 1:
        raise IdentityError(
            f"提交 {_commit_label(commit)} 不是普通单父提交；"
            "直接维护提交不得使用合并或无父拓扑"
        )

    identity = _identity_for_login(author_login)
    files = _load_direct_commit_files(commit)
    invalid_paths: list[str] = []
    invalid_statuses: list[str] = []
    renamed_paths: list[str] = []
    for file_info in files:
        raw_filename = file_info.get("filename")
        path = _text(raw_filename)
        status = _text(file_info.get("status")).casefold()
        if not _git_path_is_safe_maintenance_path(raw_filename):
            invalid_paths.append(path or "<missing-path>")
        if status not in DIRECT_MAINTENANCE_FILE_STATUSES:
            invalid_statuses.append(f"{path or '<missing-path>'} ({status or 'missing-status'})")
        if _text(file_info.get("previous_filename")):
            renamed_paths.append(path or "<missing-path>")
    if invalid_paths:
        details = ", ".join(invalid_paths[:5])
        raise IdentityError(
            f"提交 {_commit_label(commit)} 含非维护文档路径：{details}；"
            "直接 master 提交只允许 doc/ 或 docs/"
        )
    if renamed_paths:
        details = ", ".join(renamed_paths[:5])
        raise IdentityError(
            f"提交 {_commit_label(commit)} 含 rename/copy 文件：{details}；"
            "直接维护提交不得携带 previous_filename"
        )
    if invalid_statuses:
        details = ", ".join(invalid_statuses[:5])
        raise IdentityError(
            f"提交 {_commit_label(commit)} 含不允许的文件状态：{details}；"
            "直接维护提交只允许 added 或 modified"
        )

    return {
        "github_login": identity["github_login"],
        "token_env": identity["token_env"],
        "cloud_username": identity["cloud_username"],
        "cloud_username_env": identity["cloud_username_env"],
        "commit_count": 1,
        "kind": "direct-maintenance",
    }


def _commit_label(commit: dict[str, Any]) -> str:
    sha = _text(commit.get("sha"))[:12] or "unknown-sha"
    linked_login = _text((commit.get("author") or {}).get("login"))
    git_author = (commit.get("commit") or {}).get("author") or {}
    git_name = _text(git_author.get("name")) or "unknown-name"
    git_email = _text(git_author.get("email")) or "unknown-email"
    return f"{sha} ({linked_login or 'unlinked'}; {git_name} <{git_email}>)"


def resolve_identity(pr_login: str, commits: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the configured identity after validating every PR commit."""

    normalized_login = _text(pr_login)
    if not normalized_login:
        raise IdentityError("关联 PR 缺少 GitHub 作者账号")
    if not commits:
        raise IdentityError(f"PR 作者 {normalized_login!r} 没有可核对的提交")

    identity = _identity_for_login(normalized_login)
    mismatches = [
        _commit_label(commit)
        for commit in commits
        if not isinstance(commit, dict) or not _commit_matches(identity, commit)
    ]
    if mismatches:
        details = ", ".join(mismatches[:5])
        raise IdentityError(
            f"PR 作者 {normalized_login!r} 与提交账号不一致：{details}。"
            "一个同步 push 只能归属一个 Token。请在合并前拆分 PR、改用正确的 PR 作者账号，"
            "或更正提交身份；不要把其他成员的分支/提交混入本人的 PR"
        )

    return {
        "github_login": identity["github_login"],
        "token_env": identity["token_env"],
        "cloud_username": identity["cloud_username"],
        "cloud_username_env": identity["cloud_username_env"],
        "commit_count": len(commits),
    }


def load_commits(path: Path) -> list[dict[str, Any]]:
    """Load one compact GitHub commit JSON object per line."""

    commits: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise IdentityError(f"提交清单第 {line_number} 行不是合法 JSON") from error
        if not isinstance(value, dict):
            raise IdentityError(f"提交清单第 {line_number} 行不是 JSON 对象")
        commits.append(value)
    return commits


def load_commit(path: Path) -> dict[str, Any]:
    """Load one GitHub commit JSON object."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise IdentityError("直接提交元数据不是合法 JSON") from error
    if not isinstance(value, dict):
        raise IdentityError("直接提交元数据不是 JSON 对象")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--pr-login")
    mode.add_argument("--direct-commit-file", type=Path)
    parser.add_argument("--commits-file", type=Path)
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--commit-sha")
    parser.add_argument("--parent-sha")
    args = parser.parse_args()

    try:
        if args.direct_commit_file is not None:
            if args.repo is None or not args.commit_sha or not args.parent_sha:
                raise IdentityError(
                    "直接维护提交身份解析需要 --repo、--commit-sha 和 --parent-sha，"
                    "以生成未截断的本地 Git 文件清单"
                )
            commit = build_complete_direct_commit_metadata(
                load_commit(args.direct_commit_file),
                args.repo,
                args.commit_sha,
                args.parent_sha,
            )
            result = resolve_direct_maintenance_identity(
                commit
            )
        else:
            if not args.pr_login or args.commits_file is None:
                raise IdentityError("PR 身份解析需要 --pr-login 和 --commits-file")
            result = resolve_identity(args.pr_login, load_commits(args.commits_file))
    except (IdentityError, OSError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
