"""Tests for fast-forward-safe dual-repository synchronization planning."""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "cloud_sync_plan.py"
SPEC = importlib.util.spec_from_file_location("cloud_sync_plan", SCRIPT)
assert SPEC and SPEC.loader
SYNC_PLAN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SYNC_PLAN)

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Sync Test",
    "GIT_AUTHOR_EMAIL": "sync-test@example.invalid",
    "GIT_COMMITTER_NAME": "Sync Test",
    "GIT_COMMITTER_EMAIL": "sync-test@example.invalid",
}


def git(repo: Path, *args: str) -> str:
    env = os.environ.copy()
    env.update(GIT_IDENTITY)
    process = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    return process.stdout.strip()


def initialize_repo(repo: Path) -> tuple[str, str]:
    repo.mkdir()
    git(repo, "init", "-b", "master")
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    git(repo, "add", "base.txt")
    git(repo, "commit", "-m", "base")
    return git(repo, "rev-parse", "HEAD"), git(repo, "rev-parse", "HEAD^{tree}")


def commit_tree(repo: Path, tree: str, message: str, *parents: str) -> str:
    parent_args = [item for parent in parents for item in ("-p", parent)]
    return git(repo, "commit-tree", tree, *parent_args, "-m", message)


def test_loads_unique_pr_commit_shas_from_ndjson(tmp_path: Path) -> None:
    commits_file = tmp_path / "commits.ndjson"
    commits_file.write_text(
        '{"sha":"first"}\n{"sha":"second"}\n{"sha":"first"}\n',
        encoding="utf-8",
    )

    assert SYNC_PLAN.load_pr_commit_shas(commits_file) == {"first", "second"}


def test_builds_first_parent_plan_for_normal_master_history(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base, tree = initialize_repo(repo)
    first = commit_tree(repo, tree, "first", base)
    second = commit_tree(repo, tree, "second", first)

    plan = SYNC_PLAN.build_sync_plan(repo, base, second)

    assert plan == {"mode": "first-parent", "shas": [first, second]}


def test_keeps_only_master_merge_nodes_for_normal_pr_merge(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base, tree = initialize_repo(repo)
    master_commit = commit_tree(repo, tree, "master", base)
    feature_commit = commit_tree(repo, tree, "feature", base)
    merge_commit = commit_tree(repo, tree, "merge", master_commit, feature_commit)

    plan = SYNC_PLAN.build_sync_plan(repo, base, merge_commit)

    assert plan == {
        "mode": "first-parent",
        "shas": [master_commit, merge_commit],
    }


def test_rejects_non_first_parent_reconciliation_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base, tree = initialize_repo(repo)
    github_commit = commit_tree(repo, tree, "github", base)
    cloud_commit = commit_tree(repo, tree, "cloud", base)
    reconciliation = commit_tree(
        repo,
        tree,
        "reconciliation",
        github_commit,
        cloud_commit,
    )
    merged_pr = commit_tree(repo, tree, "merged-pr", github_commit, reconciliation)

    with pytest.raises(SYNC_PLAN.SyncPlanError, match="第一父链"):
        SYNC_PLAN.build_sync_plan(repo, cloud_commit, merged_pr)


def test_rejects_unreconciled_divergence(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base, tree = initialize_repo(repo)
    github_commit = commit_tree(repo, tree, "github", base)
    cloud_commit = commit_tree(repo, tree, "cloud", base)

    with pytest.raises(SYNC_PLAN.SyncPlanError, match="已分叉"):
        SYNC_PLAN.build_sync_plan(repo, cloud_commit, github_commit)


def test_reports_already_synced_and_cloud_ahead_without_pushes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base, tree = initialize_repo(repo)
    cloud_commit = commit_tree(repo, tree, "cloud", base)

    assert SYNC_PLAN.build_sync_plan(repo, base, base) == {
        "mode": "already-synced",
        "shas": [],
    }
    assert SYNC_PLAN.build_sync_plan(repo, cloud_commit, base) == {
        "mode": "cloud-ahead",
        "shas": [],
    }


def test_accepts_boundary_containing_only_pr_and_merge_commits(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base, tree = initialize_repo(repo)
    feature_commit = commit_tree(repo, tree, "feature", base)
    merge_commit = commit_tree(repo, tree, "merge", base, feature_commit)

    boundary = SYNC_PLAN.validate_pr_boundary(
        repo,
        base,
        merge_commit,
        {feature_commit},
    )

    assert set(boundary["introduced_shas"]) == {feature_commit, merge_commit}
    assert boundary["introduced_count"] == 2


def test_rejects_boundary_that_imports_commit_outside_pr(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base, tree = initialize_repo(repo)
    pr_commit = commit_tree(repo, tree, "pr", base)
    foreign_commit = commit_tree(repo, tree, "foreign", base)
    merge_commit = commit_tree(repo, tree, "merge", pr_commit, foreign_commit)

    with pytest.raises(SYNC_PLAN.SyncPlanError, match="不属于该 PR"):
        SYNC_PLAN.validate_pr_boundary(
            repo,
            base,
            merge_commit,
            {pr_commit},
        )


def test_rejects_incident_shape_that_imports_other_pr_on_final_merge(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    base, tree = initialize_repo(repo)
    github_commit = commit_tree(repo, tree, "github", base)
    cloud_commit = commit_tree(repo, tree, "cloud", base)
    reconciliation = commit_tree(
        repo,
        tree,
        "reconciliation",
        github_commit,
        cloud_commit,
    )
    other_pr_commit = commit_tree(repo, tree, "other-pr", github_commit)
    other_pr_merge = commit_tree(
        repo,
        tree,
        "other-pr-merge",
        github_commit,
        other_pr_commit,
    )
    final_merge = commit_tree(
        repo,
        tree,
        "final-merge",
        other_pr_merge,
        reconciliation,
    )

    with pytest.raises(SYNC_PLAN.SyncPlanError, match="不属于该 PR"):
        SYNC_PLAN.validate_pr_boundary(
            repo,
            reconciliation,
            final_merge,
            {cloud_commit, reconciliation},
        )
