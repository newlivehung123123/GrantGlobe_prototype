"""
Stage 3 LLM Extraction Pipeline — command-line entry point.

Usage:
    python -m stage3 --date 2026-05-23             # extract a specific cycle
    python -m stage3 --date 2026-05-23 --force     # bypass Stage 2 sentinel
    python -m stage3 --dry-run                     # estimate cost, no API calls
    python -m stage3 --status-refresh              # run daily status refresh manually

All flags can be combined freely (e.g. --date with --force, --dry-run with --date).
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Gemini pricing constants (§5.3)
# ---------------------------------------------------------------------------

_INPUT_PRICE_PER_M = 1.50       # USD per million input tokens
_OUTPUT_PRICE_PER_M = 9.00      # USD per million output tokens
_BATCH_DISCOUNT = 0.50          # 50 % Batch API discount on both input and output
_ESTIMATED_OUTPUT_RATIO = 0.15  # estimated output ≈ 15 % of input tokens


# ---------------------------------------------------------------------------
# Dry-run helpers
# ---------------------------------------------------------------------------


def _scan_meta_files(raw_cache_dir: Path, run_date: str) -> list[Path]:
    """Walk raw_cache_dir and return .meta.json paths for changed pages
    matching *run_date* — identical criteria to scan_for_pending_pages
    but without any database interaction."""
    matches: list[Path] = []
    for meta_path in sorted(raw_cache_dir.rglob("*.meta.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not meta.get("changed", False):
            continue
        if str(meta.get("crawl_date", "")) != run_date:
            continue
        matches.append(meta_path)
    return matches


def _run_dry_run(raw_cache_dir: str, run_date: str) -> int:
    """Scan raw_cache, count tokens for each prepared page, print cost summary.

    No database writes.  No LLM batch submission.  count_tokens() API calls
    ARE made (these are lightweight but not free) — their cost is reported
    separately in the summary.

    Returns:
        0 if estimated cost is within STAGE3_MAX_COST (or no ceiling set).
        1 if estimated cost exceeds the ceiling.
    """
    from stage3.batch_processor import (
        prepare_html_page,
        prepare_pdf_page,
        _count_tokens,
    )
    from stage3.extractor import MODEL_NAME

    cache_path = Path(raw_cache_dir)
    if not cache_path.exists():
        print(f"DRY RUN: raw_cache_dir not found: {cache_path}", file=sys.stderr)
        print("\nDRY RUN SUMMARY")
        print(f"  Pages found:          0")
        print(f"  Pages below minimum:  0")
        print(f"  Estimated tokens:     0 input")
        print(f"  Estimation API cost:  $0.0000")
        print(f"  Estimated batch cost: $0.0000")
        _print_cost_ceiling(0.0)
        return 0

    meta_files = _scan_meta_files(cache_path, run_date)
    pages_found = len(meta_files)

    total_input_tokens = 0
    pages_below_min = 0
    page_costs_for_estimation = 0.0  # each count_tokens() call

    for meta_path in meta_files:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pages_below_min += 1
            continue

        is_pdf = meta.get("is_pdf", False)

        if is_pdf:
            text, reason = prepare_pdf_page(meta_path, MODEL_NAME)
        else:
            text, reason = prepare_html_page(meta_path, cache_path, MODEL_NAME)

        if text is None:
            pages_below_min += 1
            continue

        # count_tokens() is the actual Gemini API call for the estimation pass
        tok = _count_tokens(text, MODEL_NAME)
        total_input_tokens += tok

        # Track the cost of count_tokens() calls (input rate, no batch discount)
        page_costs_for_estimation += tok / 1_000_000 * _INPUT_PRICE_PER_M

    # Estimated batch submission cost
    input_cost = total_input_tokens / 1_000_000 * _INPUT_PRICE_PER_M * _BATCH_DISCOUNT
    estimated_output_tokens = total_input_tokens * _ESTIMATED_OUTPUT_RATIO
    output_cost = estimated_output_tokens / 1_000_000 * _OUTPUT_PRICE_PER_M * _BATCH_DISCOUNT
    batch_cost = input_cost + output_cost

    max_cost_raw = os.environ.get("STAGE3_MAX_COST", "").strip()
    max_cost: float | None = float(max_cost_raw) if max_cost_raw else None

    if max_cost is not None and batch_cost > max_cost:
        log.warning(
            "cost_ceiling_exceeded",
            estimated_usd=round(batch_cost, 4),
            max_cost_usd=max_cost,
        )

    # ── Print summary ────────────────────────────────────────────────────
    print("\nDRY RUN SUMMARY")
    print(f"  Pages found:          {pages_found:,}")
    print(f"  Pages below minimum:  {pages_below_min:,}")
    print(f"  Estimated tokens:     {total_input_tokens:,} input")
    print(f"  Estimation API cost:  ${page_costs_for_estimation:.4f}"
          "  \u2190 cost of count_tokens() calls")
    print(f"  Estimated batch cost: ${batch_cost:.4f}")
    _print_cost_ceiling(batch_cost, max_cost)

    return 1 if (max_cost is not None and batch_cost > max_cost) else 0


def _print_cost_ceiling(batch_cost: float, max_cost: float | None = None) -> None:
    if max_cost is None:
        max_cost_raw = os.environ.get("STAGE3_MAX_COST", "").strip()
        max_cost = float(max_cost_raw) if max_cost_raw else None

    if max_cost is not None:
        status = "WITHIN LIMIT" if batch_cost <= max_cost else "EXCEEDS LIMIT"
        print(f"  Max cost ceiling:     ${max_cost:.2f} (STAGE3_MAX_COST)")
        print(f"  Status:               {status}")
    else:
        print("  Max cost ceiling:     not set (STAGE3_MAX_COST unset)")
        print("  Status:               OK")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m stage3",
        description=(
            "Stage 3 LLM Extraction Pipeline — manual run entry point.\n\n"
            "Scans raw_cache for changed pages, submits them to Gemini 3.5 Flash\n"
            "via the Batch API, normalises the results, and writes grant records\n"
            "to PostgreSQL."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m stage3 --date 2026-05-23          "
            "# process a specific crawl cycle\n"
            "  python -m stage3 --date 2026-05-23 --force  "
            "# skip Stage 2 sentinel check\n"
            "  python -m stage3 --dry-run                  "
            "# estimate cost without API calls\n"
            "  python -m stage3 --status-refresh           "
            "# run daily status refresh manually\n"
        ),
    )
    parser.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        default=None,
        help=(
            "Crawl cycle date to process.  "
            "Defaults to today (UTC) when omitted."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help=(
            "Bypass the Stage 2 crawl_complete sentinel check.  "
            "Useful for manual reruns when the sentinel file is absent."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        dest="dry_run",
        help=(
            "Scan raw_cache and call count_tokens() to estimate batch cost, "
            "but submit no LLM calls and write nothing to the database.  "
            "Logs a WARNING if the estimate exceeds STAGE3_MAX_COST."
        ),
    )
    parser.add_argument(
        "--status-refresh",
        action="store_true",
        default=False,
        dest="status_refresh",
        help=(
            "Run the daily status recalculation job manually instead of the "
            "extraction cycle.  Promotes Upcoming → Open and closes expired "
            "Open records.  Safe to run at any time."
        ),
    )
    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    run_date: str = args.date or datetime.now(timezone.utc).date().isoformat()

    # ── --status-refresh ─────────────────────────────────────────────────
    if args.status_refresh:
        import psycopg2
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            print(
                "Error: DATABASE_URL environment variable is required.",
                file=sys.stderr,
            )
            return 1
        conn = psycopg2.connect(database_url)
        try:
            from stage3.status_refresh import run_status_refresh
            result = run_status_refresh(conn)
            print(
                f"Status refresh complete: "
                f"{result['upcoming_to_open']} Upcoming→Open, "
                f"{result['open_to_closed']} Open→Closed."
            )
            return 0
        except Exception as exc:
            print(f"Fatal error: {exc}", file=sys.stderr)
            return 2
        finally:
            conn.close()

    # ── --dry-run ─────────────────────────────────────────────────────────
    if args.dry_run:
        raw_cache_dir = os.environ.get("RAW_CACHE_DIR", "raw_cache")
        return _run_dry_run(raw_cache_dir, run_date)

    # ── Normal extraction cycle ───────────────────────────────────────────
    from stage3.batch_processor import run_extraction_cycle

    try:
        run_extraction_cycle(
            force=args.force,
            run_date=run_date,
            dry_run=False,
        )
        return 0
    except RuntimeError as exc:
        print(f"Aborted: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"Fatal error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
