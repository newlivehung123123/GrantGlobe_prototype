"""Read-only: among the 1175 'both empty' R7 records (individuals_not_eligible
null, individual_eligibility_raw empty, organisation_types_raw empty), check how
many source_urls look like search/filter/listing pages rather than individual
grant detail pages — heuristically, URLs containing query-string filter params
(e.g. 'tx_solr', 'filter', '?page=', 'search', 'calls-for-proposals' with '?').

Also breaks down by domain to see concentration.

No DB writes.
"""
from collections import Counter
from urllib.parse import urlparse
from stage3.db import get_connection

conn = get_connection()
cur = conn.cursor()
cur.execute(
    """
    SELECT id, raw_extraction, source_url, domain
    FROM grants
    WHERE requires_review = true AND review_status = 'pending'
    """
)
rows = cur.fetchall()

both_empty = []
for (gid, raw_extraction, source_url, domain) in rows:
    raw_grant = dict(raw_extraction or {})
    if raw_grant.get("individuals_not_eligible") is not None:
        continue
    indiv_raw = raw_grant.get("individual_eligibility_raw") or []
    org_raw = raw_grant.get("organisation_types_raw") or []
    if indiv_raw or org_raw:
        continue
    both_empty.append((gid, source_url, domain))

print(f"both-empty total: {len(both_empty)}")

LISTING_MARKERS = ["tx_solr", "filter", "?page=", "&page=", "tx_news"]

listing_like = 0
domain_counter = Counter()
domain_listing_counter = Counter()

for gid, source_url, domain in both_empty:
    domain_counter[domain] += 1
    parsed = urlparse(source_url or "")
    is_listing = any(m in (source_url or "") for m in LISTING_MARKERS) or "?" in parsed.query and "filter" in parsed.query
    if any(m in (source_url or "") for m in LISTING_MARKERS):
        listing_like += 1
        domain_listing_counter[domain] += 1

print(f"listing/filter-like URLs (heuristic): {listing_like}")
print()
print("top domains by both-empty count:")
for d, n in domain_counter.most_common(15):
    print(f"  {d}: {n}  (listing-like: {domain_listing_counter.get(d, 0)})")

cur.close()
conn.close()
