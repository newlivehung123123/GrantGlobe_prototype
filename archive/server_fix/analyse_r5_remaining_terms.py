"""Read-only: for the records where R5 (Variant A: a non-empty array field is
ENTIRELY 'Others') still fires, dump the raw terms (thematic_sectors_raw /
individual_eligibility_raw / geographic_focus_raw) that are causing it, with
frequency counts and their best current fuzzy-match score against the
relevant controlled vocabulary, so we can see whether a curated alias table
would resolve most of them.

No DB writes.
"""
from collections import Counter
from rapidfuzz import fuzz
from stage3.db import get_connection
from stage3.normaliser import (
    normalise_controlled_vocab,
    normalise_geographic_list,
    THEMATIC_SECTORS_VOCAB,
    INDIV_ELIGIBILITY_VOCAB,
    THEMATIC_SECTORS_ALIASES,
    INDIV_ELIGIBILITY_ALIASES,
    _R5_ARRAY_FIELDS,
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

thematic_terms = Counter()
indiv_terms = Counter()
geo_terms = Counter()

for (gid, raw_extraction) in rows:
    raw_grant = dict(raw_extraction or {})

    thematic = normalise_controlled_vocab(
        raw_grant.get("thematic_sectors_raw") or [], THEMATIC_SECTORS_VOCAB,
        aliases=THEMATIC_SECTORS_ALIASES,
    )
    indiv_elig = normalise_controlled_vocab(
        raw_grant.get("individual_eligibility_raw") or [], INDIV_ELIGIBILITY_VOCAB,
        aliases=INDIV_ELIGIBILITY_ALIASES,
    )
    geo_focus = normalise_geographic_list(raw_grant.get("geographic_focus_raw") or [])

    if thematic and all(x == "Others" for x in thematic):
        for raw in (raw_grant.get("thematic_sectors_raw") or []):
            thematic_terms[raw] += 1

    if indiv_elig and all(x == "Others" for x in indiv_elig):
        for raw in (raw_grant.get("individual_eligibility_raw") or []):
            indiv_terms[raw] += 1

    regions = geo_focus["regions"]
    if regions and all(x == "Others" for x in regions):
        for raw in (raw_grant.get("geographic_focus_raw") or []):
            geo_terms[raw] += 1

print("=== thematic_sectors_raw terms causing R5 (top 25) ===")
for term, n in thematic_terms.most_common(25):
    best = max((fuzz.token_set_ratio(term.lower(), v.lower()) for v in THEMATIC_SECTORS_VOCAB), default=0)
    print(f"  {n:4d}  {term!r}  best_score={best:.0f}")

print("\n=== individual_eligibility_raw terms causing R5 (top 25) ===")
for term, n in indiv_terms.most_common(25):
    best = max((fuzz.token_set_ratio(term.lower(), v.lower()) for v in INDIV_ELIGIBILITY_VOCAB), default=0)
    print(f"  {n:4d}  {term!r}  best_score={best:.0f}")

print("\n=== geographic_focus_raw terms causing R5 (top 25) ===")
for term, n in geo_terms.most_common(25):
    print(f"  {n:4d}  {term!r}")

cur.close()
conn.close()
