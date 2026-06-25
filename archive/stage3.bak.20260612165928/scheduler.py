"""
Stage 3 APScheduler integration.

Two scheduled jobs:
  - stage3_daily        : runs every day at 03:00 UTC (after Stage 2's
                          02:00 crawl), triggers the full extraction cycle.
  - daily_status_refresh: runs every day at 01:00, re-evaluates computed
                          statuses for records whose deadlines have passed.

Run this module directly to start the scheduler in a blocking loop:

    python -m stage3.scheduler

In production, Stage 3 is co-located with Stage 2's APScheduler instance.
If Stage 2 exposes a shared scheduler object, import it there instead.
"""

import structlog
from apscheduler.schedulers.blocking import BlockingScheduler

from stage3.batch_processor import run_extraction_cycle
from stage3.db import get_connection
from stage3.status_refresh import run_status_refresh

log = structlog.get_logger(__name__)

scheduler = BlockingScheduler(timezone="UTC")


# ---------------------------------------------------------------------------
# Scheduled jobs
# ---------------------------------------------------------------------------


@scheduler.scheduled_job("cron", hour=3, id="stage3_daily")
def stage3_daily() -> None:
    """Daily Stage 3 extraction cycle.

    Runs every day at 03:00 UTC, one hour after Stage 2's 02:00 UTC crawl
    and four hours before the 07:00 UTC GitHub Actions export.  Stage 2
    does not write the crawl_complete sentinel file, so STAGE3_FORCE=1 must
    be set in the service environment (a systemd drop-in provides it); the
    env check below honours it.
    """
    import os
    force = os.environ.get("STAGE3_FORCE", "").lower() in ("1", "true", "yes")
    log.info("stage3_daily_triggered", force=force)
    try:
        run_extraction_cycle(force=force)
    except Exception:
        log.exception("stage3_daily_failed")


@scheduler.scheduled_job("cron", hour=1, id="daily_status_refresh")
def daily_status_refresh() -> None:
    """Daily status recalculation job.

    Runs every day at 01:00 UTC.  Promotes Upcoming grants whose opening date
    has arrived to Open, and closes Open grants whose deadline has passed.
    Only records with status_source = 'computed' are affected.
    """
    log.info("daily_status_refresh_triggered")
    try:
        conn = get_connection()
        try:
            run_status_refresh(conn)
        finally:
            conn.close()
    except Exception:
        log.exception("daily_status_refresh_failed")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Start the blocking scheduler (runs until interrupted with Ctrl-C)."""
    log.info("scheduler_starting", jobs=[j.id for j in scheduler.get_jobs()])
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("scheduler_stopped")


if __name__ == "__main__":
    main()
