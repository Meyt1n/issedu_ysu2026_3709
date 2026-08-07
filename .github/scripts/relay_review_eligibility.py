"""Decide whether Relay Review Bot should spend a model request on a PR.

Only the dedicated Issue field is considered. This prevents an incidental
``Closes #...`` in acceptance examples or comments from opting a PR in.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

EVENT_PATH = Path(os.environ.get("PR_EVENT_PATH", os.environ.get("GITHUB_EVENT_PATH", "")))


def issue_field(body: str) -> str:
    match = re.search(
        r"(?im)^[ \t]*-[ \t]*Issue[ \t]*[:：][ \t]*([^\r\n]*)[ \t]*$", body
    )
    return match.group(1).strip() if match else ""


def has_bound_issue(body: str) -> bool:
    value = issue_field(body)
    return bool(
        re.search(
            r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s*#\d+\b",
            value,
        )
    )


def main() -> int:
    if not EVENT_PATH.is_file():
        print(f"::error::找不到 GitHub PR 事件文件：{EVENT_PATH}")
        return 1
    event = json.loads(EVENT_PATH.read_text(encoding="utf-8"))
    body = ((event.get("pull_request") or {}).get("body") or "")
    required = has_bound_issue(body)
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as handle:
            handle.write(f"review_required={'true' if required else 'false'}\n")
    if required:
        print("PR 绑定了 Issue，Relay Review Bot 将运行。")
    else:
        print("PR 未在专用 Issue 字段绑定任务，Relay Review Bot 跳过且不调用中转 API。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
