#!/usr/bin/env python3
"""Resolve a merged PR to one explicitly configured internal-cloud identity."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


class IdentityError(ValueError):
    """Raised when a PR cannot be attributed to exactly one configured identity."""


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
            "一个同步 push 只能归属一个 Token，请拆分 PR 或更正提交身份"
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pr-login", required=True)
    parser.add_argument("--commits-file", type=Path, required=True)
    args = parser.parse_args()

    try:
        result = resolve_identity(args.pr_login, load_commits(args.commits_file))
    except (IdentityError, OSError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
