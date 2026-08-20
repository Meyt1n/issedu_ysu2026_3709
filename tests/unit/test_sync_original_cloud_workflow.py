"""Static and simulated regression tests for the dual-repository workflow."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

IDENTITY_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "scripts"
    / "cloud_sync_identity.py"
)
IDENTITY_SPEC = importlib.util.spec_from_file_location(
    "cloud_sync_identity", IDENTITY_SCRIPT
)
assert IDENTITY_SPEC and IDENTITY_SPEC.loader
IDENTITY = importlib.util.module_from_spec(IDENTITY_SPEC)
IDENTITY_SPEC.loader.exec_module(IDENTITY)

WORKFLOW_PATH = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "workflows"
    / "sync-original-cloud.yml"
)
WORKFLOW_ROOT = WORKFLOW_PATH.parent


@dataclass(frozen=True)
class Node:
    sha: str
    parent: str
    parent_count: int = 1
    pr_login: str | None = None
    direct_files: tuple[dict[str, str], ...] = ()


def direct_metadata(node: Node) -> dict:
    return {
        "sha": node.sha,
        "author": {"login": "Shen-huang-123"},
        "committer": {"login": "Shen-huang-123"},
        "parents": [{"sha": node.parent}],
        "commit": {
            "author": {"name": "zhang", "email": "z85963541@qq.com"},
            "committer": {"name": "zhang", "email": "z85963541@qq.com"},
        },
        "files": list(node.direct_files),
        "files_complete": True,
    }


def simulate_preflight_then_push(nodes: list[Node], start_sha: str) -> list[str]:
    """Model the workflow's all-preflight-before-any-push contract."""

    planned: list[str] = []
    previous_sha = start_sha
    for node in nodes:
        if node.parent != previous_sha:
            raise ValueError("父节点不连续")
        if node.parent_count == 1 and node.pr_login is None:
            identity = IDENTITY.resolve_direct_maintenance_identity(direct_metadata(node))
            planned.append(f"{node.sha}:{identity['token_env']}")
        elif node.parent_count in {1, 2} and node.pr_login is not None:
            commit = {
                "sha": node.sha,
                "author": {"login": node.pr_login},
                "commit": {
                    "author": {"name": node.pr_login, "email": "member@example.invalid"}
                },
            }
            identity = IDENTITY.resolve_identity(node.pr_login, [commit])
            planned.append(f"{node.sha}:{identity['token_env']}")
        else:
            raise ValueError("缺少唯一 PR 或不支持的提交拓扑")
        previous_sha = node.sha

    # The real workflow reaches this loop only after the complete loop above.
    return planned


def workflow_run_script() -> str:
    document = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    run_step = next(
        step
        for step in document["jobs"]["sync"]["steps"]
        if step.get("name") == "预检身份并按成员 Token 逐个同步"
    )
    run_script = run_step["run"]
    assert isinstance(run_script, str)
    return run_script


def test_sync_job_is_master_only_on_the_dedicated_runner() -> None:
    document = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    job = document["jobs"]["sync"]

    assert job["runs-on"] == ["self-hosted", "hct-sync"]
    assert job["if"] == "github.ref == 'refs/heads/master'"


def test_artifact_uploads_are_disabled() -> None:
    workflow_paths = [
        WORKFLOW_ROOT / "ci.yml",
        WORKFLOW_ROOT / "execute-cloud-history-sync.yml",
        WORKFLOW_ROOT / "sync-cloud-history-dry-run.yml",
    ]

    upload_steps: list[dict] = []
    for workflow_path in workflow_paths:
        document = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        for job in document["jobs"].values():
            for step in job.get("steps", []):
                if step.get("uses", "").startswith("actions/upload-artifact@"):
                    upload_steps.append(step)

    assert upload_steps == []


def test_history_replay_uses_dedicated_runner_backup_and_exact_lease() -> None:
    path = WORKFLOW_ROOT / "execute-cloud-history-sync.yml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    job = document["jobs"]["execute"]
    scripts = "\n".join(step.get("run", "") for step in job["steps"])

    assert job["runs-on"] == ["self-hosted", "hct-sync"]
    assert "replay_from_sha" in document[True]["workflow_dispatch"]["inputs"]
    assert "hct-sync-backup-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}" in scripts
    assert '"--force-with-lease=refs/heads/master:${cloud_sha}"' in scripts
    assert '"${replay_from_sha}:refs/heads/master"' in scripts
    assert "-c credential.helper=" in scripts
    assert "cloud_git push original-cloud" in scripts
    assert "action=\"${action//$'\\r'/}\"" in scripts


