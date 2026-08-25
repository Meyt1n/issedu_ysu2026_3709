"""HCT-439 阶段五：安全清理明确标记的演示/测试家庭数据。

只删除带显式演示标记的家庭：创建者账号或家庭名称以 ``demo-`` / ``test-``
开头，或家庭名称包含「本地演示」「教学演示」。判断规则与前端
``src/web/src/ui/demoData.ts`` 保持一致，绝不做模糊匹配，避免误删真实
家庭数据。

默认 dry-run：只打印将被清理的家庭清单，不改动任何数据。加 ``--apply``
才会通过既有的 HCT-405 擦除服务逐个删除（数据库、文件、向量、缓存、
困难样本、备份跳过标记和审计全链路传播）。生产环境直接拒绝执行。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parents[1]
for source_path in (REPO_ROOT / "src/api", REPO_ROOT / "src"):
    source = str(source_path)
    if source not in sys.path:
        sys.path.insert(0, source)

from app.config import get_settings  # noqa: E402
from app.models import Household, Member  # noqa: E402

CLEANUP_ACTOR = "demo-cleanup-script"
DEMO_PREFIXES = ("demo-", "test-")
DEMO_NAME_MARKERS = ("本地演示", "教学演示")


def is_demo_household(household: Household) -> bool:
    """只认显式标记：demo-/test- 前缀或名称中的演示字样。"""
    created_by = (household.created_by or "").casefold()
    name = household.name or ""
    if created_by.startswith(DEMO_PREFIXES):
        return True
    if name.casefold().startswith(DEMO_PREFIXES):
        return True
    return any(marker in name for marker in DEMO_NAME_MARKERS)


def find_demo_households(session: Session) -> list[Household]:
    households = session.scalars(
        select(Household).where(Household.deleted_at.is_(None)).order_by(Household.created_at)
    ).all()
    return [household for household in households if is_demo_household(household)]


def describe_household(session: Session, household: Household) -> dict[str, Any]:
    member_count = (
        session.scalar(
            select(func.count())
            .select_from(Member)
            .where(Member.household_id == household.id, Member.deleted_at.is_(None))
        )
        or 0
    )
    return {
        "household_id": household.id,
        "name": household.name,
        "created_by": household.created_by,
        "member_count": int(member_count),
    }


def cleanup_demo_households(session: Session, *, apply: bool) -> dict[str, Any]:
    """Return the cleanup plan; propagate erasure only when ``apply`` is True."""
    from app.erasure import request_household_erasure

    candidates = find_demo_households(session)
    plan = [describe_household(session, household) for household in candidates]
    results: list[dict[str, Any]] = []
    if apply:
        for household, item in zip(candidates, plan, strict=True):
            task = request_household_erasure(session, household, actor_id=CLEANUP_ACTOR)
            results.append(
                {
                    **item,
                    "erasure_task_id": task.id,
                    "erasure_status": task.status,
                    "error_layers": list(task.error_layers or []),
                }
            )
        session.commit()
    return {
        "dry_run": not apply,
        "matched": len(plan),
        "plan": plan,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="安全清理明确标记为 demo-/test- 的演示家庭数据（默认 dry-run）",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="实际执行清理；缺省只打印将被删除的家庭清单",
    )
    args = parser.parse_args()

    settings = get_settings()
    if settings.app_env.strip().casefold() in {"prod", "production"}:
        print("REFUSED: 生产环境禁止运行演示数据清理脚本。", file=sys.stderr)
        return 2

    from app.db import SessionLocal

    with SessionLocal() as session:
        report = cleanup_demo_households(session, apply=args.apply)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["dry_run"] and report["matched"]:
        print(
            f"dry-run：找到 {report['matched']} 个演示家庭，未做任何修改；"
            "确认清单无误后加 --apply 执行。",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
