"""Read-only analysis: for the 2270 pending review-queue grants, find every
raw item in thematic_sectors_raw / individual_eligibility_raw /
geographic_focus_raw that becomes "Others" after normalisation, and report
its best fuzzy-match score against the controlled vocabulary.

This does NOT write to the database. It tells us whether the "Others"
entries that trigger R5 are near-misses (score 70-84, fixable by lowering
the fuzzy threshold) or genuinely novel terms (score <70, need vocab
expansion).
"""
from collections import Counter

from rapidfuzz import fuzz

from stage3.db import get_connection
from stage3.normaliser import (
    THEMATIC_SECTORS_VOCAB,
    INDIV_ELIGIBILITY_VOCAB,
    REGION_LOOKUP,
)

conn = get_connection()
cur = conn.cursor()
cur.execute(
    """
    SELECT raw_extraction
    FROM grants
    WHERE requires_review = true AND review_status = 'pending'
    """
)
rows = cur.fetchall()
print("rows analysed:", len(rows))


def best_match(item: str, vocab_lower: dict) -> tuple[str | None, float]:
    key = item.lower().strip()
    if key in vocab_lower:
        return vocab_lower[key], 100.0
    best_score, best_canon = 0.0, None
    for v_lower, v_canon in vocab_lower.items():
        score = fuzz.ratio(key, v_lower)
        if score > best_score:
            best_score, best_canon = score, v_canon
    return best_canon, best_score


thematic_lower = {v.lower(): v for v in THEMATIC_SECTORS_VOCAB}
indiv_lower = {v.lower(): v for v in INDIV_ELIGIBILITY_VOCAB}

near_miss = Counter()   # score 70-84 -> term: count
far_miss = Counter()    # score <70 -> term: count

fields = {
    "thematic_sectors_raw": thematic_lower,
    "individual_eligibility_raw": indiv_lower,
}

geo_near = Counter()
geo_far = Counter()
region_lower = {k.lower(): k for k in REGION_LOOKUP}

for (raw,) in rows:
    raw = raw or {}

    for field, vocab_lower in fields.items():
        for item in (raw.get(field) or []):
            if not item or not item.strip():
                continue
            key = item.lower().strip()
            if key in vocab_lower:
                continue
            _, score = best_match(item, vocab_lower)
            if score >= 85:
                continue
            label = f"{field}: {item.strip()} (best={score:.0f})"
            if score >= 70:
                near_miss[label] += 1
            else:
                far_miss[label] += 1

    for item in (raw.get("geographic_focus_raw") or []):
        if not item or not item.strip():
            continue
        key = item.lower().strip()
        if key in region_lower:
            continue
        best_score, best_key = 0.0, None
        for r_lower in region_lower:
            score = fuzz.ratio(key, r_lower)
            if score > best_score:
                best_score, best_key = score, r_lower
        if best_score >= 85:
            continue
        label = f"geographic_focus_raw: {item.strip()} (best={best_score:.0f})"
        if best_score >= 70:
            geo_near[label] += 1
        else:
            geo_far[label] += 1

print("\n=== thematic_sectors / individual_eligibility ===")
print(f"near-miss (score 70-84), {sum(near_miss.values())} occurrences, top 25:")
for label, count in near_miss.most_common(25):
    print(f"  {count:5d}  {label}")

print(f"\nfar-miss (score <70), {sum(far_miss.values())} occurrences, top 25:")
for label, count in far_miss.most_common(25):
    print(f"  {count:5d}  {label}")

print("\n=== geographic_focus ===")
print(f"near-miss (score 70-84), {sum(geo_near.values())} occurrences, top 25:")
for label, count in geo_near.most_common(25):
    print(f"  {count:5d}  {label}")

print(f"\nfar-miss (score <70), {sum(geo_far.values())} occurrences, top 25:")
for label, count in geo_far.most_common(25):
    print(f"  {count:5d}  {label}")

cur.close()
conn.close()
