import argparse
import json
import time
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.event_service import DispatchSummary, dispatch_outbox_batch
from app.models import HealthEvent, OutboxMessage


def dispatch_cycle(session: Session) -> DispatchSummary:
    settings = get_settings()
    household_ids = list(
        session.scalars(
            select(distinct(HealthEvent.household_id))
            .join(OutboxMessage, OutboxMessage.event_id == HealthEvent.id)
            .where(OutboxMessage.status.in_(["PENDING", "FAILED", "PROCESSING"]))
        ).all()
    )
    totals = DispatchSummary()
    for household_id in household_ids:
        current = dispatch_outbox_batch(
            session,
            household_id=household_id,
            max_messages=settings.outbox_batch_size,
            stale_after=timedelta(seconds=settings.outbox_stale_seconds),
        )
        totals = DispatchSummary(
            inspected=totals.inspected + current.inspected,
            dispatched=totals.dispatched + current.dispatched,
            failed=totals.failed + current.failed,
            out_of_order=totals.out_of_order + current.out_of_order,
            recovered_stale=totals.recovered_stale + current.recovered_stale,
        )
    return totals


def run_worker(*, loop: bool, ready_file: Path) -> int:
    settings = get_settings()
    while True:
        try:
            with SessionLocal() as session:
                summary = dispatch_cycle(session)
            ready_file.write_text("ready\n", encoding="ascii")
            if any(asdict(summary).values()):
                print(
                    json.dumps(
                        {"event": "outbox_cycle", **asdict(summary)},
                        ensure_ascii=True,
                        sort_keys=True,
                    ),
                    flush=True,
                )
        except Exception:
            print(
                json.dumps({"event": "outbox_cycle_failed", "error": "WORKER_CYCLE_FAILED"}),
                flush=True,
            )
            if not loop:
                return 1
        if not loop:
            return 0
        time.sleep(settings.outbox_poll_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Process recoverable HomeCare Twin outbox messages"
    )
    parser.add_argument("--loop", action="store_true", help="Continue polling after each cycle")
    parser.add_argument(
        "--ready-file",
        type=Path,
        default=Path("/tmp/homecare-outbox-worker.ready"),
    )
    args = parser.parse_args()
    return run_worker(loop=args.loop, ready_file=args.ready_file)


if __name__ == "__main__":
    raise SystemExit(main())
