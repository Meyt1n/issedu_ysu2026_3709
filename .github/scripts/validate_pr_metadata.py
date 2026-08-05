"""Validate the minimum task and risk metadata required by a pull request.

This check is deliberately deterministic. It validates the PR contract and
does not attempt to decide whether the implementation is functionally correct;
that is the responsibility of CI, Codex Review, and human reviewers.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


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
    return bool(cleaned.strip()) and not bool(
        re.fullmatch(r"(?:tbd|todo|待补充|见上文|none|n/?a|不适用)\s*", cleaned.strip(), re.I)
    )


def main() -> int:
    if not EVENT_PATH.is_file():
        fail(f"找不到 GitHub PR 事件文件：{EVENT_PATH}")
        return 1

    event = json.loads(EVENT_PATH.read_text(encoding="utf-8"))
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

    story_match = re.search(r"(?im)^\s*-\s*Story\s*[:：]\s*(HCT-\d{3})\b", body)
    if not story_match:
        errors.append("PR 必须填写 Story，例如：- Story：HCT-102。")
    else:
        story_id = story_match.group(1)
        story_files = list((ROOT / "docs" / "stories").glob(f"{story_id}-*.md"))
        if not story_files:
            errors.append(f"找不到 Story 文件：docs/stories/{story_id}-*.md。")

    for heading in ("验收标准", "测试证据", "人工验收/演示证据", "部署、迁移和回滚"):
        if not meaningful(section_content(body, heading)):
            errors.append(f"必须填写“{heading}”部分，不能只留模板或写 TBD/TODO。")

    required_markers = (
        "已阅读[开发前必读与 Vibe Coding 工作流]",
        "未提交真实健康数据、药品图片、密钥、模型权重、缓存或运行日志",
        "已说明权限、撤权、审计、数据删除和网络出口影响",
        "高风险变更已指定第二位人工复核人，或已明确说明不适用",
        "需求追踪矩阵已更新，或已说明本 PR 不改变需求状态",
        "Codex Review 已完成，或已说明账号侧尚未启用及替代复核方式",
    )
    for marker in required_markers:
        checkbox = re.search(rf"(?im)^-\s*\[([ xX])\]\s*{re.escape(marker)}", body)
        if not checkbox or checkbox.group(1).lower() != "x":
            errors.append(f"必须勾选：{marker}。")

    if errors:
        print("PR 任务与风险门禁未通过：")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        "PR 任务与风险门禁通过："
        f"Issue #{closing_refs[0]}，Story {story_match.group(1)}。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
