"""双仓库同步验证 — 确认 GitHub → 内部云端同步保留 SHA 和作者身份。

验证方式（合并后本地执行）：
1. git ls-remote 获取两端 master HEAD SHA，断言一致
2. git fetch + git log 获取两端提交作者姓名和邮箱，断言一致
3. 确认内部云端推送账号 ≠ 代码作者

CI 环境无法访问内部云端仓库，相关测试通过 pytest.skip 安全跳过。
"""

import os
import subprocess

import pytest

# GitHub Actions / CI 环境自动跳过远程验证
_IN_CI = (
    os.environ.get("CI", "").lower() == "true"
    or os.environ.get("GITHUB_ACTIONS", "") == "true"
)

# ── 本测试提交的预期身份 ──────────────────────────────────
EXPECTED_AUTHOR = "zhang"
EXPECTED_EMAIL = "z85963541@qq.com"
# 同一成员在不同时期使用过的 git user.name（身份以邮箱为准，显示名允许变化，
# 否则任何合法的后续整理提交都会让"最近一次提交作者"断言失效）
EXPECTED_AUTHOR_ALIASES = {"zhang", "Wind"}
# 合并后 GitHub master 上本提交的 SHA（由合并时确定，人工填入）
EXPECTED_SHA = os.environ.get("SYNC_VERIFY_EXPECTED_SHA", "")

GITHUB_REMOTE = "https://github.com/Meyt1n/issedu_ysu2026_3709.git"
CLOUD_REMOTE = "http://119.3.217.118:30181/29092881243490627/issedu_ysu2026_3709.git"
VERIFICATION_RECORD = "sync-test/identity-sync-verification.md"


