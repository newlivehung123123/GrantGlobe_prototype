#!/usr/bin/env python3
"""
Dead-link reconciliation — close opportunities whose link is genuinely gone.

WHY THIS EXISTS
The export-time liveness check (export_grants.py:_filter_live_urls) is
deliberately conservative: for authoritative `api_` feeds it *flags* a 404 but
keeps the record (to avoid false-dropping valid opportunities on sites that
merely bot-block us). That safety choice let a class of genuinely-dead links
survive — e.g. a connector that hard-codes a URL the funder later removed.

This job closes that gap. It re-probes every live link with a real browser
User-Agent and RETRIES, and only acts on a **definitive, repeated 404/410**
(the one HTTP status a server can't fake). Such records are set
`current_status='Closed'` in the database, which removes them from the live
site on the next export regardless of build mode (Closed rows are excluded by
the export query — so this is robust even on fast/no-liveness builds).

Conservative by design — it NEVER closes on 403 / 429 / timeout / 5xx (those
are "can't tell", usually bot-blocking or rate-limiting), and it skips SPA /
bot-challenge hosts whose 404s are unreliable. A rollback file is written.

Usage:
    python3 close_dead_links.py            # dry-run: report only
    python3 close_dead_links.py --apply    # write Closed status to the DB
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import psycopg2

# SPA / bot-challenge hosts whose HTTP status is unreliable (they can 404 a valid
# route or 200 a dead one) — never auto-close based on their liveness.
SKIP_HOSTS = (
    "grants.gov", "nsf.gov", "research.gov", "nih.gov", "reporter.nih.gov",
    "ec.europa.eu", "ukri.org",
)
DEAD_CODES = {404, 410}
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
ATTEMPTS = 2            # a URL must return a dead code on EVERY attempt
ATTEMPT_GAP = 1.5       # seconds between attempts (filters transient blips)
TIMEOUT = 13


def _get_db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        for rel in ("../Stage_3_LLM_extraction/.env", ".env"):
            p = os.path.join(os.path.dirname(__file__), rel)
            if os.path.isfile(p):
                for line in open(p):
                    if line.strip().startswith("DATABASE_URL="):
                        url = line.strip()[len("DATABASE_URL="):]
                        break
            if url:
                break
    if not url:
        sys.exit("ERROR: DATABASE_URL not set.")
    return url


def _host(url: str) -> str:
    h = urlsplit(url).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def _skip(url: str) -> bool:
    h = _host(url)
    return any(h == s or h.endswith("." + s) for s in SKIP_HOSTS)


_CTX = ssl.create_default_context()


def _status(url: str) -> object:
    """Return the HTTP status code (int), 'DNS' if the host doesn't resolve, or
    'ERR' for any other failure, for a single GET."""
    try:
        req = urllib.request.Request(
            url, method="GET",
            headers={"User-Agent": BROWSER_UA, "Accept": "text/html,*/*"},
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_CTX) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except urllib.error.URLError as e:
        reason = str(getattr(e, "reason", e))
        if isinstance(getattr(e, "reason", None), socket.gaierror) or any(
            s in reason for s in ("Name or service not known", "nodename nor servname",
                                  "getaddrinfo failed", "Temporary failure in name resolution")):
            return "DNS"
        return "ERR"
    except socket.gaierror:
        return "DNS"
    except Exception:
        return "ERR"


def _is_dead(url: str) -> bool:
    """True only if EVERY attempt is a definitive dead signal — a 404/410 OR a
    DNS-resolution failure (the domain is gone). Any 200/3xx/403/429/5xx/timeout
    on any attempt → not dead (we can't be sure). Requiring all attempts (with a
    gap) to fail keeps a transient blip from false-retiring a live opportunity."""
    for i in range(ATTEMPTS):
        s = _status(url)
        if not (s in DEAD_CODES or s == "DNS"):
            return False
        if i < ATTEMPTS - 1:
            time.sleep(ATTEMPT_GAP)
    return True


def _is_alive(url: str) -> bool:
    """True only on a clean 200/3xx — used to REVIVE a previously dead-link-
    retired opportunity whose page has come back. Conservative: a 403/404/timeout
    leaves it retired."""
    s = _status(url)
    return isinstance(s, int) and 200 <= s < 400


RETIRE_TAG = "dead_link"   # written to status_source so retirements are auditable + revivable


def _revive(conn, max_workers: int, apply: bool) -> None:
    """Re-probe opportunities previously retired for a dead link; reopen any whose
    page is alive again (funder restored/moved it back). This protects coverage:
    a recovered opportunity returns to the catalog automatically, and only ever
    when its link genuinely resolves (200/3xx)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, source_url, domain, grant_title FROM grants "
            "WHERE current_status = 'Closed' AND status_source = %s AND source_url LIKE 'http%%'",
            (RETIRE_TAG,),
        )
        retired = cur.fetchall()
    if not retired:
        return
    def chk(rec):
        return (rec, _is_alive(rec[1]))
    revived = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for rec, alive in pool.map(chk, retired):
            if alive:
                revived.append(rec)
    print(f"\nRevival check: {len(retired)} previously retired → {len(revived)} link(s) alive again")
    for i, u, d, t in revived[:8]:
        print(f"    REVIVE [{d}] {t[:42]} → {u[:60]}")
    if revived and apply:
        ids = [str(i) for (i, _u, _d, _t) in revived]
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE grants SET current_status = 'Open', status_source = 'link_revived' "
                "WHERE id = ANY(%s::uuid[])", (ids,),
            )
        conn.commit()
        print(f"  Reopened {len(ids)} recovered opportunity(ies).")


