#!/usr/bin/env python3
"""
export_grants.py — Export quality-assured grant records from the Stage 3
PostgreSQL database to data/grants.json for the static searchable interface.

INCLUSION RULE:
  (review_status = 'approved')
  OR (requires_review = false AND review_status = 'pending')

  Excluded: review_status = 'rejected',
            and requires_review = true AND review_status = 'pending'.

By default current_status = 'Closed' records are also excluded.
Use --include-closed to override.

Usage:
    python export_grants.py
    python export_grants.py --include-closed
    python export_grants.py --output /path/to/custom.json
"""

from __future__ import annotations

import argparse
import datetime
import decimal
import json
import os
import sys
import uuid
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

# ---------------------------------------------------------------------------
# python-dotenv is optional but preferred; fall back to os.environ gracefully.
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # dotenv not installed — rely on environment variables already set

# ---------------------------------------------------------------------------
# Default paths (relative to this file's location)
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).parent
_DEFAULT_OUTPUT = _SCRIPT_DIR / "data" / "grants.json"

# ---------------------------------------------------------------------------
# Columns to export (JSONB audit columns are intentionally omitted)
# ---------------------------------------------------------------------------

_EXPORT_COLUMNS = """
    id,
    grant_title,
    funder_name,
    source_url,
    application_portal_url,
    description,
    application_deadline,
    application_deadline_raw,
    application_deadline_type,
    deadline_notes,
    eoi_deadline,
    eoi_deadline_raw,
    grant_opening_date,
    funding_amount_min,
    funding_amount_max,
    currency,
    current_status,
    source_language,
    ai_focused,
    individuals_not_eligible,
    organisation_types,
    individual_eligibility,
    applicant_base_regions,
    applicant_base_countries,
    geographic_focus_regions,
    geographic_focus_countries,
    thematic_sectors,
    grant_types,
    domain,
    crawl_date
"""

# Columns whose DB value may be NULL but must serialise as [] in JSON
_ARRAY_COLUMNS: frozenset[str] = frozenset(
    {
        "organisation_types",
        "individual_eligibility",
        "applicant_base_regions",
        "applicant_base_countries",
        "geographic_focus_regions",
        "geographic_focus_countries",
        "thematic_sectors",
        "grant_types",
    }
)

# ---------------------------------------------------------------------------
# SQL query (built dynamically to optionally exclude Closed)
# ---------------------------------------------------------------------------


def _build_query(include_closed: bool) -> str:
    closed_clause = (
        ""
        if include_closed
        else "    AND (current_status IS DISTINCT FROM 'Closed')\n"
    )
    return f"""
SELECT
{_EXPORT_COLUMNS}
FROM grants g
WHERE
    (
        g.review_status = 'approved'
        OR (g.requires_review = false AND g.review_status = 'pending')
    )
{closed_clause}
    -- English-only: exclude grants in other languages.
    -- source_language is null for records where language was not detected
    -- (treat as English to avoid excluding legitimate records).
    AND (g.source_language IS NULL OR g.source_language ILIKE 'English' OR g.source_language = 'en')

    -- Stale deadline filter: exclude grants whose deadline has passed but
    -- whose status was never updated from Open/Upcoming.  Rolling grants
    -- have no fixed deadline so are always kept.
    AND NOT (
        g.application_deadline < CURRENT_DATE
        AND g.current_status IN ('Open', 'Upcoming')
    )

    -- Quality filter: exclude records from listing pages where no specific
    -- grant URL was captured.  A record is treated as a listing-page extract
    -- when application_portal_url is NULL and its source_url was shared by
    -- more than one approved/auto-approved grant (i.e. the crawler hit a
    -- page that contained multiple opportunities and the LLM didn't extract
    -- individual links for them).
    AND (
        g.application_portal_url IS NOT NULL
        OR (
            SELECT COUNT(*)
            FROM grants g2
            WHERE g2.source_url = g.source_url
              AND (
                  g2.review_status = 'approved'
                  OR (g2.requires_review = false AND g2.review_status = 'pending')
              )
        ) = 1
    )

ORDER BY
    CASE g.current_status
        WHEN 'Open'     THEN 1
        WHEN 'Upcoming' THEN 2
        WHEN 'Rolling'  THEN 3
        WHEN 'Closed'   THEN 5
        ELSE                 4
    END,
    g.application_deadline ASC NULLS LAST
"""


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _serialise_value(key: str, value) -> object:
    """Convert a single psycopg2 field value to a JSON-safe Python object.

    Rules:
    - DATE / DATETIME → ISO 8601 string or null
    - NUMERIC (Decimal) → float or null
    - UUID → string
    - list (TEXT[]) → list (already Python list from psycopg2)
    - array columns that are NULL → []  (never null in output)
    - bool → bool
    - str, int, None → unchanged
    """
    if value is None:
        return [] if key in _ARRAY_COLUMNS else None

    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()

    if isinstance(value, decimal.Decimal):
        return float(value)

    if isinstance(value, uuid.UUID):
        return str(value)

    if isinstance(value, list):
        # Ensure every element is a plain string (psycopg2 may return None items)
        return [str(item) for item in value if item is not None]

    return value


