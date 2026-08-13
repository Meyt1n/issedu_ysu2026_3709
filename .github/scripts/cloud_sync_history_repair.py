#!/usr/bin/env python3
"""Collect GitHub metadata and produce a no-push legacy sync dry-run plan."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from cloud_sync_history_plan import HistoryPlanError, build_history_plan


def _run(command: list[str]) -> str:
    process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip() or "unknown command error"
        raise HistoryPlanError(f"命令失败：{' '.join(command[:4])}…：{detail}")
    return process.stdout


def _git(repo: Path, *args: str) -> str:
    return _run(["git", "-C", str(repo), *args]).strip()


def _gh_json(repository: str, endpoint: str) -> Any:
    output = _run(["gh", "api", f"repos/{repository}/{endpoint}"])
    try:
        return json.loads(output)
    except json.JSONDecodeError as error:
        raise HistoryPlanError(f"GitHub API 返回不是合法 JSON：{endpoint}") from error


def _gh_paginated_objects(repository: str, endpoint: str) -> list[dict[str, Any]]:
    output = _run(["gh", "api", "--paginate", f"repos/{repository}/{endpoint}", "--jq", ".[]"])
    objects: list[dict[str, Any]] = []
    for line_number, line in enumerate(output.splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise HistoryPlanError(
                f"GitHub API 分页结果第 {line_number} 行不是合法 JSON：{endpoint}"
            ) from error
        if not isinstance(value, dict):
            raise HistoryPlanError(f"GitHub API 分页结果不是对象：{endpoint}")
        objects.append(value)
    return objects


def _first_parent_shas(repo: Path, cloud_sha: str, github_sha: str) -> list[str]:
    if cloud_sha == github_sha:
        return []
    return _git(
        repo,
        "rev-list",
        "--first-parent",
        "--reverse",
        f"{cloud_sha}..{github_sha}",
    ).splitlines()


def collect_metadata(
    repo: Path,
    repository: str,
    cloud_sha: str,
    github_sha: str,
) -> list[dict[str, Any]]:
    """Collect only public GitHub commit/PR metadata needed by the planner."""

    metadata: list[dict[str, Any]] = []
    for sha in _first_parent_shas(repo, cloud_sha, github_sha):
        parents = _git(repo, "show", "-s", "--format=%P", sha).split()
        if len(parents) >= 2:
            prs = _gh_json(repository, f"commits/{sha}/pulls")
            if not isinstance(prs, list):
                raise HistoryPlanError(f"提交 {sha[:12]} 的 PR 关联结果不是数组")
            merged_prs = [
                pr
                for pr in prs
                if isinstance(pr, dict)
                and (pr.get("base") or {}).get("ref") == "master"
                and pr.get("merged_at")
            ]
            if len(merged_prs) != 1:
                raise HistoryPlanError(
                    f"提交 {sha[:12]} 未关联唯一的已合并 master PR：{len(merged_prs)} 个"
                )
            pr = merged_prs[0]
            number = pr.get("number")
            login = (pr.get("user") or {}).get("login")
            if not isinstance(number, int) or not isinstance(login, str) or not login.strip():
                raise HistoryPlanError(f"提交 {sha[:12]} 的 PR 作者元数据不完整")
            metadata.append(
                {
                    "sha": sha,
                    "pr_number": number,
                    "pr_login": login,
                    "pr_commits": _gh_paginated_objects(
                        repository,
                        f"pulls/{number}/commits?per_page=100",
                    ),
                }
            )
        elif len(parents) == 1:
            metadata.append(
                {
                    "sha": sha,
                    "commit": _gh_json(repository, f"commits/{sha}"),
                }
            )
        else:
            raise HistoryPlanError(f"提交 {sha[:12]} 没有父提交，不支持作为增量同步节点")
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--github-repository", required=True)
    parser.add_argument("--cloud-sha", required=True)
    parser.add_argument("--github-sha", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        metadata = collect_metadata(
            args.repo,
            args.github_repository,
            args.cloud_sha,
            args.github_sha,
        )
        result = build_history_plan(
            args.repo,
            args.cloud_sha,
            args.github_sha,
            metadata,
        )
        rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
    except (OSError, HistoryPlanError, json.JSONDecodeError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
