"""
Database Writer — upserts normalised grant records into PostgreSQL.

Key invariant: operator review decisions (review_status = 'approved' or 'rejected')
are preserved on re-extraction ONLY when the incoming record does not itself raise a
review flag. If requires_review = true on the new extraction, the record reverts to
'pending' so the quality concern is re-evaluated.
"""

import csv
import datetime
import json
import os
from pathlib import Path

import structlog
from psycopg2.extras import Json, RealDictCursor

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Upsert SQL
# ---------------------------------------------------------------------------

_UPSERT_SQL = """
INSERT INTO grants (
    content_hash, grant_title, funder_name, funder_ror_id,
    source_url, application_portal_url, description,
    application_deadline, application_deadline_raw, application_deadline_type,
    deadline_notes, eoi_deadline, eoi_deadline_raw, eoi_deadline_type,
    grant_opening_date, grant_opening_date_raw,
    funding_amount_min, funding_amount_max, currency, funding_amount_type,
    current_status, status_source,
    source_language, ai_focused,
    individuals_not_eligible, organisation_types, individual_eligibility,
    applicant_base_regions, applicant_base_countries,
    geographic_focus_regions, geographic_focus_countries,
    thematic_sectors, grant_types,
    confidence_scores, aggregate_confidence_score,
    raw_extraction, requires_review, review_status,
    domain, crawl_date
)
VALUES (
    %(content_hash)s, %(grant_title)s, %(funder_name)s, %(funder_ror_id)s,
    %(source_url)s, %(application_portal_url)s, %(description)s,
    %(application_deadline)s, %(application_deadline_raw)s, %(application_deadline_type)s,
    %(deadline_notes)s, %(eoi_deadline)s, %(eoi_deadline_raw)s, %(eoi_deadline_type)s,
    %(grant_opening_date)s, %(grant_opening_date_raw)s,
    %(funding_amount_min)s, %(funding_amount_max)s, %(currency)s, %(funding_amount_type)s,
    %(current_status)s, %(status_source)s,
    %(source_language)s, %(ai_focused)s,
    %(individuals_not_eligible)s, %(organisation_types)s, %(individual_eligibility)s,
    %(applicant_base_regions)s, %(applicant_base_countries)s,
    %(geographic_focus_regions)s, %(geographic_focus_countries)s,
    %(thematic_sectors)s, %(grant_types)s,
    %(confidence_scores)s, %(aggregate_confidence_score)s,
    %(raw_extraction)s, %(requires_review)s, %(review_status)s,
    %(domain)s, %(crawl_date)s
)
ON CONFLICT (content_hash) DO UPDATE SET
    grant_title                 = EXCLUDED.grant_title,
    funder_name                 = EXCLUDED.funder_name,
    funder_ror_id               = EXCLUDED.funder_ror_id,
    application_portal_url      = EXCLUDED.application_portal_url,
    description                 = EXCLUDED.description,
    application_deadline        = EXCLUDED.application_deadline,
    application_deadline_raw    = EXCLUDED.application_deadline_raw,
    application_deadline_type   = EXCLUDED.application_deadline_type,
    deadline_notes              = EXCLUDED.deadline_notes,
    eoi_deadline                = EXCLUDED.eoi_deadline,
    eoi_deadline_raw            = EXCLUDED.eoi_deadline_raw,
    eoi_deadline_type           = EXCLUDED.eoi_deadline_type,
    grant_opening_date          = EXCLUDED.grant_opening_date,
    grant_opening_date_raw      = EXCLUDED.grant_opening_date_raw,
    funding_amount_min          = EXCLUDED.funding_amount_min,
    funding_amount_max          = EXCLUDED.funding_amount_max,
    currency                    = EXCLUDED.currency,
    funding_amount_type         = EXCLUDED.funding_amount_type,
    current_status              = EXCLUDED.current_status,
    status_source               = EXCLUDED.status_source,
    source_language             = EXCLUDED.source_language,
    ai_focused                  = EXCLUDED.ai_focused,
    individuals_not_eligible    = EXCLUDED.individuals_not_eligible,
    organisation_types          = EXCLUDED.organisation_types,
    individual_eligibility      = EXCLUDED.individual_eligibility,
    applicant_base_regions      = EXCLUDED.applicant_base_regions,
    applicant_base_countries    = EXCLUDED.applicant_base_countries,
    geographic_focus_regions    = EXCLUDED.geographic_focus_regions,
    geographic_focus_countries  = EXCLUDED.geographic_focus_countries,
    thematic_sectors            = EXCLUDED.thematic_sectors,
    grant_types                 = EXCLUDED.grant_types,
    confidence_scores           = EXCLUDED.confidence_scores,
    aggregate_confidence_score  = EXCLUDED.aggregate_confidence_score,
    raw_extraction              = EXCLUDED.raw_extraction,
    requires_review             = EXCLUDED.requires_review,
    review_status = CASE
        WHEN grants.review_status IN ('approved', 'rejected')
             AND EXCLUDED.requires_review = false
        THEN grants.review_status
        ELSE EXCLUDED.review_status
    END,
    updated_at                  = NOW()
WHERE EXCLUDED.aggregate_confidence_score > grants.aggregate_confidence_score
RETURNING (xmax = 0) AS is_new_insert
"""


