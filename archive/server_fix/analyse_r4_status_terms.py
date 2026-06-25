"""Read-only: for pending records where compute_status() returns
current_status == "Others" (R4), dump the raw current_status_raw values
(with confidence_scores.current_status) and frequency counts, to see whether
a curated alias table for _STATUS_VOCAB would resolve most of them.

No DB writes.
"""
from collections import Counter
from rapidfuzz import fuzz
from stage3.db import get_connection
from stage3.normaliser import (
    normalise_controlled_vocab,
    normalise_geographic_list,
    normalise_deadline,
    compute_status,
    INDIV_ELIGIBILITY_VOCAB,
    THEMATIC_SECTORS_VOCAB,
    INDIV_ELIGIBILITY_ALIASES,
    THEMATIC_SECTORS_ALIASES,
    _STATUS_VOCAB,
)

conn = get_connection()
cur = conn.cursor()
cur.execute(
    """
    SELECT id, raw_extraction
    FROM grants
    WHERE requires_review = true AND review_status = 'pending'
    """
)
rows = cur.fetchall()

terms = Counter()

for (gid, raw_extraction) in rows:
    raw_grant = dict(raw_extraction or {})
    cs = raw_grant.get("confidence_scores") or {}

    app_deadline = normalise_deadline(
        raw_grant.get("application_deadline_raw"),
        cs.get("application_deadline", "not_found"),
    )
    opening_date = normalise_deadline(
        raw_grant.get("grant_opening_date_raw"),
        cs.get("grant_opening_date", "not_found"),
    )

    record = {
        "confidence_scores": cs,
        "current_status_raw": raw_grant.get("current_status_raw"),
        "application_deadline_type": app_deadline["type"],
        "application_deadline": app_deadline["date"],
        "grant_opening_date": opening_date["date"],
    }
    status_result = compute_status(record)
    if status_result["current_status"] == "Others":
        terms[raw_grant.get("current_status_raw")] += 1

print(f"records with current_status == 'Others': {sum(terms.values())}")
print("\ntop current_status_raw values causing R4 (top 25):")
for term, n in terms.most_common(25):
    best = max((fuzz.ratio((term or "").lower(), v.lower()) for v in _STATUS_VOCAB), default=0)
    print(f"  {n:4d}  {term!r}  best_ratio_score={best:.0f}")

cur.close()
conn.close()
