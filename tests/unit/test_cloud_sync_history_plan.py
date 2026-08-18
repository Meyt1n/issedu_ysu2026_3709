"""Tests for legacy per-commit dual-repository repair planning."""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "cloud_sync_history_plan.py"
SPEC = importlib.util.spec_from_file_location("cloud_sync_history_plan", SCRIPT)
assert SPEC and SPEC.loader
HISTORY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HISTORY)

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


def initialize_repo(repo: Path) -> str:
    repo.mkdir()
    git(repo, "init", "-b", "master")
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    git(repo, "add", "base.txt")
    git(repo, "commit", "-m", "base")
    return git(repo, "rev-parse", "HEAD")


def commit(repo: Path, parent: str, message: str) -> str:
    (repo / f"{message}.txt").write_text(f"{message}\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def merge(repo: Path, first: str, second: str, message: str) -> str:
    tree = git(repo, "rev-parse", f"{first}^{{tree}}")
    return git(repo, "commit-tree", tree, "-p", first, "-p", second, "-m", message)


def linked_commit(sha: str, login: str, name: str, email: str) -> dict:
    return {
        "sha": sha,
        "author": {"login": login},
        "commit": {"author": {"name": name, "email": email}},
    }


def direct_commit_metadata(sha: str, login: str, name: str, email: str) -> dict:
    return {
        "sha": sha,
        "author": {"login": login},
        "committer": {"login": login},
        "parents": [{"sha": "parent"}],
        "commit": {
            "author": {"name": name, "email": email},
            "committer": {"name": name, "email": email},
        },
        "files": [
            {"filename": "doc/07.会议记录/meeting-record.docx", "status": "added"}
        ],
        "files_complete": True,
    }


def test_plans_mixed_pr_commit_and_merge_with_separate_owners(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base = initialize_repo(repo)
    pr_commit = commit(repo, base, "ry-change")
    merge_commit = merge(repo, base, pr_commit, "merge-pr-141")

    plan = HISTORY.build_history_plan(
        repo,
        base,
        merge_commit,
        [
            {
                "sha": merge_commit,
                "pr_number": 141,
                "pr_login": "Meyt1n",
                "pr_commits": [
                    linked_commit(
                        pr_commit,
                        "ry12-20",
                        "ry12-20",
                        "1970591935@qq.com",
                    )
                ],
            }
        ],
    )

    assert [item["sha"] for item in plan["actions"]] == [pr_commit, merge_commit]
    assert [item["github_login"] for item in plan["actions"]] == ["ry12-20", "Meyt1n"]
    assert [item["kind"] for item in plan["actions"]] == ["pr-commit", "pr-merge"]
    assert [item["push_mode"] for item in plan["actions"]] == [
        "fast-forward",
        "fast-forward",
    ]


def test_stages_pr_commit_when_current_master_moved_from_branch_base(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    base = initialize_repo(repo)
    master_commit = commit(repo, base, "master-change")
    feature_tree = git(repo, "rev-parse", f"{base}^{{tree}}")
    feature_commit = git(
        repo,
        "commit-tree",
        feature_tree,
        "-p",
        base,
        "-m",
        "feature-change",
    )
    merge_commit = merge(repo, master_commit, feature_commit, "merge-pr-141")

    plan = HISTORY.build_history_plan(
        repo,
        master_commit,
        merge_commit,
        [
            {
                "sha": merge_commit,
                "pr_number": 141,
                "pr_login": "Meyt1n",
                "pr_commits": [
                    linked_commit(
                        feature_commit,
                        "ry12-20",
                        "ry12-20",
                        "1970591935@qq.com",
                    )
                ],
            }
        ],
    )

    assert [item["push_mode"] for item in plan["actions"]] == [
        "force-with-lease-staging",
        "fast-forward",
    ]


def test_plans_direct_commit_by_commit_owner(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base = initialize_repo(repo)
    direct = commit(repo, base, "meeting-record")

    plan = HISTORY.build_history_plan(
        repo,
        base,
        direct,
        [
            {
                "sha": direct,
                "commit": direct_commit_metadata(
                    direct,
                    "ry12-20",
                    "ry12-20",
                    "1970591935@qq.com",
                ),
            }
        ],
    )

    assert plan["actions"] == [
        {
            "sha": direct,
            "kind": "direct-commit",
            "previous_sha": base,
            "push_mode": "fast-forward",
            "github_login": "ry12-20",
            "token_env": "CLOUD_TOKEN_RY12_20",
            "cloud_username": "ry12-20",
            "cloud_username_env": "",
        }
    ]


def test_rejects_pr_metadata_that_does_not_match_second_parent_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base = initialize_repo(repo)
    pr_commit = commit(repo, base, "ry-change")
    merge_commit = merge(repo, base, pr_commit, "merge-pr")

    with pytest.raises(HISTORY.HistoryPlanError, match="第二父链不一致"):
        HISTORY.build_history_plan(
            repo,
            base,
            merge_commit,
            [
                {
                    "sha": merge_commit,
                    "pr_number": 141,
                    "pr_login": "Meyt1n",
                    "pr_commits": [
                        linked_commit(
                            "0" * 40,
                            "ry12-20",
                            "ry12-20",
                            "1970591935@qq.com",
                        )
                    ],
                }
            ],
        )