def upsert_grant(conn, record: dict) -> str:
    """Insert or update a normalised grant record in the ``grants`` table.

    The upsert applies the §8 CASE guard: operator decisions
    (``review_status = 'approved'`` or ``'rejected'``) are preserved when the
    incoming extraction does NOT raise a review flag
    (``requires_review = false``).  A re-extraction that sets
    ``requires_review = true`` resets ``review_status`` to ``'pending'`` so
    the quality concern is re-evaluated.

    Args:
        conn: Active psycopg2 connection (caller manages commit/rollback).
        record: Fully-normalised grant dict whose keys match the ``%(key)s``
            placeholders in ``_UPSERT_SQL``.  JSONB fields
            (``confidence_scores``, ``raw_extraction``) may be raw Python
            dicts — they will be wrapped with ``psycopg2.extras.Json``
            automatically.

    Returns:
        ``"inserted"``  — new record was added to the table.
        ``"updated"``   — existing record replaced by higher-confidence data.
        ``"skipped"``   — incoming confidence ≤ existing; no change made.
    """
    # Wrap JSONB columns for psycopg2 — plain dicts are not automatically
    # serialised to JSONB by all driver versions.
    params = dict(record)
    for jsonb_col in ("confidence_scores", "raw_extraction"):
        val = params.get(jsonb_col)
        if val is not None and not isinstance(val, Json):
            params[jsonb_col] = Json(val)
        elif val is None:
            params[jsonb_col] = Json({})

    with conn.cursor() as cur:
        cur.execute(_UPSERT_SQL, params)
        row = cur.fetchone()

    conn.commit()

    if row is None:
        # WHERE clause not satisfied — incoming confidence ≤ existing record.
        log.debug("upsert_skipped", content_hash=record.get("content_hash"))
        return "skipped"

    # row is a tuple (plain cursor) or dict (RealDictCursor).
    is_new: bool
    if isinstance(row, dict):
        is_new = bool(row.get("is_new_insert"))
    else:
        is_new = bool(row[0])

    if is_new:
        log.info("upsert_inserted", content_hash=record.get("content_hash"))
        return "inserted"

    log.info("upsert_updated", content_hash=record.get("content_hash"))
    return "updated"


# ---------------------------------------------------------------------------
# Review queue exporter (§9)
# ---------------------------------------------------------------------------

_REVIEW_QUEUE_SQL = """
SELECT
    id, content_hash, grant_title, funder_name, source_url,
    application_deadline, application_deadline_type,
    current_status, status_source,
    geographic_focus_regions, geographic_focus_countries,
    thematic_sectors, individual_eligibility,
    ai_focused,
    confidence_scores, raw_extraction,
    created_at
FROM grants
WHERE requires_review = true
  AND review_status = 'pending'
ORDER BY created_at DESC
"""

# Columns exported to CSV — order determines column order in the file.
_REVIEW_QUEUE_COLUMNS = [
    "id",
    "content_hash",
    "grant_title",
    "funder_name",
    "source_url",
    "application_deadline",
    "application_deadline_type",
    "current_status",
    "status_source",
    "geographic_focus_regions",
    "geographic_focus_countries",
    "thematic_sectors",
    "individual_eligibility",
    "ai_focused",
    "confidence_scores",
    "raw_extraction",
    "created_at",
]


def export_review_queue(
    conn,
    output_dir: str | Path,
    run_date: str | datetime.date,
) -> Path:
    """Export all pending-review grant records to a CSV file.

    Queries ``grants`` for rows where ``requires_review = true`` and
    ``review_status = 'pending'``, ordered newest first, and writes them to
    ``{output_dir}/review_queue_{run_date}.csv``.

    JSONB columns (``confidence_scores``, ``raw_extraction``) and PostgreSQL
    array columns are serialised to their JSON/string representations so the
    CSV is human-readable in any spreadsheet application.

    Args:
        conn: Active psycopg2 connection.
        output_dir: Directory to write the CSV into.  Created if absent.
        run_date: The extraction run date, used in the filename.
            Accepts a ``datetime.date`` object or an ISO-8601 string.

    Returns:
        ``Path`` to the written CSV file.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    date_str = (
        run_date.isoformat()
        if isinstance(run_date, datetime.date)
        else str(run_date)
    )
    csv_path = output_path / f"review_queue_{date_str}.csv"

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(_REVIEW_QUEUE_SQL)
        rows = cur.fetchall()

    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_REVIEW_QUEUE_COLUMNS)
        writer.writeheader()
        for row in rows:
            out: dict = {}
            for col in _REVIEW_QUEUE_COLUMNS:
                val = row.get(col)
                # Serialise JSONB and array values to strings for the CSV.
                if isinstance(val, (dict, list)):
                    val = json.dumps(val, ensure_ascii=False, default=str)
                out[col] = val
            writer.writerow(out)

    log.info(
        "review_queue_exported",
        path=str(csv_path),
        row_count=len(rows),
        run_date=date_str,
    )
    return csv_path