def test_ci_and_relay_review_are_manual_only() -> None:
    for workflow_name in ("ci.yml", "relay-review-bot.yml"):
        document = yaml.safe_load(
            (WORKFLOW_ROOT / workflow_name).read_text(encoding="utf-8")
        )
        events = document.get("on", document.get(True))
        assert events == {"workflow_dispatch": None}


def test_workflow_uses_full_history_and_preflights_before_push() -> None:
    run_script = workflow_run_script()

    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert workflow["jobs"]["sync"]["steps"][0]["with"]["fetch-depth"] == 0
    assert "--repo ." in run_script
    assert "--commit-sha" in run_script
    assert "--parent-sha" in run_script
    assert "完整 Git diff" in run_script

    setup_script = workflow["jobs"]["sync"]["steps"][1]["run"]
    assert "HCT_SYNC_RUNNER_BIN" in setup_script
    assert "RUNNER_OS" in setup_script
    assert "cygpath" in setup_script
    assert "${sync_sha//$'\\r'/}" in run_script
    assert "${pr_meta//$'\\r'/}" in run_script
    assert "cloud_git()" in run_script
    assert "-c credential.helper=" in run_script
    assert "-c credential.useHttpPath=true" in run_script
    assert '-c "credential.username=${CLOUD_SELECTED_USERNAME}"' in run_script
    assert "cloud_git fetch original-cloud master" in run_script
    assert 'cloud_git push original-cloud "${sync_sha}:refs/heads/master"' in run_script
    assert "cloud_git ls-remote original-cloud" in run_script

    preflight_loop = run_script.index('for sync_sha in "${sync_shas[@]}"')
    plan_append = run_script.index("sync_plan+=(", preflight_loop)
    push_loop = run_script.index('for plan_row in "${sync_plan[@]}"')
    push_command = run_script.index("cloud_git push original-cloud", push_loop)
    assert preflight_loop < plan_append < push_loop < push_command


def test_direct_document_commit_is_planned_for_registered_owner() -> None:
    node = Node(
        sha="document-sha",
        parent="cloud-sha",
        direct_files=(
            {"filename": "doc/07.会议记录/meeting.docx", "status": "added"},
        ),
    )

    assert simulate_preflight_then_push([node], "cloud-sha") == [
        "document-sha:CLOUD_TOKEN_SHEN_HUANG_123"
    ]


def test_direct_source_commit_fails_before_any_push() -> None:
    node = Node(
        sha="source-sha",
        parent="cloud-sha",
        direct_files=(
            {"filename": "src/api/app/main.py", "status": "modified"},
        ),
    )

    with pytest.raises(IDENTITY.IdentityError, match="非维护文档路径"):
        simulate_preflight_then_push([node], "cloud-sha")


def test_commit_with_pr_metadata_does_not_use_direct_allowlist() -> None:
    node = Node(
        sha="pr-sha",
        parent="cloud-sha",
        pr_login="Shen-huang-123",
        direct_files=(
            {"filename": "src/api/app/main.py", "status": "modified"},
        ),
    )

    # A PR-associated single-parent commit uses PR identity resolution; the
    # direct doc-only allowlist is not consulted.
    assert simulate_preflight_then_push([node], "cloud-sha") == [
        "pr-sha:CLOUD_TOKEN_SHEN_HUANG_123"
    ]


def test_non_contiguous_parent_fails_before_any_push() -> None:
    node = Node(
        sha="next-sha",
        parent="different-parent",
        direct_files=(
            {"filename": "doc/meeting.md", "status": "modified"},
        ),
    )

    with pytest.raises(ValueError, match="父节点不连续"):
        simulate_preflight_then_push([node], "cloud-sha")


def test_later_preflight_failure_prevents_earlier_push() -> None:
    nodes = [
        Node(
            sha="first-sha",
            parent="cloud-sha",
            direct_files=(
                {"filename": "docs/meeting.md", "status": "added"},
            ),
        ),
        Node(
            sha="second-sha",
            parent="first-sha",
            direct_files=(
                {"filename": "src/api/app/main.py", "status": "modified"},
            ),
        ),
    ]

    with pytest.raises(IDENTITY.IdentityError, match="非维护文档路径"):
        simulate_preflight_then_push(nodes, "cloud-sha")
