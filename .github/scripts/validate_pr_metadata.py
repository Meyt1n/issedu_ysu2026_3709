"""Validate the minimum task and risk metadata required by a pull request.

This check is deliberately deterministic. It validates the PR contract and
    does not attempt to decide whether the implementation is functionally correct;
    that is the responsibility of CI, Relay Review Bot, and human reviewers.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
EVENT_PATH = Path(os.environ.get("PR_EVENT_PATH", ""))


def fail(message: str) -> None:
    print(f"::error::{message}")


def section_content(body: str, heading: str) -> str:
    pattern = rf"(?ms)^###\s+{re.escape(heading)}\s*$\n(.*?)(?=^###\s+|^##\s+|\Z)"
    match = re.search(pattern, body)
    return match.group(1).strip() if match else ""


def meaningful(value: str) -> bool:
    cleaned = re.sub(r"<!--.*?-->", "", value, flags=re.DOTALL)
    cleaned = re.sub(r"[`*_>#\-]", "", cleaned)
    normalized = cleaned.strip()
    if not normalized:
        return False
    if re.search(
        r"(?:\b(?:tbd|todo|pending|fill\s+in)\b|待补充|见上文|待(?:项目组)?指定|尚未指定|待确认|待填写)",
        normalized,
        re.I,
    ):
        return False
    if re.fullmatch(r"(?:none|n/?a|不适用)\s*", normalized, re.I):
        return False
    pass_only = normalized.strip(" .。!！?？;；:：")
    return not bool(
        re.fullmatch(r"(?:通过|pass(?:ed)?|ok|success(?:ful)?|已完成)", pass_only, re.I)
    )


def field_content(body: str, label: str) -> str:
    pattern = rf"(?im)^[ \t]*-[ \t]*{re.escape(label)}[ \t]*[:：][ \t]*([^\r\n]*)[ \t]*$"
    match = re.search(pattern, body)
    return match.group(1).strip() if match else ""


def github_issue_exists(repository: str, issue_number: str) -> tuple[bool, str]:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return False, "缺少 GITHUB_TOKEN，无法验证 Issue 是否存在。"

    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    endpoint = f"{api_url}/repos/{quote(repository, safe='/')}/issues/{issue_number}"
    request = Request(
        endpoint,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=10) as response:
            payload = json.load(response)
    except HTTPError as exc:
        if exc.code == 404:
            return False, f"找不到 Issue #{issue_number}。"
        return False, f"GitHub Issue 校验失败（HTTP {exc.code}）。"
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        return False, f"GitHub Issue 校验失败：{exc.__class__.__name__}。"

    if payload.get("pull_request"):
        return False, f"#{issue_number} 是 Pull Request，不是任务 Issue。"
    return True, ""


def validate_event(event: dict) -> list[str]:
    pull_request = event.get("pull_request") or {}
    body = pull_request.get("body") or ""
    errors: list[str] = []

    closing_refs = sorted(
        set(
            re.findall(
                r"(?im)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s*#(\d+)\b",
                body,
            )
        )
    )
    if len(closing_refs) != 1:
        errors.append(
            "PR 必须使用一个且仅一个 Closes/Fixes/Resolves #<Issue> 任务引用；"
            f"当前发现 {len(closing_refs)} 个。"
        )
    else:
        repository = (event.get("repository") or {}).get("full_name")
        if not repository:
            errors.append("PR 事件缺少仓库标识，无法验证任务 Issue。")
        else:
            issue_ok, issue_error = github_issue_exists(repository, closing_refs[0])
            if not issue_ok:
                errors.append(issue_error)

    story_match = re.search(r"(?im)^\s*-\s*Story\s*[:：]\s*(HCT-\d{3})\b", body)
    if not story_match:
        errors.append("PR 必须填写 Story，例如：- Story：HCT-102。")
    else:
        story_id = story_match.group(1)
        story_files = list((ROOT / "docs" / "stories").glob(f"{story_id}-*.md"))
        if not story_files:
            errors.append(f"找不到 Story 文件：docs/stories/{story_id}-*.md。")

    fr_nfr_match = re.search(
        r"(?im)^[ \t]*-[ \t]*FR/NFR[ \t]*[:：][ \t]*([^\r\n]*)[ \t]*$", body
    )
    fr_nfr_value = fr_nfr_match.group(1) if fr_nfr_match else ""
    if not meaningful(fr_nfr_value) or not re.search(
        r"\b(?:FR|NFR)-\d+\b", fr_nfr_value, re.I
    ):
        errors.append("PR 必须填写至少一个有效的 FR/NFR 编号，例如：- FR/NFR：NFR-04、NFR-06。")

    for label in ("负责人", "复核人", "变更范围", "明确不做"):
        if not meaningful(field_content(body, label)):
            errors.append(f"PR 必须填写“{label}”，不能留空或使用占位词。")

    for heading in ("验收标准", "测试证据", "人工验收/演示证据", "部署、迁移和回滚"):
        if not meaningful(section_content(body, heading)):
            errors.append(f"必须填写“{heading}”部分，不能只留模板或写 TBD/TODO。")

    workflow_marker = (
        "已阅读[开发前必读与 Vibe Coding 工作流](../docs/vibe-coding/"
        "开发前必读与Vibe%20Coding工作流.md)和[PR 任务关联与 Relay Review Bot "
        "工作流](../docs/vibe-coding/PR任务关联与Relay%20Review%20Bot%20工作流.md)"
    )
    recognition_marker = (
        "已确认：未确认的视觉识别结果不会进入正式健康状态、风险计算或药物计划；"
        "只有多证据匹配且人工确认后才可入库"
    )
    required_markers = (
        workflow_marker,
        "未提交真实健康数据、药品图片、密钥、模型权重、缓存或运行日志",
        "已说明权限、撤权、审计、数据删除和网络出口影响",
        "已说明 AI 使用、人工复核、证据来源和已知限制",
        "没有诊断、处方、停药、换药、买药、问诊、广告或佣金导流",
        recognition_marker,
        "高风险变更已指定第二位人工复核人，或已明确说明不适用",
        "需求追踪矩阵已更新，或已说明本 PR 不改变需求状态",
        "相关 API、OpenAPI、迁移、测试和文档已同步，或已说明不适用",
        "Relay Review Bot 已完成，或已说明未配置中转服务及替代复核方式",
    )
    for marker in required_markers:
        checkbox = re.search(
            rf"(?im)^[ \t]*-[ \t]*\[([ xX])\][ \t]*{re.escape(marker)}[ \t]*$",
            body,
        )
        if not checkbox or checkbox.group(1).lower() != "x":
            errors.append(f"必须勾选：{marker}。")

    return errors


def main() -> int:
    if not EVENT_PATH.is_file():
        fail(f"找不到 GitHub PR 事件文件：{EVENT_PATH}")
        return 1

    event = json.loads(EVENT_PATH.read_text(encoding="utf-8"))
    errors = validate_event(event)

    if errors:
        print("PR 任务与风险门禁未通过：")
        for error in errors:
            print(f"- {error}")
        return 1

    pull_request = event.get("pull_request") or {}
    body = pull_request.get("body") or ""
    story_match = re.search(r"(?im)^\s*-\s*Story\s*[:：]\s*(HCT-\d{3})\b", body)
    print(f"PR 任务与风险门禁通过：Story {story_match.group(1)}。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
