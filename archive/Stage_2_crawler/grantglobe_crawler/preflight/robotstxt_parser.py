"""
robots.txt fetching, parsing, and sitemap discovery — spec §2.1.

Responsibilities
----------------
1. Fetch robots.txt for a domain and extract:
   - ``Crawl-delay`` directive → ``rate_limit_floor_seconds``
   - ``Sitemap:`` directives → ``sitemap_url`` (source: "directive")
2. If no ``Sitemap:`` directive is found, probe:
   - ``{origin}/sitemap.xml``
   - ``{origin}/sitemap_index.xml``  (fallback)
   → ``sitemap_url`` (source: "fallback_probe")
3. Fetch and parse the resolved sitemap XML; extract URLs whose path
   contains any segment from ``settings.SITEMAP_GRANT_SIGNALS``.
   These URLs are returned for injection into the spider's start queue.
4. Return the raw robots.txt text to ``rss_checker.py`` (Method 3).

All I/O is synchronous (``requests`` library).  This module is called
from ``preflight.py`` which runs outside the Scrapy/Twisted reactor.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

logger = logging.getLogger(__name__)

# Default request timeout for all probes in this module.
_TIMEOUT_S: float = 20.0

# Minimal UA for pre-flight probes — not a real browser UA (pre-flight runs
# before the USERAGENT_POOL assignment that happens at session start).
_PROBE_UA: str = "GrantGlobe-Preflight/1.0 (pre-flight probe; not a production crawler)"

# Sitemap XML namespace used by the sitemaps.org protocol.
_SITEMAP_NS: dict[str, str] = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

# Regex to detect any URL-like string in robots.txt comments or directives.
_URL_PATTERN: re.Pattern = re.compile(r"https?://\S+", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------


@dataclass
class RobotsResult:
    """
    Parsed outcome of a robots.txt + sitemap pre-flight check for one domain.
    All fields are written directly into ``crawl_manifest.json``.
    """

    robots_txt_fetched: bool = False
    """True if robots.txt returned a 2xx response."""

    crawl_delay: float | None = None
    """
    Value of the ``Crawl-delay`` directive for ``*`` (any user-agent).
    When not None, this value overwrites ``rate_limit_floor_seconds`` in the
    manifest — the spec mandates honouring robots.txt Crawl-delay as the floor.
    Spec ref: §2.1 robots.txt policy — "Honour Crawl-delay directives".
    """

    sitemap_url: str | None = None
    """Resolved sitemap URL, or None if neither directive nor probe found one."""

    sitemap_url_source: str | None = None
    """``"directive"`` (from robots.txt ``Sitemap:``) or ``"fallback_probe"``."""

    sitemap_grant_urls: list[str] = field(default_factory=list)
    """
    URLs extracted from the sitemap whose path contains a grant-signal segment.
    Injected into the spider's start queue at depth 1.
    Spec ref: §2.1 Sitemap.xml check.
    """

    raw_robots_content: str | None = None
    """
    Full text of the fetched robots.txt.  Passed to ``rss_checker.py``
    (Method 3) to search for feed URL patterns in comments.
    """


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def fetch_robots_and_sitemap(seed_url: str) -> RobotsResult:
    """
    Run the full robots.txt + sitemap pre-flight check for the domain of
    *seed_url*.

    Parameters
    ----------
    seed_url:
        Any URL on the target domain.  Only the scheme + host are used to
        construct ``{origin}/robots.txt``.

    Returns
    -------
    RobotsResult
        Populated result ready to be merged into ``crawl_manifest.json``.
    """
    result = RobotsResult()
    parsed = urlparse(seed_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    # Step 1 — fetch robots.txt
    robots_url = urljoin(origin, "/robots.txt")
    raw_content = _fetch_text(robots_url)
    if raw_content is None:
        logger.debug("robots.txt not reachable for %s", origin)
        return result

    result.robots_txt_fetched = True
    result.raw_robots_content = raw_content

    # Step 2 — extract Crawl-delay via Python's stdlib RobotFileParser
    result.crawl_delay = _extract_crawl_delay(raw_content, robots_url)

    # Step 3 — extract Sitemap: directives (may be multiple; use the first)
    directive_sitemaps = _extract_sitemap_directives(raw_content)
    if directive_sitemaps:
        result.sitemap_url = directive_sitemaps[0]
        result.sitemap_url_source = "directive"
        logger.debug(
            "Sitemap URL from directive for %s: %s", origin, result.sitemap_url
        )
    else:
        # Step 4 — fallback probe: /sitemap.xml then /sitemap_index.xml
        for probe_path in ("/sitemap.xml", "/sitemap_index.xml"):
            probe_url = urljoin(origin, probe_path)
            if _url_returns_xml(probe_url):
                result.sitemap_url = probe_url
                result.sitemap_url_source = "fallback_probe"
                logger.debug(
                    "Sitemap URL from fallback probe for %s: %s",
                    origin,
                    probe_url,
                )
                break

    # Step 5 — parse sitemap and extract grant-signal URLs
    if result.sitemap_url:
        result.sitemap_grant_urls = _parse_sitemap_for_grant_urls(result.sitemap_url)

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _fetch_text(url: str) -> str | None:
    """
    GET *url* and return the response body as a decoded string, or None on
    any error (connection, timeout, non-2xx status).
    """
    headers = {"User-Agent": _PROBE_UA}
    try:
        resp = requests.get(url, headers=headers, timeout=_TIMEOUT_S, allow_redirects=True)
        if resp.status_code == 200:
            return resp.text
        logger.debug("Non-200 (%d) fetching %s", resp.status_code, url)
    except requests.RequestException as exc:
        logger.debug("Error fetching %s: %s", url, exc)
    return None


def _url_returns_xml(url: str) -> bool:
    """
    Return True if *url* responds 200 with an XML-like Content-Type.
    Used to verify fallback sitemap probes.
    """
    headers = {"User-Agent": _PROBE_UA}
    try:
        resp = requests.get(
            url, headers=headers, timeout=_TIMEOUT_S, allow_redirects=True, stream=True
        )
        if resp.status_code != 200:
            return False
        ct = resp.headers.get("Content-Type", "").lower()
        return "xml" in ct
    except requests.RequestException:
        return False


def _extract_sitemap_directives(robots_content: str) -> list[str]:
    """
    Scan *robots_content* line by line for ``Sitemap:`` directives.
    Returns a list of all declared sitemap URLs (preserves declaration order).
    Spec ref: §2.1 Sitemap.xml check — "already-parsed robots.txt is checked
    for a Sitemap: directive … this directive is authoritative".
    """
    sitemaps: list[str] = []
    for line in robots_content.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("sitemap:"):
            url = stripped.split(":", 1)[1].strip()
            if url.startswith("http"):
                sitemaps.append(url)
    return sitemaps


def _extract_crawl_delay(robots_content: str, robots_url: str) -> float | None:
    """
    Use Python's ``urllib.robotparser.RobotFileParser`` to extract the
    ``Crawl-delay`` value for the ``*`` (any) user-agent group.

    Returns the delay as a float, or None if no directive is present.
    """
    parser = RobotFileParser()
    parser.set_url(robots_url)
    # RobotFileParser.parse() accepts an iterable of lines.
    parser.parse(robots_content.splitlines())
    delay = parser.crawl_delay("*")
    if delay is not None:
        try:
            return float(delay)
        except (TypeError, ValueError):
            pass
    return None


def _parse_sitemap_for_grant_urls(sitemap_url: str) -> list[str]:
    """
    Fetch *sitemap_url*, parse the XML, and return every ``<loc>`` URL whose
    path contains at least one segment from ``settings.SITEMAP_GRANT_SIGNALS``.

    Handles both standard sitemaps (``<urlset>``) and sitemap index files
    (``<sitemapindex>``).  For index files, each child sitemap is fetched and
    parsed one level deep (no recursive expansion to avoid unbounded fetches).

    Spec ref: §2.1 Sitemap.xml check.
    """
    # Import settings here (not at module level) to avoid circular imports
    # and to allow this module to be imported standalone in tests.
    try:
        from grantglobe_crawler import settings
        grant_signals: list[str] = settings.SITEMAP_GRANT_SIGNALS
    except Exception:
        grant_signals = [
            "grant", "call", "fund", "award", "fellow", "scholarship",
            "opportunity", "programme", "program", "bursary", "rfp", "rfa",
        ]

    raw_xml = _fetch_text(sitemap_url)
    if not raw_xml:
        return []

    grant_urls: list[str] = []
    _extract_grant_locs_from_xml(raw_xml, grant_signals, grant_urls, depth=0)
    return grant_urls


def _extract_grant_locs_from_xml(
    xml_content: str,
    grant_signals: list[str],
    accumulator: list[str],
    depth: int,
) -> None:
    """
    Parse sitemap XML and append grant-signal URLs to *accumulator*.

    If the root element is ``<sitemapindex>`` (and depth == 0), each child
    ``<sitemap>/<loc>`` is fetched and processed one level deep.
    """
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as exc:
        logger.debug("XML parse error in sitemap: %s", exc)
        return

    # Normalise: strip namespace from tag for comparison.
    def _local(tag: str) -> str:
        return tag.split("}", 1)[-1] if "}" in tag else tag

    root_local = _local(root.tag)

    if root_local == "sitemapindex" and depth == 0:
        # Sitemap index: recurse into each child sitemap (one level only).
        for sitemap_elem in root.iter():
            if _local(sitemap_elem.tag) == "loc":
                child_url = (sitemap_elem.text or "").strip()
                if child_url:
                    child_xml = _fetch_text(child_url)
                    if child_xml:
                        _extract_grant_locs_from_xml(
                            child_xml, grant_signals, accumulator, depth=1
                        )
        return

    # Standard sitemap: iterate all <loc> elements.
    for elem in root.iter():
        if _local(elem.tag) == "loc":
            url = (elem.text or "").strip()
            if url and _url_has_grant_signal(url, grant_signals):
                accumulator.append(url)


def _url_has_grant_signal(url: str, signals: list[str]) -> bool:
    """
    Return True if any path segment of *url*, when split on ``/``, ``-``,
    and ``_``, matches a grant signal keyword.

    The same token-splitting logic as the Link Intelligence Filter is applied
    here so that URLs like ``/grant_opportunities/`` correctly match.
    Spec ref: §2.1 + §2.2 Link Intelligence Filter path splitting.
    """
    path = urlparse(url).path.lower()
    tokens = re.split(r"[/_-]", path)
    return any(token in signals for token in tokens if token)
