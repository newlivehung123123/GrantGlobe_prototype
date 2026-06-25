"""Re-normalise the existing review queue against the fuzzy-matched
controlled vocabularies (normaliser.py fix), without any new Gemini calls.

For every grant with requires_review=true AND review_status='pending'
(i.e. nothing an operator has already approved/rejected), re-run
normalise_raw_grant() over the stored raw_extraction JSON and write back
the recomputed array fields, current_status, requires_review, and
review_status. Records an operator has already decided on (approved /
rejected) are left untouched, matching the upsert CASE guard in writer.py.
"""
from stage3.db import get_connection
from stage3.normaliser import normalise_raw_grant

conn = get_connection()
cur = conn.cursor()

cur.execute(
    """
    SELECT id, content_hash, raw_extraction, source_url, domain, crawl_date
    FROM grants
    WHERE requires_review = true AND review_status = 'pending'
    """
)
rows = cur.fetchall()
print("rows to re-normalise:", len(rows))

moved_to_approved = 0
still_review = 0

for (gid, content_hash, raw_extraction, source_url, domain, crawl_date) in rows:
    raw_grant = dict(raw_extraction or {})
    source = {
        "source_url": source_url or "",
        "domain": domain or "unknown",
        "crawl_date": crawl_date.isoformat() if hasattr(crawl_date, "isoformat") else crawl_date,
    }
    normalised = normalise_raw_grant(raw_grant, source)

    if normalised["requires_review"]:
        still_review += 1
    else:
        moved_to_approved += 1

    cur.execute(
        """
        UPDATE grants SET
            organisation_types         = %(organisation_types)s,
            individual_eligibility     = %(individual_eligibility)s,
            applicant_base_regions     = %(applicant_base_regions)s,
            applicant_base_countries   = %(applicant_base_countries)s,
            geographic_focus_regions   = %(geographic_focus_regions)s,
            geographic_focus_countries = %(geographic_focus_countries)s,
            thematic_sectors           = %(thematic_sectors)s,
            grant_types                = %(grant_types)s,
            current_status             = %(current_status)s,
            status_source              = %(status_source)s,
            requires_review            = %(requires_review)s,
            review_status              = %(review_status)s,
            updated_at                 = NOW()
        WHERE id = %(id)s
        """,
        {
            "organisation_types": normalised["organisation_types"],
            "individual_eligibility": normalised["individual_eligibility"],
            "applicant_base_regions": normalised["applicant_base_regions"],
            "applicant_base_countries": normalised["applicant_base_countries"],
            "geographic_focus_regions": normalised["geographic_focus_regions"],
            "geographic_focus_countries": normalised["geographic_focus_countries"],
            "thematic_sectors": normalised["thematic_sectors"],
            "grant_types": normalised["grant_types"],
            "current_status": normalised["current_status"],
            "status_source": normalised["status_source"],
            "requires_review": normalised["requires_review"],
            "review_status": normalised["review_status"],
            "id": gid,
        },
    )

conn.commit()
print("moved to approved (now visible):", moved_to_approved)
print("still flagged for review:       ", still_review)

cur.close()
conn.close()
