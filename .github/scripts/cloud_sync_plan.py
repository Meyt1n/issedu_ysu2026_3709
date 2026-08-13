#!/usr/bin/env python3
"""Build a fast-forward-safe plan from an internal master to GitHub master."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


class SyncPlanError(ValueError):
    """Raised when the two refs cannot be synchronized without rewriting history."""


def _run_git(repo: Path, *args: str) -> str:
    process = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip() or "unknown git error"
        raise SyncPlanError(f"git {' '.join(args)} 失败：{detail}")
    return process.stdout.strip()


def _commit_sha(repo: Path, value: str) -> str:
    if not value.strip():
        raise SyncPlanError("同步端点 SHA 不能为空")
    return _run_git(repo, "rev-parse", "--verify", f"{value}^{{commit}}")


def _is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    process = subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", ancestor, descendant],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if process.returncode == 0:
        return True
    if process.returncode == 1:
        return False
    detail = process.stderr.strip() or process.stdout.strip() or "unknown git error"
    raise SyncPlanError(f"无法检查提交祖先关系：{detail}")


def _rev_list(repo: Path, *args: str) -> list[str]:
    output = _run_git(repo, "rev-list", *args)
    return output.splitlines() if output else []


def _validate_fast_forward_chain(
    repo: Path,
    cloud_sha: str,
    github_sha: str,
    sync_shas: list[str],
) -> None:
    if not sync_shas:
        raise SyncPlanError("没有找到可快进同步的 GitHub master 提交")

    current = cloud_sha
    for sync_sha in sync_shas:
        if not _is_ancestor(repo, current, sync_sha):
            raise SyncPlanError(
                f"同步计划不是连续快进链：{current[:12]} 无法快进到 {sync_sha[:12]}"
            )
        current = sync_sha

    if current != github_sha:
        raise SyncPlanError(
            f"同步计划未到达 GitHub master：计划={current[:12]}，目标={github_sha[:12]}"
        )


def build_sync_plan(repo: Path, cloud_ref: str, github_ref: str) -> dict[str, object]:
    """Return an ordered, fast-forward-safe synchronization plan."""

    cloud_sha = _commit_sha(repo, cloud_ref)
    github_sha = _commit_sha(repo, github_ref)

    if cloud_sha == github_sha:
        return {"mode": "already-synced", "shas": []}
    if _is_ancestor(repo, github_sha, cloud_sha):
        return {"mode": "cloud-ahead", "shas": []}
    if not _is_ancestor(repo, cloud_sha, github_sha):
        raise SyncPlanError("原云端 master 与 GitHub master 已分叉，拒绝强制覆盖")

    first_parent_shas = _rev_list(
        repo,
        "--first-parent",
        "--reverse",
        f"{cloud_sha}..{github_sha}",
    )
    if not first_parent_shas or not _is_ancestor(repo, cloud_sha, first_parent_shas[0]):
        raise SyncPlanError(
            "原云端 master 不在 GitHub master 第一父链；"
            "自动同步可能把其他 PR 归入同一 Token，必须人工核对"
        )

    _validate_fast_forward_chain(repo, cloud_sha, github_sha, first_parent_shas)
    return {"mode": "first-parent", "shas": first_parent_shas}


def load_pr_commit_shas(path: Path) -> set[str]:
    """Load full commit SHAs from GitHub PR commit NDJSON."""

    commit_shas: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value: Any = json.loads(line)
        except json.JSONDecodeError as error:
            raise SyncPlanError(f"PR 提交清单第 {line_number} 行不是合法 JSON") from error
        commit_sha = value.get("sha") if isinstance(value, dict) else None
        if not isinstance(commit_sha, str) or not commit_sha.strip():
            raise SyncPlanError(f"PR 提交清单第 {line_number} 行缺少 SHA")
        commit_shas.add(commit_sha.strip())
    if not commit_shas:
        raise SyncPlanError("PR 提交清单为空")
    return commit_shas


def validate_pr_boundary(
    repo: Path,
    previous_ref: str,
    target_ref: str,
    pr_commit_shas: set[str],
) -> dict[str, object]:
    """Ensure one push introduces only one PR's commits and its merge commit."""

    previous_sha = _commit_sha(repo, previous_ref)
    target_sha = _commit_sha(repo, target_ref)
    if not _is_ancestor(repo, previous_sha, target_sha):
        raise SyncPlanError(
            f"同步边界不能快进：{previous_sha[:12]} 无法快进到 {target_sha[:12]}"
        )

    introduced_shas = _rev_list(repo, "--reverse", f"{previous_sha}..{target_sha}")
    if not introduced_shas:
        raise SyncPlanError("同步边界没有新增提交")

    allowed_shas = set(pr_commit_shas)
    allowed_shas.add(target_sha)
    unexpected_shas = [sha for sha in introduced_shas if sha not in allowed_shas]
    if unexpected_shas:
        details = ", ".join(sha[:12] for sha in unexpected_shas[:8])
        raise SyncPlanError(
            f"同步目标 {target_sha[:12]} 会额外引入不属于该 PR 的提交：{details}；"
            "禁止把混合历史归入单一 Token"
        )

    return {
        "previous_sha": previous_sha,
        "target_sha": target_sha,
        "introduced_shas": introduced_shas,
        "introduced_count": len(introduced_shas),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--repo", type=Path, default=Path.cwd())
    plan_parser.add_argument("--cloud-sha", required=True)
    plan_parser.add_argument("--github-sha", required=True)

    boundary_parser = subparsers.add_parser("validate-boundary")
    boundary_parser.add_argument("--repo", type=Path, default=Path.cwd())
    boundary_parser.add_argument("--previous-sha", required=True)
    boundary_parser.add_argument("--target-sha", required=True)
    boundary_parser.add_argument("--pr-commits-file", type=Path, required=True)
    args = parser.parse_args()

    try:
        if args.command == "plan":
            result = build_sync_plan(args.repo, args.cloud_sha, args.github_sha)
        else:
            result = validate_pr_boundary(
                args.repo,
                args.previous_sha,
                args.target_sha,
                load_pr_commit_shas(args.pr_commits_file),
            )
    except (OSError, SyncPlanError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
