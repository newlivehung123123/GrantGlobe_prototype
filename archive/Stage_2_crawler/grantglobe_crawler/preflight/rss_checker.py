"""
RSS/Atom feed detection — spec §2.1 RSS/Atom feed detection.

Implements the three detection methods in order:

Method 1 — HTML ``<link rel="alternate">`` autodiscovery
    Inspects the seed page's ``<head>`` for standard machine-readable feed
    declarations.  Present on most WordPress/Drupal/Joomla grant sites.

Method 2 — Common path probe
    Probes the paths in ``settings.FEED_PROBE_PATHS``.
    - ``application/rss+xml`` or ``application/atom+xml`` → confirmed.
    - ``text/xml``: also verify that the XML root element is ``<rss>`` or
      ``<feed>`` before accepting.  Prevents false positives from sitemaps,
      SOAP responses, or generic XML APIs that share the probe path.
    Spec ref: §2.1 — "text/xml responses require one additional check".

Method 3 — robots.txt / already-parsed content cross-reference
    Scans the robots.txt raw text (and any other pre-parsed content passed
    in) for URL-like strings that match known feed path patterns.

All I/O is via ``feedparser`` (for parsing) and ``requests`` (for probing).
This module is called from ``preflight.py``, which runs outside the
Scrapy/Twisted reactor.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import feedparser
import requests

logger = logging.getLogger(__name__)

_TIMEOUT_S: float = 15.0
_PROBE_UA: str = "GrantGlobe-Preflight/1.0 (pre-flight probe)"

# Regex that matches URL-like strings anywhere in a text block.
# Used for Method 3 (robots.txt cross-reference).
_URL_RE: re.Pattern = re.compile(r"https?://\S+", re.IGNORECASE)

# Feed path keywords used to recognise feed URLs in Method 3.
_FEED_PATH_KEYWORDS: frozenset[str] = frozenset(
    ["feed", "rss", "atom", "rss.xml", "atom.xml", "feed.xml"]
)


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------


@dataclass
class FeedCheckResult:
    """
    Outcome of the three-method feed detection pass for one domain.
    Written into ``crawl_manifest.json``.
    """

    feed_url: str | None = None
    """Confirmed feed URL, or None if no feed was found."""

    detected_by: str | None = None
    """
    Which method confirmed the feed:
    ``"autodiscovery"``  — HTML ``<link rel="alternate">``
    ``"path_probe"``     — successful probe of a candidate path
    ``"robots_crossref"``— URL found in robots.txt / sitemap content
    """

    @property
    def found(self) -> bool:
        return self.feed_url is not None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def detect_feed(
    seed_url: str,
    seed_html: str | None = None,
    robots_txt_content: str | None = None,
) -> FeedCheckResult:
    """
    Run all three feed-detection methods in order and return on first success.

    Parameters
    ----------
    seed_url:
        The domain's grants_url (used to derive the origin for path probing).
    seed_html:
        Full HTML of the seed page if already fetched (avoids a redundant GET).
        May be None; in that case Method 1 is skipped gracefully.
    robots_txt_content:
        Raw text of robots.txt if already fetched by ``robotstxt_parser``.
        Used by Method 3.

    Returns
    -------
    FeedCheckResult
        ``feed_url`` is None if no feed was confirmed by any method.
    """
    parsed = urlparse(seed_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    # Method 1 — HTML <link> autodiscovery
    if seed_html:
        feed_url = _method1_autodiscovery(seed_html, origin)
        if feed_url:
            logger.info("Feed found via autodiscovery for %s: %s", origin, feed_url)
            return FeedCheckResult(feed_url=feed_url, detected_by="autodiscovery")

    # Method 2 — probe common feed paths
    feed_url = _method2_path_probe(origin)
    if feed_url:
        logger.info("Feed found via path probe for %s: %s", origin, feed_url)
        return FeedCheckResult(feed_url=feed_url, detected_by="path_probe")

    # Method 3 — robots.txt / sitemap cross-reference
    if robots_txt_content:
        feed_url = _method3_robots_crossref(robots_txt_content, origin)
        if feed_url:
            logger.info(
                "Feed found via robots.txt cross-ref for %s: %s", origin, feed_url
            )
            return FeedCheckResult(feed_url=feed_url, detected_by="robots_crossref")

    return FeedCheckResult()


# ---------------------------------------------------------------------------
# Method 1 — HTML <link rel="alternate"> autodiscovery
# ---------------------------------------------------------------------------


class _LinkTagParser(HTMLParser):
    """
    Minimal SAX-style HTML parser that collects ``<link rel="alternate">``
    elements with an RSS or Atom type attribute.
    """

    _FEED_TYPES: frozenset[str] = frozenset(
        ["application/rss+xml", "application/atom+xml"]
    )

    def __init__(self) -> None:
        super().__init__()
        self.feed_hrefs: list[str] = []
        self._in_head: bool = True  # only scan until </head>

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if not self._in_head:
            return
        if tag.lower() != "link":
            return
        attr_dict = {k.lower(): (v or "").lower() for k, v in attrs}
        if attr_dict.get("rel") != "alternate":
            return
        if attr_dict.get("type", "") in self._FEED_TYPES:
            # Re-read attrs to get the original (non-lowercased) href value.
            href_original = next(
                (v for k, v in attrs if k.lower() == "href" and v), None
            )
            if href_original:
                self.feed_hrefs.append(href_original)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "head":
            self._in_head = False


def _method1_autodiscovery(html: str, origin: str) -> str | None:
    """
    Parse *html* for ``<link rel="alternate" type="application/rss+xml">``
    or ``…atom+xml`` elements and return the first resolved feed URL, or None.
    Spec ref: §2.1 Method 1 — HTML ``<link>`` autodiscovery.
    """
    parser = _LinkTagParser()
    try:
        parser.feed(html)
    except Exception as exc:
        logger.debug("HTML parser error in autodiscovery: %s", exc)
        return None

    for href in parser.feed_hrefs:
        resolved = urljoin(origin, href)
        if _is_confirmed_feed(resolved):
            return resolved
    return None


# ---------------------------------------------------------------------------
# Method 2 — common path probe
# ---------------------------------------------------------------------------


def _method2_path_probe(origin: str) -> str | None:
    """
    Probe each path in ``settings.FEED_PROBE_PATHS`` and return the first
    URL that is confirmed as a feed, or None.
    Spec ref: §2.1 Method 2 — Common path probe.
    """
    try:
        from grantglobe_crawler import settings
        probe_paths: list[str] = settings.FEED_PROBE_PATHS
        feed_content_types: list[str] = settings.FEED_CONTENT_TYPES
    except Exception:
        probe_paths = ["/feed", "/rss", "/rss.xml", "/atom.xml", "/feed.xml", "/news/feed"]
        feed_content_types = ["application/rss+xml", "application/atom+xml"]

    for path in probe_paths:
        candidate = urljoin(origin, path)
        if _is_confirmed_feed(candidate, explicit_content_types=feed_content_types):
            return candidate
    return None


# ---------------------------------------------------------------------------
# Method 3 — robots.txt / sitemap cross-reference
# ---------------------------------------------------------------------------


def _method3_robots_crossref(robots_content: str, origin: str) -> str | None:
    """
    Scan *robots_content* for URL-like strings containing feed-path keywords.
    Returns the first matching URL that is also confirmed as a feed, or None.
    Spec ref: §2.1 Method 3 — robots.txt and sitemap cross-reference.
    """
    candidate_urls: list[str] = []
    for match in _URL_RE.finditer(robots_content):
        url = match.group(0).rstrip(".,;)")  # strip trailing punctuation
        path = urlparse(url).path.lower()
        path_tokens = set(re.split(r"[/_.-]", path))
        if path_tokens & _FEED_PATH_KEYWORDS:
            candidate_urls.append(url)

    for candidate in candidate_urls:
        # Resolve relative to origin in case the URL is domain-relative.
        resolved = urljoin(origin, candidate)
        if _is_confirmed_feed(resolved):
            return resolved
    return None


# ---------------------------------------------------------------------------
# Shared feed confirmation helper
# ---------------------------------------------------------------------------


def _is_confirmed_feed(
    url: str,
    explicit_content_types: list[str] | None = None,
) -> bool:
    """
    Return True if *url* responds with a valid RSS or Atom feed.

    Acceptance rules (spec §2.1 Method 2):
    - ``application/rss+xml`` or ``application/atom+xml`` → confirmed.
    - ``text/xml`` or ``application/xml`` → check the XML root element:
      must be ``<rss>`` or ``<feed>`` before acceptance.
    - Any other Content-Type → rejected.

    Uses ``feedparser.parse()`` which makes the HTTP request and parses
    the feed in one call.  ``feedparser`` sets ``d.version`` to a non-empty
    string (e.g. ``rss20``, ``atom10``) only when it successfully identifies
    a feed structure, which satisfies the root-element requirement for
    text/xml responses.
    """
    if explicit_content_types is None:
        try:
            from grantglobe_crawler import settings
            explicit_content_types = settings.FEED_CONTENT_TYPES
        except Exception:
            explicit_content_types = ["application/rss+xml", "application/atom+xml"]

    try:
        d = feedparser.parse(url, agent=_PROBE_UA, request_headers={"Range": ""})
    except Exception as exc:
        logger.debug("feedparser error for %s: %s", url, exc)
        return False

    # feedparser may return status=0 on network error.
    status = d.get("status", 0)
    if status not in (200, 206):
        return False

    content_type: str = d.get("headers", {}).get("content-type", "").lower()
    # Strip parameters (e.g. "; charset=utf-8").
    ct_base = content_type.split(";")[0].strip()

    for accepted in explicit_content_types:
        if accepted.lower() in ct_base:
            # Unambiguous feed content type — confirmed.
            return True

    if ct_base in ("text/xml", "application/xml", "text/plain"):
        # Ambiguous: require feedparser to have identified a known feed format.
        # feedparser sets d.version to e.g. "rss20", "atom10", "rss10", etc.
        # An empty string means it could not identify a feed structure.
        version: str = d.get("version", "")
        return bool(version)

    return False