def main() -> None:
    ap = argparse.ArgumentParser(description="Retire dead-link opportunities; revive recovered ones")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    ap.add_argument("--max-workers", type=int, default=16)
    args = ap.parse_args()

    conn = psycopg2.connect(_get_db_url(), connect_timeout=30)

    # Pass 1 — revive previously-retired opportunities whose link is back.
    _revive(conn, args.max_workers, args.apply)

    # Pass 2 — probe the link the site ACTUALLY DISPLAYS (application_portal_url
    # || source_url). If that link is dead but the other URL field is alive,
    # REPAIR the record (point the display at the working link) — don't retire a
    # real, open opportunity just because its portal URL rotted. Only when BOTH
    # URLs are dead is the opportunity retired.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, source_url, application_portal_url, domain, grant_title FROM grants "
            "WHERE current_status <> 'Closed'"
        )
        rows = cur.fetchall()

    def _disp(su, ap):
        return ap or su

    candidates = [
        (i, su, ap, d, t) for (i, su, ap, d, t) in rows
        if _disp(su, ap) and str(_disp(su, ap)).startswith("http") and not _skip(_disp(su, ap))
    ]
    print(f"Live records: {len(rows)} | probing displayed link of {len(candidates)} "
          f"(skipped SPA/challenge hosts)")

    def check(rec):
        i, su, ap, d, t = rec
        disp = _disp(su, ap)
        if not _is_dead(disp):
            return (rec, "ok", None)
        # Displayed link is dead — is the OTHER url field a working alternative?
        other = su if disp == ap else ap
        if other and other != disp and str(other).startswith("http") and _is_alive(other):
            return (rec, "repair", other)
        return (rec, "close", None)

    repairs: list = []   # (rec, working_url)
    closes: list = []
    with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        for rec, action, alt in pool.map(check, candidates):
            if action == "repair":
                repairs.append((rec, alt))
            elif action == "close":
                closes.append(rec)

    print(f"\nDisplayed link dead → REPAIR (working alt exists): {len(repairs)} | "
          f"CLOSE (both urls dead): {len(closes)}")
    for (i, su, ap, d, t), alt in repairs[:8]:
        print(f"    REPAIR [{d}] {t[:38]} → {alt[:58]}")
    for i, su, ap, d, t in closes[:8]:
        print(f"    CLOSE  [{d}] {t[:38]} → {_disp(su, ap)[:58]}")

    if not repairs and not closes:
        print("\nNothing to repair or close.")
        conn.close()
        return

    if not args.apply:
        print(f"\n[DRY RUN] Would repair {len(repairs)} and close {len(closes)}. Re-run with --apply.")
        conn.close()
        return

    stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    rollback = f"/tmp/gg_dead_links_rollback_{stamp}.json"
    json.dump({
        "repairs": [{"id": str(r[0][0]), "to": r[1]} for r in repairs],
        "closes": [{"id": str(c[0]), "url": _disp(c[1], c[2])} for c in closes],
    }, open(rollback, "w"))

    with conn.cursor() as cur:
        for (i, su, ap, d, t), alt in repairs:
            cur.execute(
                "UPDATE grants SET application_portal_url = %s WHERE id = %s::uuid", (alt, str(i)),
            )
        if closes:
            cur.execute(
                "UPDATE grants SET current_status = 'Closed', status_source = %s "
                "WHERE id = ANY(%s::uuid[])", (RETIRE_TAG, [str(c[0]) for c in closes]),
            )
    conn.commit()
    conn.close()
    print(f"\nRepaired {len(repairs)} link(s) to a working URL; closed {len(closes)} "
          f"(both urls dead). Rollback: {rollback}")


if __name__ == "__main__":
    main()