def _serialise_row(row: dict) -> dict:
    """Serialise a full database row dict to a JSON-safe dict."""
    return {key: _serialise_value(key, val) for key, val in row.items()}


# ---------------------------------------------------------------------------
# Main export logic
# ---------------------------------------------------------------------------


def export(include_closed: bool, output_path: Path) -> tuple[int, str]:
    """Connect, query, serialise, and write grants.json.

    Returns a (count, exported_at) tuple: the number of records exported and
    the ISO 8601 timestamp that was written into the JSON metadata.
    Raises SystemExit(1) on connection or query failure.
    """
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print(
            "Error: DATABASE_URL is not set.\n"
            "Set it in your environment or in a .env file in this directory, e.g.:\n"
            "  DATABASE_URL=postgresql://user:pass@localhost/grantglobe",
            file=sys.stderr,
        )
        sys.exit(1)

    # ── Connect ────────────────────────────────────────────────────────────
    try:
        conn = psycopg2.connect(database_url)
    except psycopg2.OperationalError as exc:
        print(f"Error: Could not connect to the database.\n{exc}", file=sys.stderr)
        sys.exit(1)

    # ── Query ──────────────────────────────────────────────────────────────
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(_build_query(include_closed))
            rows = cur.fetchall()
    except psycopg2.Error as exc:
        print(f"Error: Database query failed.\n{exc}", file=sys.stderr)
        conn.close()
        sys.exit(1)
    finally:
        conn.close()

    # ── Serialise ──────────────────────────────────────────────────────────
    exported_at = datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds"
    )
    grants = [_serialise_row(dict(row)) for row in rows]

    payload: dict = {
        "metadata": {
            "exported_at": exported_at,
            "total_grants": len(grants),
            "schema_version": "1.0",
            "includes_closed": include_closed,
        },
        "grants": grants,
    }

    # ── Write ──────────────────────────────────────────────────────────────
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return len(grants), exported_at


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export quality-assured grant records to grants.json.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--include-closed",
        action="store_true",
        default=False,
        help="Include grants whose current_status is 'Closed' (excluded by default).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_OUTPUT,
        metavar="PATH",
        help=f"Output path for grants.json (default: {_DEFAULT_OUTPUT}).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    total, exported_at = export(include_closed=args.include_closed, output_path=args.output)

    print(
        f"\nExport complete.\n"
        f"  Records exported:  {total}\n"
        f"  Includes closed:   {'Yes' if args.include_closed else 'No'}\n"
        f"  Output:            {args.output}\n"
        f"  Exported at:       {exported_at}"
    )


if __name__ == "__main__":
    main()
