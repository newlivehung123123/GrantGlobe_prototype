"""Read-only: for grants still requires_review=true AND review_status='pending'
after the Variant A R5 deploy, break down WHICH of R1-R4/R6/R7 (confidence-score
and status rules) is responsible for keeping each record flagged.

For each record, recompute the normalised view (same approach as
analyse_r5_variants.py) and check each individual sub-rule:

  R1  grant_title confidence in {low, not_found}
  R2  funder_name confidence in {low, not_found}
  R3  application_deadline confidence in {low, not_found}
      (excused if application_deadline_type in {rolling, tbc, not_published})
  R4  current_status == "Others"
  R5  (Variant A) a non-empty R5 array field is entirely "Others"
  R6  ai_focused confidence in {low, not_found}
  R7  individuals_not_eligible is None

Reports, for the full pending queue:
  - how many records each rule fires on (overlaps allowed)
  - how many records are flagged ONLY by each single rule (i.e. fixing that
    rule alone would clear the record to approved)

No DB writes.
"""
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
    _R5_ARRAY_FIELDS,
)

conn = get_connection()
cur = conn.cursor()
cur.execute(
    """
    SELECT id, raw_extraction, source_url, domain, crawl_date
    FROM grants
    WHERE requires_review = true AND review_status = 'pending'
    """
)
rows = cur.fetchall()
print("rows analysed:", len(rows))

trigger_set = frozenset({"low", "not_found"})
_deadline_excused = frozenset({"rolling", "tbc", "not_published"})

fires = {"R1": 0, "R2": 0, "R3": 0, "R4": 0, "R5": 0, "R6": 0, "R7": 0}
only_fires = {"R1": 0, "R2": 0, "R3": 0, "R4": 0, "R5": 0, "R6": 0, "R7": 0}
combo_counts: dict[tuple, int] = {}

for (gid, raw_extraction, source_url, domain, crawl_date) in rows:
    raw_grant = dict(raw_extraction or {})
    cs = raw_grant.get("confidence_scores") or {}

    thematic = normalise_controlled_vocab(
        raw_grant.get("thematic_sectors_raw") or [], THEMATIC_SECTORS_VOCAB,
        aliases=THEMATIC_SECTORS_ALIASES,
    )
    indiv_elig = normalise_controlled_vocab(
        raw_grant.get("individual_eligibility_raw") or [], INDIV_ELIGIBILITY_VOCAB,
        aliases=INDIV_ELIGIBILITY_ALIASES,
    )
    geo_focus = normalise_geographic_list(raw_grant.get("geographic_focus_raw") or [])

    app_deadline = normalise_deadline(
        raw_grant.get("application_deadline_raw"),
        cs.get("application_deadline", "not_found"),
    )

    individuals_not_eligible = raw_grant.get("individuals_not_eligible")
    if individuals_not_eligible is None and (raw_grant.get("individual_eligibility_raw") or []):
        individuals_not_eligible = False

    intermediate = {
        "confidence_scores": cs,
        "application_deadline_type": app_deadline["type"],
        "application_deadline": app_deadline["date"],
        "current_status_raw": raw_grant.get("current_status_raw"),
        "thematic_sectors": thematic,
        "geographic_focus_regions": geo_focus["regions"],
        "individual_eligibility": indiv_elig,
        "individuals_not_eligible": individuals_not_eligible,
    }
    status_result = compute_status(intermediate)
    record = {**intermediate, **status_result}

    active = []

    if cs.get("grant_title") in trigger_set:
        active.append("R1")
    if cs.get("funder_name") in trigger_set:
        active.append("R2")
    if (
        cs.get("application_deadline") in trigger_set
        and record.get("application_deadline_type") not in _deadline_excused
    ):
        active.append("R3")
    if record.get("current_status") == "Others":
        active.append("R4")
    for field in _R5_ARRAY_FIELDS:
        arr = record.get(field) or []
        if arr and all(x == "Others" for x in arr):
            active.append("R5")
            break
    if cs.get("ai_focused") in trigger_set:
        active.append("R6")
    if record.get("individuals_not_eligible") is None:
        active.append("R7")

    for r in active:
        fires[r] += 1
    if len(active) == 1:
        only_fires[active[0]] += 1

    combo = tuple(sorted(active))
    combo_counts[combo] = combo_counts.get(combo, 0) + 1

print("\nrule fires (overlaps allowed):")
for k, v in fires.items():
    print(f"  {k}: {v}")

print("\nrecords flagged by EXACTLY ONE rule (fixing it alone -> approved):")
for k, v in only_fires.items():
    print(f"  {k} only: {v}")

print("\ntop combos:")
for combo, n in sorted(combo_counts.items(), key=lambda x: -x[1])[:15]:
    print(f"  {combo or '(none)'}: {n}")

cur.close()
conn.close()
