"""
Full Stage 3 backfill runner.

Iterates over every crawl date present in raw_cache (directory names of the
form raw_cache/{domain}/{YYYY-MM-DD}/), registers and processes pending
pages for each date, and repeats until no pending rows remain. Designed to
run once under nohup to clear the backlog; the daily scheduler handles all
subsequent days automatically.
"""

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, "/opt/grantglobe/Stage_3_LLM_extraction")

from stage3.batch_processor import run_extraction_cycle  # noqa: E402
from stage3.db import get_connection  # noqa: E402

RAW_CACHE = Path(os.environ.get(
    "RAW_CACHE_DIR", "/opt/grantglobe/Stage_2_crawler/raw_cache"
))
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
MAX_PASSES = 60  # hard safety ceiling


def crawl_dates() -> list[str]:
    dates: set[str] = set()
    for domain_dir in RAW_CACHE.iterdir():
        if not domain_dir.is_dir():
            continue
        for sub in domain_dir.iterdir():
            if sub.is_dir() and DATE_RE.fullmatch(sub.name):
                dates.add(sub.name)
    return sorted(dates)


def pending_by_date() -> dict[str, int]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT crawl_date::text, COUNT(*) FROM extraction_log "
                "WHERE status = 'pending' GROUP BY crawl_date"
            )
            return {r[0]: r[1] for r in cur.fetchall()}
    finally:
        conn.close()


def main() -> int:
    dates = crawl_dates()
    print(f"crawl dates found in raw_cache: {dates}", flush=True)

    # Pass 1 — one cycle per date so every date's pages get registered.
    for ds in dates:
        print(f"=== initial cycle for {ds} ===", flush=True)
        try:
            stats = run_extraction_cycle(force=True, run_date=ds)
            print(f"    stats: {stats}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"    cycle for {ds} errored: {exc}", flush=True)

    # Subsequent passes — drain whatever remains pending, date by date.
    for n in range(MAX_PASSES):
        remaining = pending_by_date()
        total = sum(remaining.values())
        print(f"=== pass {n + 2}: {total} pending {remaining} ===", flush=True)
        if total == 0:
            break
        for ds, count in sorted(remaining.items()):
            print(f"--- {ds}: {count} pending ---", flush=True)
            try:
                stats = run_extraction_cycle(force=True, run_date=ds)
                print(f"    stats: {stats}", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"    cycle for {ds} errored: {exc}", flush=True)

    print("FULL EXTRACTION RUN COMPLETE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
