"""Read-only: pull a sample of 15 'both empty' R7 records (individuals_not_eligible
is null, individual_eligibility_raw empty, organisation_types_raw empty) and print
their source_url + the raw_cache HTML file path (domain/crawl_date based), so we
can manually inspect a few pages and check whether eligibility info is actually
present on the page (re-extraction could help) or genuinely absent (re-extraction
would not help).

No DB writes.
"""
from stage3.db import get_connection

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

sample = []
for (gid, raw_extraction, source_url, domain, crawl_date) in rows:
    raw_grant = dict(raw_extraction or {})
    if raw_grant.get("individuals_not_eligible") is not None:
        continue
    indiv_raw = raw_grant.get("individual_eligibility_raw") or []
    org_raw = raw_grant.get("organisation_types_raw") or []
    if indiv_raw or org_raw:
        continue
    sample.append((gid, source_url, domain, crawl_date))
    if len(sample) >= 15:
        break

print(f"sample size: {len(sample)}")
for gid, source_url, domain, crawl_date in sample:
    print(f"id={gid}  domain={domain}  crawl_date={crawl_date}")
    print(f"  url={source_url}")

cur.close()
conn.close()