def _git_ls_remote(url: str, ref: str = "refs/heads/master") -> str:
    """执行 git ls-remote，返回 HEAD SHA 或空字符串。"""
    try:
        result = subprocess.run(
            ["git", "ls-remote", url, ref],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if result.returncode != 0:
            return ""
        lines = result.stdout.strip().split("\n")
        for line in lines:
            if line.endswith(ref):
                return line.split("\t")[0]
        return ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _git_cat_file_author(repo_url: str, sha: str) -> tuple[str, str]:
    """通过 git fetch + cat-file 获取指定提交的作者姓名和邮箱。

    返回 (author_name, author_email)，失败返回空字符串。
    """
    try:
        # fetch the specific commit
        subprocess.run(
            ["git", "fetch", "--no-tags", repo_url, sha],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        # read author name
        name_result = subprocess.run(
            ["git", "log", "-1", "--format=%an", sha],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        email_result = subprocess.run(
            ["git", "log", "-1", "--format=%ae", sha],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if name_result.returncode != 0 or email_result.returncode != 0:
            return "", ""
        return name_result.stdout.strip(), email_result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return "", ""


# ── 本地验证测试 ──────────────────────────────────────────


def test_github_cloud_master_sha_match() -> None:
    """两端 master HEAD SHA 必须完全一致。

    环境变量：
        SYNC_VERIFY_EXPECTED_SHA — 预期的合并后提交 SHA
    """
    if _IN_CI:
        pytest.skip("CI 环境无法访问内部云端，跳过远程 SHA 比对")
    github_sha = _git_ls_remote(GITHUB_REMOTE)
    cloud_sha = _git_ls_remote(CLOUD_REMOTE)

    if not cloud_sha:
        pytest.skip("无法访问内部云端仓库（CI 环境或网络不通），跳过远程 SHA 比对")

    assert github_sha, f"无法获取 GitHub master SHA：{GITHUB_REMOTE}"
    assert github_sha == cloud_sha, (
        f"SHA 不一致！\n"
        f"  GitHub: {github_sha}\n"
        f"  云端:    {cloud_sha}"
    )
    print(f"SHA 一致：{github_sha}")

    if EXPECTED_SHA:
        assert github_sha == EXPECTED_SHA, (
            f"合并后 SHA 与预期不符：expected={EXPECTED_SHA[:12]} actual={github_sha[:12]}"
        )


def test_sync_preserves_commit_author_identity() -> None:
    """同步后提交作者姓名和邮箱与原始提交一致。

    依赖 test_github_cloud_master_sha_match 已确认 SHA 一致，
    本测试拉取该提交并比对两端 author 信息。
    """
    if _IN_CI:
        pytest.skip("CI 环境无法访问内部云端，跳过 author 身份比对")
    github_sha = _git_ls_remote(GITHUB_REMOTE)
    if not github_sha:
        pytest.skip("无法获取 GitHub master SHA")

    cloud_sha = _git_ls_remote(CLOUD_REMOTE)
    if not cloud_sha:
        pytest.skip("无法访问内部云端仓库，跳过 author 身份比对")

    if github_sha != cloud_sha:
        pytest.skip("两端 SHA 不一致，跳过 author 比对（先修 SHA 问题）")

    # 获取两端作者信息
    gh_name, gh_email = _git_cat_file_author(GITHUB_REMOTE, github_sha)
    cl_name, cl_email = _git_cat_file_author(CLOUD_REMOTE, cloud_sha)

    assert gh_name, f"无法从 GitHub 获取提交 {github_sha[:12]} 的作者信息"
    assert cl_name, f"无法从云端获取提交 {cloud_sha[:12]} 的作者信息"

    assert gh_name == cl_name, (
        f"作者姓名不一致：GitHub={gh_name}，云端={cl_name}"
    )
    assert gh_email == cl_email, (
        f"作者邮箱不一致：GitHub={gh_email}，云端={cl_email}"
    )

    print(f"作者身份一致：{gh_name} <{gh_email}>")

    # 如果指定了预期 SHA，额外验证该提交的作者身份
    if EXPECTED_SHA:
        assert github_sha == EXPECTED_SHA, "SHA 与预期不符，跳过身份断言"
        assert gh_name == EXPECTED_AUTHOR, (
            f"作者姓名与预期不符：expected={EXPECTED_AUTHOR} actual={gh_name}"
        )
        assert gh_email == EXPECTED_EMAIL, (
            f"作者邮箱与预期不符：expected={EXPECTED_EMAIL} actual={gh_email}"
        )


# ── 静态自检 — 始终运行 ──────────────────────────────────

def test_expected_author_is_not_sync_account() -> None:
    """确认预期作者不是同步专用推送账号。"""
    # 同步推送账号通常是 bot 或 service account 格式
    sync_patterns = ["bot", "service", "sync", "ci", "github-actions", "noreply"]
    lower_author = EXPECTED_AUTHOR.lower()
    lower_email = EXPECTED_EMAIL.lower()
    for pattern in sync_patterns:
        assert pattern not in lower_author, (
            f"作者姓名包含疑似同步账号关键词：{pattern}"
        )
        assert pattern not in lower_email, (
            f"作者邮箱包含疑似同步账号关键词：{pattern}"
        )


def test_author_email_format_valid() -> None:
    """预期作者邮箱格式合法。"""
    assert "@" in EXPECTED_EMAIL, f"邮箱格式无效：{EXPECTED_EMAIL}"
    local, domain = EXPECTED_EMAIL.split("@", 1)
    assert local and domain, f"邮箱格式无效：{EXPECTED_EMAIL}"
    assert "." in domain, f"邮箱域名无效：{EXPECTED_EMAIL}"


def test_github_remote_reachable() -> None:
    """GitHub 远程仓库可达时，返回的 SHA 必须格式正确。

    网络不通不是代码缺陷：离线、内网或代理环境下应跳过，而不是让整个单元测试
    套件变红（本文件其余远程用例已是这个语义，见 ``test_github_cloud_master_sha_match``）。
    真正值得断言的是——连得上时返回的必须是合法 SHA。
    """
    if _IN_CI:
        pytest.skip("CI 环境跳过连通性检查")
    sha = _git_ls_remote(GITHUB_REMOTE)
    if not sha:
        pytest.skip(f"无法访问 GitHub 仓库（离线或网络受限），跳过连通性检查：{GITHUB_REMOTE}")
    assert len(sha) == 40, f"SHA 长度异常：{len(sha)}"


def test_cloud_remote_configured() -> None:
    """验证 cloud remote 已配置（本地开发环境）。"""
    result = subprocess.run(
        ["git", "remote", "get-url", "cloud"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    if result.returncode != 0:
        pytest.skip("cloud remote 未配置，跳过（CI 环境正常）")
    assert CLOUD_REMOTE in result.stdout, (
        f"cloud remote URL 不匹配：expected={CLOUD_REMOTE} actual={result.stdout.strip()}"
    )


def test_verification_record_committed_by_correct_author() -> None:
    """自检：同步验证记录由预期成员维护。

    身份锚点是提交邮箱；git user.name 允许在该成员的已知别名内变化
    （历史上同一成员先后使用过 zhang / Wind 两个显示名）。
    """
    if _IN_CI:
        pytest.skip("CI 环境跳过本地 git log 自检")
    result = subprocess.run(
        ["git", "log", "-1", "--format=%an|%ae", "--", VERIFICATION_RECORD],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    if result.returncode != 0:
        pytest.skip("无法执行 git log")
    output = result.stdout.strip()
    if "|" not in output:
        pytest.skip("git log 输出格式异常")
    author_name, author_email = output.split("|", 1)
    assert author_email == EXPECTED_EMAIL, (
        f"本文件提交邮箱与预期不符：expected={EXPECTED_EMAIL} actual={author_email}"
    )
    assert author_name in EXPECTED_AUTHOR_ALIASES, (
        f"本文件提交作者不在预期成员别名内："
        f"expected_any={sorted(EXPECTED_AUTHOR_ALIASES)} actual={author_name}"
    )
