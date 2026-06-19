"""Read-only: for the 2260 still-flagged review-queue grants, recompute
thematic_sectors / individual_eligibility / geographic_focus_regions with the
NEW normaliser (token-set fix already installed), then test how many records
would clear R5 under three variants of the rule:

  CURRENT  - flag if "Others" appears anywhere in the three R5 arrays
  VARIANT_A - flag only if a non-empty array is ENTIRELY "Others"
              (i.e. nothing in that field matched at all)
  VARIANT_B - flag if more than 50% of a non-empty array's entries are
              "Others"

For each variant, also report how many of the records that would clear R5
are STILL flagged overall because of R1-R4/R6/R7 (confidence scores,
current_status=Others, individuals_not_eligible=None, etc.) — i.e. the net
number that would actually move to "approved".

No DB writes.
"""
from stage3.db import get_connection
from stage3.normaliser import (
    normalise_raw_grant,
    normalise_controlled_vocab,
    normalise_geographic_list,
    normalise_deadline,
    compute_status,
    determine_review_flag,
    aggregate_confidence_score,
    ORG_TYPES_VOCAB,
    INDIV_ELIGIBILITY_VOCAB,
    THEMATIC_SECTORS_VOCAB,
    GRANT_TYPES_VOCAB,
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


def r5_current(record):
    for field in _R5_ARRAY_FIELDS:
        if "Others" in (record.get(field) or []):
            return True
    return False


def r5_variant_a(record):
    for field in _R5_ARRAY_FIELDS:
        arr = record.get(field) or []
        if arr and all(x == "Others" for x in arr):
            return True
    return False


def r5_variant_b(record):
    for field in _R5_ARRAY_FIELDS:
        arr = record.get(field) or []
        if not arr:
            continue
        others = sum(1 for x in arr if x == "Others")
        if others / len(arr) > 0.5:
            return True
    return False


def other_rules_flag(record):
    """R1-R4, R6, R7 only (everything except R5)."""
    cs = record.get("confidence_scores", {})
    trigger_set = frozenset({"low", "not_found"})

    if cs.get("grant_title") in trigger_set:
        return True
    if cs.get("funder_name") in trigger_set:
        return True
    _deadline_excused = frozenset({"rolling", "tbc", "not_published"})
    if (
        cs.get("application_deadline") in trigger_set
        and record.get("application_deadline_type") not in _deadline_excused
    ):
        return True
    if record.get("current_status") == "Others":
        return True
    if cs.get("ai_focused") in {"low", "not_found"}:
        return True
    if record.get("individuals_not_eligible") is None:
        return True
    return False


counts = {
    "current_r5_only": 0,
    "variant_a_r5_only": 0,
    "variant_b_r5_only": 0,
    "current_net_clear": 0,
    "variant_a_net_clear": 0,
    "variant_b_net_clear": 0,
}

for (gid, raw_extraction, source_url, domain, crawl_date) in rows:
    raw_grant = dict(raw_extraction or {})
    cs = raw_grant.get("confidence_scores") or {}

    thematic = normalise_controlled_vocab(
        raw_grant.get("thematic_sectors_raw") or [], THEMATIC_SECTORS_VOCAB
    )
    indiv_elig = normalise_controlled_vocab(
        raw_grant.get("individual_eligibility_raw") or [], INDIV_ELIGIBILITY_VOCAB
    )
    geo_focus = normalise_geographic_list(raw_grant.get("geographic_focus_raw") or [])

    app_deadline = normalise_deadline(
        raw_grant.get("application_deadline_raw"),
        cs.get("application_deadline", "not_found"),
    )
    opening_date = normalise_deadline(
        raw_grant.get("grant_opening_date_raw"),
        cs.get("grant_opening_date", "not_found"),
    )

    intermediate = {
        "confidence_scores": cs,
        "application_deadline_type": app_deadline["type"],
        "application_deadline": app_deadline["date"],
        "grant_opening_date": opening_date["date"],
        "current_status_raw": raw_grant.get("current_status_raw"),
        "thematic_sectors": thematic,
        "geographic_focus_regions": geo_focus["regions"],
        "individual_eligibility": indiv_elig,
        "organisation_types": [],  # not in R5, not needed
        "individuals_not_eligible": raw_grant.get("individuals_not_eligible"),
    }
    status_result = compute_status(intermediate)
    record = {**intermediate, **status_result}

    r5_cur = r5_current(record)
    r5_a = r5_variant_a(record)
    r5_b = r5_variant_b(record)
    others = other_rules_flag(record)

    if r5_cur:
        counts["current_r5_only"] += 1
    if r5_a:
        counts["variant_a_r5_only"] += 1
    if r5_b:
        counts["variant_b_r5_only"] += 1

    if not (r5_cur or others):
        counts["current_net_clear"] += 1
    if not (r5_a or others):
        counts["variant_a_net_clear"] += 1
    if not (r5_b or others):
        counts["variant_b_net_clear"] += 1

print(f"\nof {len(rows)} still-flagged rows:")
print(f"  R5 (current rule) still fires on: {counts['current_r5_only']}")
print(f"  R5 (variant A: field all-Others) fires on: {counts['variant_a_r5_only']}")
print(f"  R5 (variant B: >50% Others)     fires on: {counts['variant_b_r5_only']}")
print()
print(f"  net would clear to approved, CURRENT  R5: {counts['current_net_clear']}")
print(f"  net would clear to approved, VARIANT A:   {counts['variant_a_net_clear']}")
print(f"  net would clear to approved, VARIANT B:   {counts['variant_b_net_clear']}")

cur.close()
conn.close()
