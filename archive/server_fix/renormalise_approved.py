"""
Re-normalisation pass for approved records.

Re-runs normalise_raw_grant() on every approved record that has a non-empty
raw_extraction, then writes back any changed normalised fields (sectors,
org_types, regions, eligibility, status, etc.) WITHOUT touching
requires_review — all records remain approved regardless of what the
updated normaliser would compute.

This is a free operation: no Gemini API calls, no rate limits.
It exists to propagate new alias additions and region_lookup expansions
to records that were normalised before those aliases existed.

Environment: source Stage_3_LLM_extraction/.env first.

Run from /opt/grantglobe/Stage_3_LLM_extraction with .env sourced:
  set -a && source .env && set +a
  .venv/bin/python -c "import runpy; runpy.run_path(
      '/opt/grantglobe/server_fix/renormalise_approved.py',
      run_name='__main__')"
"""

import os
import time

import structlog
from psycopg2.extras import Json, RealDictCursor

from stage3.db import get_connection
from stage3.normaliser import normalise_raw_grant

log = structlog.get_logger(__name__)

DRY_RUN = os.environ.get("DRY_RUN") == "1"
LIMIT = int(os.environ.get("LIMIT", "0")) or None
BATCH_SIZE = 200  # records per DB round-trip

_UPDATE_SQL = """
UPDATE grants SET
    description                 = %(description)s,
    application_deadline        = %(application_deadline)s,
    application_deadline_raw    = %(application_deadline_raw)s,
    application_deadline_type   = %(application_deadline_type)s,
    deadline_notes              = %(deadline_notes)s,
    eoi_deadline                = %(eoi_deadline)s,
    eoi_deadline_raw            = %(eoi_deadline_raw)s,
    eoi_deadline_type           = %(eoi_deadline_type)s,
    grant_opening_date          = %(grant_opening_date)s,
    grant_opening_date_raw      = %(grant_opening_date_raw)s,
    funding_amount_min          = %(funding_amount_min)s,
    funding_amount_max          = %(funding_amount_max)s,
    currency                    = %(currency)s,
    funding_amount_type         = %(funding_amount_type)s,
    current_status              = %(current_status)s,
    status_source               = %(status_source)s,
    source_language             = %(source_language)s,
    ai_focused                  = %(ai_focused)s,
    individuals_not_eligible    = %(individuals_not_eligible)s,
    organisation_types          = %(organisation_types)s,
    individual_eligibility      = %(individual_eligibility)s,
    applicant_base_regions      = %(applicant_base_regions)s,
    applicant_base_countries    = %(applicant_base_countries)s,
    geographic_focus_regions    = %(geographic_focus_regions)s,
    geographic_focus_countries  = %(geographic_focus_countries)s,
    thematic_sectors            = %(thematic_sectors)s,
    grant_types                 = %(grant_types)s,
    confidence_scores           = %(confidence_scores)s,
    aggregate_confidence_score  = %(aggregate_confidence_score)s,
    updated_at                  = NOW()
WHERE id = %(id)s
"""

_NORMALISED_FIELDS = [
    "description",
    "application_deadline", "application_deadline_raw", "application_deadline_type",
    "deadline_notes",
    "eoi_deadline", "eoi_deadline_raw", "eoi_deadline_type",
    "grant_opening_date", "grant_opening_date_raw",
    "funding_amount_min", "funding_amount_max", "currency", "funding_amount_type",
    "current_status", "status_source",
    "source_language", "ai_focused",
    "individuals_not_eligible",
    "organisation_types", "individual_eligibility",
    "applicant_base_regions", "applicant_base_countries",
    "geographic_focus_regions", "geographic_focus_countries",
    "thematic_sectors", "grant_types",
    "aggregate_confidence_score",
]


def _build_params(grant_id, normalised: dict) -> dict:
    params = {f: normalised.get(f) for f in _NORMALISED_FIELDS}
    params["confidence_scores"] = Json(normalised.get("confidence_scores") or {})
    params["id"] = grant_id
    return params


def main():
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    q = """
        SELECT id, source_url, domain, crawl_date, raw_extraction
        FROM grants
        WHERE requires_review = FALSE
          AND raw_extraction IS NOT NULL
          AND raw_extraction != '{}'::jsonb
        ORDER BY id
    """
    if LIMIT:
        q += f" LIMIT {LIMIT}"

    cur.execute(q)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    total = len(rows)
    log.info("renormalise_start", total=total, dry_run=DRY_RUN)

    updated = 0
    errors = 0

    for i, row in enumerate(rows, 1):
        grant_id = row["id"]
        raw_extraction = dict(row["raw_extraction"])

        source = {
            "source_url": row["source_url"],
            "domain": row["domain"],
            "crawl_date": str(row["crawl_date"]),
        }

        try:
            normalised = normalise_raw_grant(raw_extraction, source)
        except Exception as exc:
            errors += 1
            log.warning("normalise_failed", id=str(grant_id), error=str(exc))
            continue

        if DRY_RUN:
            if i <= 5:
                log.info(
                    "dry_run_sample",
                    id=str(grant_id),
                    sectors=normalised.get("thematic_sectors"),
                    org_types=normalised.get("organisation_types"),
                    regions=normalised.get("applicant_base_regions"),
                )
            continue

        params = _build_params(grant_id, normalised)

        # Fresh connection per batch to avoid Neon idle timeout
        if i % BATCH_SIZE == 1:
            write_conn = get_connection()

        try:
            write_cur = write_conn.cursor()
            write_cur.execute(_UPDATE_SQL, params)
            write_cur.close()

            if i % BATCH_SIZE == 0 or i == total:
                write_conn.commit()
                write_conn.close()

            updated += 1
        except Exception as exc:
            errors += 1
            log.warning("write_failed", id=str(grant_id), error=str(exc))
            try:
                write_conn.rollback()
                write_conn.close()
            except Exception:
                pass

        if i % 100 == 0:
            log.info("progress", done=i, total=total, updated=updated, errors=errors)

    print(f"\n{'DRY RUN — ' if DRY_RUN else ''}Re-normalisation complete")
    print(f"  records processed: {total}")
    if not DRY_RUN:
        print(f"  records updated:   {updated}")
        print(f"  errors:            {errors}")


if __name__ == "__main__":
    main()
