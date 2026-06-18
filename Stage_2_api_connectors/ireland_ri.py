#!/usr/bin/env python3
"""
Research Ireland connector — Stage 2 API source.

Scrapes open funding calls from https://www.researchireland.ie/funding/
(Research Ireland, the merged SFI + IRC body since 2023.)

The page is a statically-generated Next.js site — all content is present
in the HTML source, no JavaScript execution needed.

Primary parse: __NEXT_DATA__ JSON blob embedded in the page.
Fallback:      regex on raw HTML.

Usage (on the server):
    export $(grep DATABASE_URL /opt/grantglobe/Stage_3_LLM_extraction/.env | xargs)
    python3 Stage_2_api_connectors/ireland_ri.py [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import html
import json
import os
import re
import sys

import psycopg2
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RI_URL  = "https://www.researchireland.ie/funding/"
RI_BASE = "https://www.researchireland.ie"

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

TOPIC_SECTOR_MAP: dict[str, list[str]] = {
    "health":           ["Health Sciences"],
    "medicine":         ["Health Sciences"],
    "clinical":         ["Health Sciences"],
    "cancer":           ["Health Sciences"],
    "brain":            ["Health Sciences"],
    "pandemic":         ["Health Sciences"],
    "antimicrobial":    ["Health Sciences"],
    "disease":          ["Health Sciences"],
    "clean energy":     ["Climate & Environment", "Science & Technology"],
    "energy":           ["Climate & Environment", "Science & Technology"],
    "climate":          ["Climate & Environment"],
    "environment":      ["Climate & Environment"],
    "agriculture":      ["Climate & Environment", "Science & Technology"],
    "digital":          ["Science & Technology", "Information & Communication Technologies"],
    "engineering":      ["Science & Technology", "Technology & Innovation"],
    "physics":          ["Science & Technology"],
    "chemistry":        ["Science & Technology"],
    "humanities":       ["Social Sciences & Humanities"],
    "creative":         ["Social Sciences & Humanities", "Arts & Culture"],
    "social":           ["Social Sciences & Humanities"],
    "education":        ["Education & Training"],
    "postdoc":          ["Research & Innovation"],
    "postgraduate":     ["Education & Training"],
    "fellowship":       ["Research & Innovation"],
    "innovation":       ["Technology & Innovation"],
    "sustainability":   ["Climate & Environment"],
    "sdg":              ["Climate & Environment"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _parse_deadline(text: str) -> str | None:
    """
    Parse deadline text like:
      "8th October 2026, 13:00 (local Irish time)"
      "3rd November 2026"
      "Rolling"
      "Pre-proposal deadline: 10th March 2026"   ← skip pre-proposal dates
    Returns ISO date string or None.
    """
    if not text:
        return None
    t = text.strip()
    if re.match(r"rolling", t, re.IGNORECASE):
        return None
    # Pre-proposal deadlines are interim milestones, not the main deadline
    if re.search(r"pre.?proposal", t, re.IGNORECASE):
        return None
    # Remove ordinal suffixes: "8th" → "8", "1st" → "1"
    t = re.sub(r"(\d+)(?:st|nd|rd|th)\b", r"\1", t, flags=re.IGNORECASE)
    # "8 October 2026" or "8 October 2026, 13:00 ..."
    m = re.search(
        r"(\d{1,2})\s+(" + "|".join(_MONTHS) + r")\s+(20\d{2})\b",
        t, re.IGNORECASE,
    )
    if m:
        mon = _MONTHS.get(m.group(2).lower())
        if mon:
            try:
                return datetime.date(int(m.group(3)), mon, int(m.group(1))).isoformat()
            except ValueError:
                pass
    # "October 8, 2026"
    m = re.search(
        r"(" + "|".join(_MONTHS) + r")\s+(\d{1,2}),?\s+(20\d{2})\b",
        t, re.IGNORECASE,
    )
    if m:
        mon = _MONTHS.get(m.group(1).lower())
        if mon:
            try:
                return datetime.date(int(m.group(3)), mon, int(m.group(2))).isoformat()
            except ValueError:
                pass
    return None


def _parse_amount(text: str) -> tuple[float | None, float | None]:
    """Parse award amount text like '€350,000 - €700,000', 'Max €500,000'."""
    if not text:
        return None, None
    nums = [float(n.replace(",", "")) for n in re.findall(r"[\d,]+", text) if n.replace(",", "").isdigit()]
    if not nums:
        return None, None
    if len(nums) == 1:
        return nums[0], nums[0]
    return min(nums), max(nums)


def _infer_sectors(text: str) -> list[str]:
    t = text.lower()
    sectors: list[str] = []
    for kw, sl in TOPIC_SECTOR_MAP.items():
        if kw in t:
            sectors.extend(s for s in sl if s not in sectors)
    return sectors or ["Research & Innovation"]


def _get_db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        env = os.path.join(
            os.path.dirname(__file__), "..", "Stage_3_LLM_extraction", ".env"
        )
        if os.path.isfile(env):
            with open(env) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("DATABASE_URL="):
                        url = line[len("DATABASE_URL="):]
                        break
    if not url:
        sys.exit("ERROR: DATABASE_URL not set.")
    return url


def _connect():
    return psycopg2.connect(_get_db_url(), connect_timeout=30)


# ---------------------------------------------------------------------------
# Fetching & parsing
# ---------------------------------------------------------------------------

def _fetch_page(session: requests.Session) -> str | None:
    try:
        resp = session.get(RI_URL, timeout=30)
        resp.raise_for_status()
        resp.encoding = "utf-8"   # Next.js always serves UTF-8; prevent latin-1 mis-decode
        return resp.text
    except Exception as e:
        print(f"  WARNING: RI fetch failed: {e}")
        return None


def _find_items_in_json(obj, depth: int = 0):
    """
    DFS through a JSON blob looking for the first list that looks like
    a list of funding programmes (dicts with title/slug/status keys).
    """
    if depth > 10:
        return None
    if isinstance(obj, list) and len(obj) >= 2:
        sample = obj[0] if obj else {}
        if isinstance(sample, dict):
            keys = set(sample.keys())
            if any(k in keys for k in ("title", "slug", "status", "deadline", "name")):
                return obj
    if isinstance(obj, dict):
        for v in obj.values():
            result = _find_items_in_json(v, depth + 1)
            if result:
                return result
    return None


def _parse_next_data(page_html: str) -> list[dict]:
    """Extract funding items from Next.js __NEXT_DATA__ JSON blob."""
    m = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>\s*(\{.*?\})\s*</script>',
        page_html, re.DOTALL,
    )
    if not m:
        print("  RI: no __NEXT_DATA__ script tag found")
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        print(f"  RI: __NEXT_DATA__ JSON decode error: {e}")
        return []

    raw_items = _find_items_in_json(data)
    if not raw_items:
        print("  RI: no funding items array found in __NEXT_DATA__")
        return []

    items = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("name") or "").strip()
        if not title:
            continue
        status = str(item.get("status") or item.get("callStatus") or "").strip()
        slug   = str(item.get("slug") or item.get("url") or "").strip("/")
        url    = f"{RI_BASE}/funding/{slug}/" if slug else ""

        deadline_raw = str(
            item.get("deadline") or item.get("deadlineDate") or
            item.get("closingDate") or item.get("closing_date") or ""
        ).strip()
        if isinstance(item.get("deadline"), dict):
            deadline_raw = str(
                item["deadline"].get("date") or item["deadline"].get("value") or ""
            ).strip()

        amount_raw = str(
            item.get("awardAmount") or item.get("award_amount") or
            item.get("amount") or ""
        ).strip()

        desc_raw = (
            item.get("description") or item.get("excerpt") or
            item.get("summary") or ""
        )
        if isinstance(desc_raw, dict):
            desc_raw = (
                desc_raw.get("text") or desc_raw.get("value") or ""
            )
        desc = _strip_html(str(desc_raw)).strip()
        # __NEXT_DATA__ sometimes embeds description as HTML truncated mid-tag
        # (e.g. `...life. <a class="btn ...` with no closing >).
        # _strip_html strips complete tags; cut off any orphaned < that remains.
        lt_pos = desc.find("<")
        if lt_pos >= 0:
            desc = desc[:lt_pos].strip()
        desc = desc[:500]

        items.append({
            "title":        title,
            "url":          url,
            "status":       status,
            "deadline_raw": deadline_raw,
            "amount_raw":   amount_raw,
            "description":  desc,
        })

    print(f"  RI: parsed {len(items)} items from __NEXT_DATA__")
    return items


def _parse_html_fallback(page_html: str) -> list[dict]:
    """
    Fallback: regex parse the raw HTML.

    The page structure (from web_fetch observation) has each item as:
        <status>Open or Closed</status>
        <h3>Title</h3>
        <p>Description</p>
        <a href="/funding/slug/">Learn more</a>
        <dt/dd or div> Deadline: TEXT </dt/dd>
        ...

    We split on h3 headings and look backwards for status, forwards for link+deadline.
    """
    items = []
    today = datetime.date.today()

    h3_matches = list(re.finditer(r"<h3[^>]*>(.*?)</h3>", page_html, re.DOTALL))

    for h3_m in h3_matches:
        title = _strip_html(h3_m.group(1)).strip()
        if not title or len(title) < 5:
            continue

        # Context windows
        pre_ctx  = page_html[max(0, h3_m.start() - 800) : h3_m.start()]
        post_ctx = page_html[h3_m.end() : min(len(page_html), h3_m.end() + 2000)]

        # Status: last occurrence of Open/Closed/Upcoming in pre-context text
        pre_text = _strip_html(pre_ctx)
        status_words = re.findall(r"\b(Open|Closed|Upcoming)\b", pre_text)
        status = status_words[-1] if status_words else "Unknown"

        # Link: first /funding/<slug>/ href in post-context
        link_m = re.search(r'href="(/funding/[a-z0-9\-]+/?)"', post_ctx, re.IGNORECASE)
        if not link_m:
            continue
        url = RI_BASE + "/" + link_m.group(1).lstrip("/")

        # Description: text between h3 and the link
        pre_link = post_ctx[: link_m.start()]
        description = _strip_html(pre_link).strip()
        _lt = description.find('<')
        if _lt >= 0:
            description = description[:_lt].strip()
        description = description[:500]

        # Deadline: look for "Deadline" label followed by date text
        deadline_raw = ""
        _post_clean = re.sub(r'<!--.*?-->', '', post_ctx[link_m.end():])
        _post_text = re.sub(r'<[^>]+>', ' ', _post_clean)
        dl_m = re.search(
            r'[Dd]eadline\s*:\s*(\S[^\n]{4,119})',
            _post_text,
            re.IGNORECASE,
        )
        if dl_m:
            _dr = _strip_html(dl_m.group(1)).strip()
            _lt = _dr.find('<')
            if _lt >= 0: _dr = _dr[:_lt].strip()
            for _sep in [' Programme Type', ' Career Stage', ' Award Amount', ' Duration']:
                if _sep in _dr: _dr = _dr[:_dr.index(_sep)].strip(); break
            deadline_raw = _dr

        # Award amount: look for currency symbol patterns
        amount_raw = ""
        am_m = re.search(r"[€£\$][\d,\. \-–]+(?:M|million|k)?", post_ctx[link_m.end():])
        if am_m:
            amount_raw = _strip_html(am_m.group(0)).strip()

        items.append({
            "title":        title,
            "url":          url,
            "status":       status,
            "deadline_raw": deadline_raw,
            "amount_raw":   amount_raw,
            "description":  description,
        })

    # Deduplicate by URL
    seen: set[str] = set()
    deduped = []
    for item in items:
        if item["url"] not in seen:
            seen.add(item["url"])
            deduped.append(item)

    print(f"  RI: parsed {len(deduped)} items via HTML fallback")
    return deduped


def _enrich_from_html(items: list[dict], page_html: str) -> list[dict]:
    """
    After __NEXT_DATA__ parsing, deadline/amount metadata lives only in the
    rendered HTML (DT/DD or labelled divs), not in the JSON blob.

    Strategy:
      - Each item's slug href appears TWICE: once in the h3 title link, once
        in the "Learn more" button. The deadline appears AFTER the button.
      - Search for the second occurrence of the slug href to start the context.
      - For deadline: find any "Deadline" text then look for a date pattern
        within the next 400 chars (avoids Tailwind colon-containing classes).
    """
    _DATE_PAT = re.compile(
        r"\d{1,2}(?:st|nd|rd|th)?\s+"
        r"(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+20\d{2}",
        re.IGNORECASE,
    )

    for item in items:
        url = item.get("url", "")
        if not url:
            continue
        slug = url.replace(RI_BASE, "")   # /funding/clean-energy-transition-partnership/

        # Find first occurrence (h3 title link)
        first_pos = page_html.find(f'href="{slug}')
        if first_pos < 0:
            first_pos = page_html.find(f'href="{slug.rstrip("/")}')
        if first_pos < 0:
            continue

        # Find second occurrence (Learn more button) — deadline comes after this
        second_pos = page_html.find(f'href="{slug}', first_pos + 1)
        if second_pos < 0:
            second_pos = page_html.find(f'href="{slug.rstrip("/")}', first_pos + 1)

        search_from = second_pos if second_pos >= 0 else first_pos
        ctx = page_html[search_from: search_from + 2000]

        # Deadline — strip React <!-- --> comments so regex can cross them
        if not item.get("deadline_raw"):
            ctx_clean = re.sub(r'<!--.*?-->', '', ctx)
            for dl_m in re.finditer(r"\bDeadline\b", ctx_clean, re.IGNORECASE):
                date_window = ctx_clean[dl_m.start(): dl_m.start() + 400]
                # Stage 1: "Deadline: <text>" (works once comments are stripped)
                colon_m = re.search(r"Deadline\s*:\s*([^\n<]{5,120})", date_window, re.IGNORECASE)
                if colon_m:
                    item["deadline_raw"] = _strip_html(colon_m.group(1)).strip()
                    break
                # Stage 2: next calendar date pattern after "Deadline"
                date_m = _DATE_PAT.search(date_window[len("Deadline"):])
                if date_m:
                    item["deadline_raw"] = date_m.group(0)
                    break

        # Award amount
        if not item.get("amount_raw"):
            am_m = re.search(r"[€£\$][\d,][\d,\.\s\-–Mmillion]+", ctx)
            if am_m:
                item["amount_raw"] = _strip_html(am_m.group(0)).strip()

    return items


def _fetch_ri_calls() -> list[dict]:
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "en-GB,en;q=0.5",
    })

    page_html = _fetch_page(session)
    if not page_html:
        return []
    print(f"  RI: {len(page_html)} chars fetched")

    # Primary: __NEXT_DATA__ JSON (gives title/url/status; deadline/amount often absent)
    items = _parse_next_data(page_html)
    if items:
        # Deadline and award amount are in the rendered HTML, not __NEXT_DATA__
        items = _enrich_from_html(items, page_html)

    # Fallback: HTML regex
    if not items:
        items = _parse_html_fallback(page_html)

    # Keep only Open items
    open_items = [i for i in items if i.get("status", "").strip().lower() == "open"]
    print(f"  RI: {len(open_items)} open calls (of {len(items)} total)")
    return open_items


# ---------------------------------------------------------------------------
# Mapping & upserting
# ---------------------------------------------------------------------------

def _map_call(item: dict) -> dict | None:
    title = item.get("title", "").strip()
    url   = item.get("url", "").strip()
    if not title or not url:
        return None

    deadline_raw = item.get("deadline_raw", "") or ""
    deadline_iso = _parse_deadline(deadline_raw)

    # If parsed deadline is in the past, clear it but keep the item
    # (the site still marks it Open — pre-proposal stage may have passed)
    if deadline_iso:
        try:
            if datetime.date.fromisoformat(deadline_iso) < datetime.date.today():
                deadline_iso = None
        except ValueError:
            pass

    amount_raw        = item.get("amount_raw", "") or ""
    amt_min, amt_max  = _parse_amount(amount_raw)

    combined = title + " " + (item.get("description") or "") + " " + (amount_raw or "")

    return {
        "grant_title":               title,
        "funder_name":               "Research Ireland",
        "source_url":                url,
        "application_portal_url":    url,
        "description":               (item.get("description") or None),
        "application_deadline":      deadline_iso,
        "application_deadline_raw":  deadline_raw if deadline_raw else None,
        "grant_opening_date":        None,
        "current_status":            "Open",
        "source_language":           "en",
        "funding_amount_min":        amt_min,
        "funding_amount_max":        amt_max,
        "currency":                  "EUR" if amt_min is not None else None,
        "thematic_sectors":          _infer_sectors(combined),
        "grant_types":               ["Research Grant"],
        "applicant_base_regions":    ["Europe"],
        "geographic_focus_regions":  ["Europe"],
        "applicant_base_countries":  ["IE"],
        "geographic_focus_countries": [],
        "organisation_types":        ["University", "Research Institution"],
        "individual_eligibility":    [],
        "domain":                    "api_ri",
        "review_status":             "approved",
        "requires_review":           False,
        "crawl_date":                datetime.date.today().isoformat(),
        "content_hash":              hashlib.sha256(
            f"{url}|{title}|{deadline_iso}".encode()
        ).hexdigest(),
    }


def _upsert_grant(cur, g: dict) -> str:
    cur.execute(
        "SELECT id, review_status FROM grants WHERE source_url = %s",
        (g["source_url"],)
    )
    existing = cur.fetchone()
    if existing:
        if existing[1] == "rejected":
            return "skipped"
        set_clauses = ", ".join(f"{k} = %({k})s" for k in g if k != "source_url")
        cur.execute(
            f"UPDATE grants SET {set_clauses} WHERE id = %(id)s",
            {**g, "id": existing[0]},
        )
        return "updated"
    cols = list(g.keys())
    cur.execute(
        f"INSERT INTO grants ({', '.join(cols)}) VALUES "
        f"({', '.join(f'%({c})s' for c in cols)})",
        g,
    )
    return "inserted"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Research Ireland → GrantGlobe ingestor")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("Fetching Research Ireland open funding calls …")
    raw_calls = _fetch_ri_calls()
    print(f"  {len(raw_calls)} open calls found.")

    mapped = []
    for item in raw_calls:
        g = _map_call(item)
        if g:
            mapped.append(g)

    seen: set[str] = set()
    deduped = [g for g in mapped if not (g["source_url"] in seen or seen.add(g["source_url"]))]
    print(f"  {len(deduped)} calls to upsert after deduplication.")

    if args.dry_run:
        print("\n[DRY RUN] First 3 records:")
        for g in deduped[:3]:
            print(json.dumps(g, indent=2, default=str))
        print(f"\n[DRY RUN] Would upsert {len(deduped)} records.")
        return

    if not deduped:
        print("  Nothing to upsert.")
        return

    conn = _connect()
    try:
        counts = {"inserted": 0, "updated": 0, "skipped": 0}
        for i in range(0, len(deduped), 200):
            batch = deduped[i : i + 200]
            with conn.cursor() as cur:
                for g in batch:
                    counts[_upsert_grant(cur, g)] += 1
            conn.commit()
            print(f"  Progress: {min(i + 200, len(deduped))}/{len(deduped)}")
    finally:
        conn.close()

    print(
        f"\nDone: {counts['inserted']} inserted, {counts['updated']} updated, "
        f"{counts['skipped']} skipped."
    )


if __name__ == "__main__":
    main()
