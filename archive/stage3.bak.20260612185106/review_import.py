"""
Review Import — updates review_status in PostgreSQL from an operator-annotated CSV.

Usage: python -m stage3.review_import <path/to/review_queue_YYYY-MM-DD.csv>

The operator opens the CSV produced by export_review_queue, sets the
review_status column to "approved" or "rejected" for each record they have
reviewed, and saves the file.  This script reads those decisions back and
applies them to the database.

Rows where review_status is blank or still "pending" are silently skipped.
"""

import argparse
import csv
import os
import sys
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

_VALID_DECISIONS = frozenset({"approved", "rejected"})

_UPDATE_SQL = """
UPDATE grants
SET review_status = %s,
    updated_at    = NOW()
WHERE id = %s
"""


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def import_review_decisions(csv_path: str | Path, conn) -> dict:
    """Read operator decisions from *csv_path* and apply them to the database.

    For each row where ``review_status`` is ``"approved"`` or ``"rejected"``:
      - Executes ``UPDATE grants SET review_status = %s, updated_at = NOW()
        WHERE id = %s``.

    Rows where ``review_status`` is blank, ``"pending"``, or any other value
    are skipped without error.

    Args:
        csv_path: Path to the operator-annotated review queue CSV.
        conn: Active psycopg2 connection (caller manages commit/rollback).

    Returns:
        Summary dict: ``{"total": N, "approved": A, "rejected": R, "skipped": S}``.
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    counts = {"approved": 0, "rejected": 0, "skipped": 0}

    with csv_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)

        if "id" not in (reader.fieldnames or []):
            raise ValueError(
                f"CSV is missing required 'id' column. "
                f"Found columns: {reader.fieldnames}"
            )
        if "review_status" not in (reader.fieldnames or []):
            raise ValueError(
                f"CSV is missing required 'review_status' column. "
                f"Found columns: {reader.fieldnames}"
            )

        with conn.cursor() as cur:
            for row in reader:
                decision = (row.get("review_status") or "").strip().lower()
                row_id = (row.get("id") or "").strip()

                if decision not in _VALID_DECISIONS or not row_id:
                    counts["skipped"] += 1
                    continue

                cur.execute(_UPDATE_SQL, (decision, row_id))
                counts[decision] += 1

    conn.commit()

    total = counts["approved"] + counts["rejected"]
    log.info(
        "review_decisions_imported",
        total=total,
        approved=counts["approved"],
        rejected=counts["rejected"],
        skipped=counts["skipped"],
        csv_path=str(csv_path),
    )
    return {"total": total, **counts}


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m stage3.review_import",
        description=(
            "Import operator review decisions from an annotated review-queue CSV "
            "into the grants database.\n\n"
            "The operator opens the CSV produced by export_review_queue, sets the "
            "review_status column to 'approved' or 'rejected', saves the file, then "
            "runs this script to apply the decisions."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "csv_file",
        metavar="CSV_FILE",
        help="Path to the operator-annotated review_queue_YYYY-MM-DD.csv file.",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        metavar="URL",
        help=(
            "PostgreSQL connection string. "
            "Defaults to the DATABASE_URL environment variable."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.database_url:
        parser.error(
            "Database URL required: pass --database-url or set DATABASE_URL."
        )

    import psycopg2

    conn = psycopg2.connect(args.database_url)
    try:
        result = import_review_decisions(args.csv_file, conn)
        print(
            f"Imported {result['total']} decisions "
            f"({result['approved']} approved, {result['rejected']} rejected, "
            f"{result['skipped']} skipped)."
        )
        return 0
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
