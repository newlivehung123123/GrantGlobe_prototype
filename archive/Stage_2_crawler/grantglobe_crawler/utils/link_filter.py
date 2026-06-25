"""
Two-tier Link Intelligence Filter — spec §2.2 Link Intelligence Filter.

Implemented as a module-level function (no Scrapy dependency) so that
tests can import it directly without instantiating a spider.

The spider's ``_passes_link_filter`` method is a thin wrapper:

    def _passes_link_filter(self, url, depth=1):
        return passes_link_filter(url, depth=depth)

Usage::

    from grantglobe_crawler.utils.link_filter import passes_link_filter
    passes_link_filter("https://example.org/grants/open-call/")   # True
    passes_link_filter("https://example.org/staff/team.jpg")      # False (Tier 1)
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Tier 1 — Hard exclusions
# spec §2.2 "Tier 1 — Hard exclusions (discard immediately)"
# ---------------------------------------------------------------------------

# File extensions that are never grant-relevant HTML or PDF content.
# NOTE: .pdf is intentionally ABSENT — PDFs pass Tier 1 and receive +3 in Tier 2.
_TIER1_EXTENSIONS: frozenset[str] = frozenset(
    [
        "jpg", "jpeg", "png", "gif", "svg", "ico",
        "css", "js",
        "woff", "woff2", "ttf", "eot",
        "mp4", "mp3",
        "zip", "tar", "gz",
    ]
)

# Path-segment tokens that unambiguously signal a non-grant page.
# Exact-match after splitting the path on '/', '-', '_'.
# These words essentially never appear in legitimate grant-page URLs.
_TIER1_PATH_SEGMENTS: frozenset[str] = frozenset(
    [
        "login", "signin", "signup", "register", "logout",
        "cart", "checkout", "basket",
        "account", "profile",
        "password", "reset", "unsubscribe",
        "privacy", "terms", "cookie", "gdpr",
        "sitemap", "search",
        "print", "share",
        "mailto",
    ]
)

# ---------------------------------------------------------------------------
# Tier 2 — Relevance scoring
# spec §2.2 "Tier 2 — Relevance scoring"
# ---------------------------------------------------------------------------

# Positive-signal prefixes: each matching token adds +1.
# Includes partial stems (e.g. "financ" matches "finance", "financial";
# "opportunit" matches "opportunity", "opportunities") so that plurals and
# derived forms are captured without explicit enumeration.
# spec §2.2 positive signals list + programme/scheme/initiative group.
_TIER2_POSITIVE: tuple[str, ...] = (
    "grant", "fund", "financ",
    "fellowship", "scholarship",
    "award", "opportunit",
    "call", "proposal",
    "support", "bursary", "prize",
    "endow", "philanthrop",
    "donation", "subsid",
    "application", "deadline",
    "programme", "program",
    "scheme", "initiative",
    "project", "mechanism", "instrument",
)

# Negative-signal prefixes: each matching token subtracts -1.
# These are NOT hard exclusions — spec §2.2 explicitly states that news, blog,
# event, press, media are "not applied as blanket negative signals".
# A URL scoring ≤ 0 is discarded; a URL where positive signals outweigh these
# still passes (e.g. /news/grant-deadline/ → -1 +1 +1 = +1 → pass).
_TIER2_NEGATIVE: tuple[str, ...] = (
    "staff", "team", "board", "director",
    "contact", "about",
    "history", "mission", "vision",
    "press", "media", "news",
)

# Regex to split a URL path into tokens on '/', '-', '_'.
# Using '+' so consecutive delimiters are treated as one separator.
_SPLIT_RE: re.Pattern = re.compile(r"[/_\-]+")

# PDF extension check (case-insensitive).
_PDF_RE: re.Pattern = re.compile(r"\.pdf$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def passes_link_filter(url: str, depth: int = 1) -> bool:
    """
    Return True if *url* should be added to the crawl queue.

    Parameters
    ----------
    url:
        Absolute URL to evaluate (after canonicalisation).
    depth:
        Crawl depth at which this URL was discovered.  At depth 0 (seed
        page), the scoring threshold is relaxed to ≥ −1 per spec §2.2
        "threshold is relaxed to ≥ −1 to ensure broad initial coverage".
        Default is 1 (strict threshold: score must be strictly > 0).

    Algorithm
    ---------
    0. PDF early-exit  — .pdf paths always return True (+3 virtual score).
    1. Tier 1 extension check  — discard known non-content extensions.
    2. Tier 1 path-segment check — discard hard-exclusion tokens.
    3. Tier 2 scoring — sum +1 per positive prefix, -1 per negative prefix.
       Threshold: score > 0 (or score ≥ -1 at depth 0).

    Spec ref: §2.2 Link Intelligence Filter (both tiers).
    """
    if not url:
        return False

    parsed = urlparse(url)
    path = parsed.path.lower()

    # ── Step 0: PDF early-exit ────────────────────────────────────────────
    # PDFs score +3 "regardless of path content" (spec §2.2).  They must not
    # be rejected by Tier 1 path-segment checks (e.g. a path containing the
    # word "profile" would otherwise discard a PDF about applicant profiles).
    if _PDF_RE.search(path):
        return True  # spec §2.2: PDF links score +3, always pass

    # ── Step 1: Tier 1 extension check ────────────────────────────────────
    # Extract the extension from the final path segment.
    final_segment = path.rsplit("/", 1)[-1]
    if "." in final_segment:
        ext = final_segment.rsplit(".", 1)[-1]
        if ext in _TIER1_EXTENSIONS:
            return False  # spec §2.2 Tier 1 hard exclusion — extension

    # ── Step 2: Tier 1 path-segment check ─────────────────────────────────
    # Split the full path on '/', '-', '_' and check each non-empty token
    # for exact membership in the hard-exclusion set.
    tokens = [t for t in _SPLIT_RE.split(path) if t]
    token_set = set(tokens)
    if token_set & _TIER1_PATH_SEGMENTS:
        return False  # spec §2.2 Tier 1 hard exclusion — path segment

    # ── Step 3: Tier 2 relevance scoring ──────────────────────────────────
    score = 0
    for token in tokens:
        # Positive signals: prefix match to handle plurals and derived forms.
        for prefix in _TIER2_POSITIVE:
            if token.startswith(prefix):
                score += 1
                break  # only count each token once
        else:
            # Negative signals: prefix match (only reached if no +1 fired).
            for prefix in _TIER2_NEGATIVE:
                if token.startswith(prefix):
                    score -= 1
                    break

    # Apply depth-dependent threshold.
    # spec §2.2: "at depth 0 … threshold is relaxed to ≥ −1"
    threshold = -1 if depth == 0 else 0
    return score > threshold
