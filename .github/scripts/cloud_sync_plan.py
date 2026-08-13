#!/usr/bin/env python3
"""Build a fast-forward-safe plan from an internal master to GitHub master."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


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
    if first_parent_shas and _is_ancestor(repo, cloud_sha, first_parent_shas[0]):
        mode = "first-parent"
        sync_shas = first_parent_shas
    else:
        mode = "ancestry-reconciliation"
        sync_shas = _rev_list(
            repo,
            "--ancestry-path",
            "--topo-order",
            "--reverse",
            f"{cloud_sha}..{github_sha}",
        )

    _validate_fast_forward_chain(repo, cloud_sha, github_sha, sync_shas)
    return {"mode": mode, "shas": sync_shas}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--cloud-sha", required=True)
    parser.add_argument("--github-sha", required=True)
    args = parser.parse_args()

    try:
        plan = build_sync_plan(args.repo, args.cloud_sha, args.github_sha)
    except (OSError, SyncPlanError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1

    print(json.dumps(plan, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
