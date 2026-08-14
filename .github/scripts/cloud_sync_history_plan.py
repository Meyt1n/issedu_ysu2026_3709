#!/usr/bin/env python3
"""Build an audited, per-commit ownership plan for legacy cloud sync repair."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


class HistoryPlanError(ValueError):
    """Raised when a legacy synchronization plan is unsafe or incomplete."""


def _load_identity_module() -> Any:
    try:
        from cloud_sync_identity import (  # type: ignore[import-not-found]
            IdentityError,
            resolve_commit_identity,
            resolve_login_identity,
        )

        return IdentityError, resolve_commit_identity, resolve_login_identity
    except ModuleNotFoundError:
        path = Path(__file__).with_name("cloud_sync_identity.py")
        spec = importlib.util.spec_from_file_location("cloud_sync_identity", path)
        if spec is None or spec.loader is None:
            raise HistoryPlanError(f"无法加载身份映射脚本：{path}") from None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return (
            module.IdentityError,
            module.resolve_commit_identity,
            module.resolve_login_identity,
        )


IdentityError, resolve_commit_identity, resolve_login_identity = _load_identity_module()


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
        raise HistoryPlanError(f"git {' '.join(args)} 失败：{detail}")
    return process.stdout.strip()


def _commit_sha(repo: Path, value: str) -> str:
    if not value.strip():
        raise HistoryPlanError("同步端点 SHA 不能为空")
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
    raise HistoryPlanError(f"无法检查提交祖先关系：{detail}")


def _first_parent_plan(repo: Path, cloud_sha: str, github_sha: str) -> list[str]:
    if cloud_sha == github_sha:
        return []
    if not _is_ancestor(repo, cloud_sha, github_sha):
        raise HistoryPlanError("内部 master 不在 GitHub master 的祖先链上，拒绝重写历史")
    return _run_git(
        repo,
        "rev-list",
        "--first-parent",
        "--reverse",
        f"{cloud_sha}..{github_sha}",
    ).splitlines()


def _parents(repo: Path, sha: str) -> list[str]:
    output = _run_git(repo, "show", "-s", "--format=%P", sha)
    return output.split() if output else []


def _second_parent_path(repo: Path, previous_sha: str, second_parent: str) -> list[str]:
    output = _run_git(
        repo,
        "rev-list",
        "--reverse",
        f"{previous_sha}..{second_parent}",
    )
    return output.splitlines() if output else []


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _metadata_sha(metadata: dict[str, Any]) -> str:
    value = _text(metadata.get("sha"))
    if not value:
        raise HistoryPlanError("提交元数据缺少 SHA")
    return value


def _owner_fields(identity: dict[str, Any]) -> dict[str, str]:
    return {
        "github_login": identity["github_login"],
        "token_env": identity["token_env"],
        "cloud_username": identity["cloud_username"],
        "cloud_username_env": identity["cloud_username_env"],
    }


def _action(
    *,
    sha: str,
    kind: str,
    identity: dict[str, Any],
    previous_sha: str,
    pr_number: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "sha": sha,
        "kind": kind,
        "previous_sha": previous_sha,
        **_owner_fields(identity),
    }
    if pr_number is not None:
        result["pr_number"] = pr_number
    return result


def build_history_plan(
    repo: Path,
    cloud_sha: str,
    github_sha: str,
    nodes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build per-commit pushes without changing any Git refs."""

    cloud_sha = _commit_sha(repo, cloud_sha)
    github_sha = _commit_sha(repo, github_sha)
    first_parent_shas = _first_parent_plan(repo, cloud_sha, github_sha)
    by_target = {_metadata_sha(node): node for node in nodes}
    if len(by_target) != len(nodes):
        raise HistoryPlanError("同步节点元数据包含重复目标 SHA")

    actions: list[dict[str, Any]] = []
    current = cloud_sha
    for target_sha in first_parent_shas:
        node = by_target.get(target_sha)
        if node is None:
            raise HistoryPlanError(f"缺少同步节点元数据：{target_sha}")
        parents = _parents(repo, target_sha)
        if not parents or parents[0] != current:
            raise HistoryPlanError(
                f"提交 {target_sha[:12]} 的第一父提交不是当前同步点 {current[:12]}"
            )

        pr_number_value = node.get("pr_number")
        pr_number = int(pr_number_value) if pr_number_value is not None else None
        if len(parents) >= 2:
            if pr_number is None or not _text(node.get("pr_login")):
                raise HistoryPlanError(
                    f"合并提交 {target_sha[:12]} 缺少唯一已合并 PR 作者元数据"
                )
            second_parent = parents[1]
            second_path = _second_parent_path(repo, current, second_parent)
            pr_commits = node.get("pr_commits")
            if not isinstance(pr_commits, list) or not pr_commits:
                raise HistoryPlanError(f"PR #{pr_number} 缺少完整提交元数据")
            commit_by_sha = {_metadata_sha(item): item for item in pr_commits}
            if set(second_path) != set(commit_by_sha):
                missing = sorted(set(second_path) - set(commit_by_sha))
                unexpected = sorted(set(commit_by_sha) - set(second_path))
                raise HistoryPlanError(
                    f"PR #{pr_number} 与合并提交 {target_sha[:12]} 的第二父链不一致；"
                    f"缺少={','.join(item[:12] for item in missing[:5]) or '-'}；"
                    f"多出={','.join(item[:12] for item in unexpected[:5]) or '-'}"
                )
            for commit_sha in second_path:
                try:
                    identity = resolve_commit_identity(commit_by_sha[commit_sha])
                except IdentityError as error:
                    raise HistoryPlanError(
                        f"PR #{pr_number} 提交 {commit_sha[:12]}：{error}"
                    ) from error
                actions.append(
                    _action(
                        sha=commit_sha,
                        kind="pr-commit",
                        identity=identity,
                        previous_sha=current,
                        pr_number=pr_number,
                    )
                )
                current = commit_sha
            try:
                merge_identity = resolve_login_identity(_text(node["pr_login"]))
            except IdentityError as error:
                raise HistoryPlanError(f"PR #{pr_number} 合并提交归属无法解析：{error}") from error
            actions.append(
                _action(
                    sha=target_sha,
                    kind="pr-merge",
                    identity=merge_identity,
                    previous_sha=current,
                    pr_number=pr_number,
                )
            )
            current = target_sha
            continue

        if len(parents) != 1:
            raise HistoryPlanError(f"提交 {target_sha[:12]} 是不支持的非普通提交拓扑")
        if node.get("pr_number") is not None:
            raise HistoryPlanError(
                f"普通提交 {target_sha[:12]} 不能伪装成 PR 合并提交"
            )
        commit_metadata = node.get("commit")
        if not isinstance(commit_metadata, dict) or _metadata_sha(commit_metadata) != target_sha:
            raise HistoryPlanError(f"直接提交 {target_sha[:12]} 缺少匹配的提交作者元数据")
        try:
            identity = resolve_commit_identity(commit_metadata)
        except IdentityError as error:
            raise HistoryPlanError(f"直接提交 {target_sha[:12]}：{error}") from error
        actions.append(
            _action(
                sha=target_sha,
                kind="direct-commit",
                identity=identity,
                previous_sha=current,
            )
        )
        current = target_sha

    if current != github_sha:
        raise HistoryPlanError(
            f"同步计划未到达 GitHub master：计划={current[:12]}，目标={github_sha[:12]}"
        )
    return {
        "mode": "legacy-per-commit-dry-run",
        "cloud_sha": cloud_sha,
        "github_sha": github_sha,
        "first_parent_count": len(first_parent_shas),
        "action_count": len(actions),
        "actions": actions,
    }


def load_metadata(path: Path) -> list[dict[str, Any]]:
    raw = sys.stdin.read() if str(path) == "-" else path.read_text(encoding="utf-8")
    value = json.loads(raw)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise HistoryPlanError("同步节点元数据必须是 JSON 对象数组")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--cloud-sha", required=True)
    parser.add_argument("--github-sha", required=True)
    parser.add_argument("--metadata-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build_history_plan(
            args.repo,
            args.cloud_sha,
            args.github_sha,
            load_metadata(args.metadata_file),
        )
    except (OSError, HistoryPlanError, json.JSONDecodeError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
