"""Local HCT-308 worker for authorized medication-plan lifecycle automation."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.care_plan import execute_plan_automation
from app.config import get_settings
from app.db import SessionLocal
from app.models import Household, Member


@dataclass(frozen=True)
class AutomationSummary:
    inspected_members: int = 0
    created_events: int = 0
    notified_caregivers: int = 0
    failed_members: int = 0


def automation_cycle(session: Session, *, now: datetime | None = None) -> AutomationSummary:
    evaluated_at = now or datetime.now(UTC)
    rows = session.execute(
        select(Household, Member)
        .join(Member, Member.household_id == Household.id)
        .where(Household.deleted_at.is_(None), Member.deleted_at.is_(None))
        .order_by(Household.id, Member.id)
    ).all()
    created_count = 0
    notified_count = 0
    failed_count = 0
    for household, member in rows:
        try:
            events, notified = execute_plan_automation(
                session,
                household=household,
                member=member,
                actor_id="system:hct308",
                correlation_id=f"hct308-worker:{evaluated_at.isoformat()}",
                now=evaluated_at,
            )
        except Exception:
            session.rollback()
            failed_count += 1
            continue
        created_count += len(events)
        notified_count += len(notified)
    return AutomationSummary(
        inspected_members=len(rows),
        created_events=created_count,
        notified_caregivers=notified_count,
        failed_members=failed_count,
    )


def run_worker(*, loop: bool, ready_file: Path) -> int:
    settings = get_settings()
    while True:
        try:
            with SessionLocal() as session:
                summary = automation_cycle(session)
            ready_file.parent.mkdir(parents=True, exist_ok=True)
            ready_file.write_text("ready\n", encoding="ascii")
            if summary.created_events or summary.failed_members:
                print(
                    json.dumps(
                        {"event": "care_plan_automation_cycle", **asdict(summary)},
                        ensure_ascii=True,
                        sort_keys=True,
                    ),
                    flush=True,
                )
        except Exception:
            print(
                json.dumps(
                    {"event": "care_plan_automation_failed", "error": "WORKER_CYCLE_FAILED"}
                ),
                flush=True,
            )
            if not loop:
                return 1
        if not loop:
            return 0
        time.sleep(settings.care_plan_poll_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate authorized HomeCare Twin medication plans"
    )
    parser.add_argument("--loop", action="store_true", help="Continue polling after each cycle")
    parser.add_argument(
        "--ready-file",
        type=Path,
        default=Path("./tmp/hct308-care-plan-worker.ready"),
    )
    args = parser.parse_args()
    return run_worker(loop=args.loop, ready_file=args.ready_file)


if __name__ == "__main__":
    raise SystemExit(main())
