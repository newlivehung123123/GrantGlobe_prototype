"""Read-only: for the records where individuals_not_eligible is null (R7),
check whether individual_eligibility_raw (a separate LLM-extracted field)
already contains actual category strings. If so, individuals_not_eligible
could be inferred as `false` (individuals ARE eligible) with no re-extraction.

Also checks organisation_types_raw as a cross-check: if individual_eligibility_raw
is empty AND organisation_types_raw is non-empty, that's weaker evidence the
grant is org-only (individuals_not_eligible -> true), vs. both empty (genuinely
unknown -> still needs review or re-extraction).

No DB writes.
"""
from stage3.db import get_connection

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

total = 0
null_indiv_not_elig = 0
has_indiv_elig_raw = 0
empty_indiv_has_org_raw = 0
both_empty = 0

for (gid, raw_extraction) in rows:
    raw_grant = dict(raw_extraction or {})
    total += 1
    if raw_grant.get("individuals_not_eligible") is not None:
        continue
    null_indiv_not_elig += 1

    indiv_raw = raw_grant.get("individual_eligibility_raw") or []
    org_raw = raw_grant.get("organisation_types_raw") or []

    if indiv_raw:
        has_indiv_elig_raw += 1
    elif org_raw:
        empty_indiv_has_org_raw += 1
    else:
        both_empty += 1

print(f"total pending rows: {total}")
print(f"individuals_not_eligible IS NULL: {null_indiv_not_elig}")
print(f"  -> individual_eligibility_raw non-empty (infer false, zero cost): {has_indiv_elig_raw}")
print(f"  -> individual_eligibility_raw empty but organisation_types_raw non-empty (infer true?): {empty_indiv_has_org_raw}")
print(f"  -> both empty (genuinely undetermined): {both_empty}")

cur.close()
conn.close()
