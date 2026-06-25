"""
GrantGlobe crawl scheduler — spec §2.9 Scheduling.

Runs two recurring jobs using APScheduler 3.x (BlockingScheduler):

  daily_crawl   — every day at 02:00 UTC (high-activity domains)
  weekly_crawl  — every Sunday at 02:05 UTC (full crawl, all domains)

The daily job also fires on Sunday so Sunday sees two crawl runs.  The
5-minute offset prevents them from launching simultaneously.

On-demand single-domain crawls are supported via _run_triggered(domain).
Manifests with triggered_recrawl_after_change=True are handled by the
scheduler operator (or a future watcher job) calling _run_triggered().

Usage:
    python -m grantglobe_crawler.scheduler.crawl_scheduler
    # or
    from grantglobe_crawler.scheduler.crawl_scheduler import build_scheduler
    scheduler = build_scheduler()
    scheduler.start()
"""

from __future__ import annotations

import logging
import subprocess

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

UTC = pytz.utc


# ---------------------------------------------------------------------------
# Job functions
# ---------------------------------------------------------------------------


def _run_scrapy(extra_args: list[str] | None = None) -> None:
    """
    Launch ``scrapy crawl grants`` in a subprocess.

    *extra_args* are appended (e.g. ``["-s", "SINGLE_DOMAIN=example.org"]``).
    Blocks until the subprocess completes.
    """
    cmd = ["scrapy", "crawl", "grants"] + (extra_args or [])
    logger.info("Launching: %s", " ".join(cmd))
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        logger.error("scrapy crawl exited with code %d", result.returncode)


def _run_daily() -> None:
    """
    Daily crawl job.

    In the current prototype this runs the full crawl for all domains.
    A future targeted mode will filter to daily-scheduled domains only
    by reading crawl_frequency from each domain's manifest.
    """
    _run_scrapy()


def _run_weekly() -> None:
    """Weekly full crawl — all domains."""
    _run_scrapy()


def _run_triggered(domain: str) -> None:
    """On-demand single-domain crawl (e.g. after a change-triggered re-crawl)."""
    _run_scrapy(["-s", f"SINGLE_DOMAIN={domain}"])


# ---------------------------------------------------------------------------
# Scheduler factory
# ---------------------------------------------------------------------------


def build_scheduler() -> BlockingScheduler:
    """
    Construct and return the configured scheduler (not yet started).

    Jobs
    ----
    daily_crawl
        Every day at 02:00 UTC.  ``coalesce=True`` collapses any misfired
        runs into a single execution; ``misfire_grace_time=3600`` allows
        up to one hour of lateness.

    weekly_crawl
        Every Sunday at 02:05 UTC.  The 5-minute offset from the daily job
        prevents simultaneous launches on Sunday mornings.

    Returns
    -------
    BlockingScheduler
        A fully configured scheduler ready to call ``.start()`` on.
    """
    scheduler = BlockingScheduler(timezone=UTC)

    scheduler.add_job(
        _run_daily,
        CronTrigger(hour=2, minute=0, timezone=UTC),
        id="daily_crawl",
        name="Daily crawl (high-activity domains)",
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        _run_weekly,
        CronTrigger(day_of_week="sun", hour=2, minute=5, timezone=UTC),
        id="weekly_crawl",
        name="Weekly full crawl (all domains)",
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=1,
    )

    return scheduler


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Start the blocking scheduler."""
    logging.basicConfig(level=logging.INFO)
    scheduler = build_scheduler()
    logger.info(
        "GrantGlobe scheduler starting — weekly Sunday 02:05 UTC, daily 02:00 UTC"
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    main()
