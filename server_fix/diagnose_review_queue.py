"""Diagnose why grants are landing in the review queue.

For every grant with requires_review=true, re-derive which of the R1-R7
rules in normaliser.determine_review_flag fired, and report counts per
rule plus the most common "Others"-mapped raw values for R5.
"""
from collections import Counter

from stage3.db import get_connection

TRIGGER = {"low", "not_found"}
DEADLINE_EXCUSED = {"rolling", "tbc", "not_published"}
R5_FIELDS = ("thematic_sectors", "geographic_focus_regions", "individual_eligibility")

conn = get_connection()
cur = conn.cursor()
cur.execute(
    """
    SELECT confidence_scores, application_deadline_type, current_status,
           thematic_sectors, geographic_focus_regions, individual_eligibility,
           individuals_not_eligible, raw_extraction
    FROM grants
    WHERE requires_review = true
    """
)
rows = cur.fetchall()
print("total flagged:", len(rows))

rule_counts = Counter()
others_raw_values = Counter()

for r in rows:
    (cs, dl_type, status, thematic, geo, indiv, not_elig, raw) = r
    cs = cs or {}
    thematic = thematic or []
    geo = geo or []
    indiv = indiv or []
    raw = raw or {}

    if cs.get("grant_title") in TRIGGER:
        rule_counts["R1_grant_title_conf"] += 1
    if cs.get("funder_name") in TRIGGER:
        rule_counts["R2_funder_name_conf"] += 1
    if cs.get("application_deadline") in TRIGGER and dl_type not in DEADLINE_EXCUSED:
        rule_counts["R3_deadline_conf"] += 1
    if status == "Others":
        rule_counts["R4_status_others"] += 1
    if "Others" in thematic or "Others" in geo or "Others" in indiv:
        rule_counts["R5_array_others"] += 1
        for raw_key in ("thematic_sectors_raw", "geographic_focus_raw", "individual_eligibility_raw"):
            for item in raw.get(raw_key) or []:
                others_raw_values[item] += 1
    if cs.get("ai_focused") in {"low", "not_found"}:
        rule_counts["R6_ai_focused_conf"] += 1
    if not_elig is None:
        rule_counts["R7_individuals_not_eligible_none"] += 1

print()
print("rule trigger counts (a record can trigger multiple):")
for rule, n in rule_counts.most_common():
    print(f"  {rule:35s} {n:5d}  ({100*n/len(rows):.1f}%)")

print()
print("top 20 raw values behind R5 'Others' (not in controlled vocab):")
for val, n in others_raw_values.most_common(20):
    print(f"  {n:4d}  {val}")

cur.close()
conn.close()
