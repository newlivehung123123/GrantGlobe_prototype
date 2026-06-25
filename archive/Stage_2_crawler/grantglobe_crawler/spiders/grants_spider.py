"""
GrantGlobe main spider — spec §2.2 Core crawl loop.

Name: "grants"

Crawl flow
----------
1. ``start_requests()`` reads the 582-row seed CSV, loads per-domain
   ``crawl_manifest.json`` files, and yields one seed Request per live
   domain (Profile B domains use scrapy-playwright).

2. ``parse()`` — the default callback — handles every fetched page:
   - 429 / 403 / 503 responses are caught here (spider declares
     ``handle_httpstatus_list`` so Scrapy passes them through).
   - CAPTCHA presence is detected via ``CAPTCHA_DETECTION_STRINGS``.
   - Links are extracted, canonicalised, passed through
     ``_passes_link_filter()``, depth-checked, and yielded as new Requests.
   - PDF links are yielded with ``meta["is_pdf"] = True``.
   - JSON-LD ``<script>`` blocks are extracted and written to disk.
   - A ``GrantItem`` is yielded for every successfully fetched resource.

3. ``spider_closed()`` writes per-domain manifest updates (crawl_status,
   pages_crawled, last_crawl_timestamp) and emits a Critical alert if the
   domain-failure rate exceeds ``ALERT_THRESHOLD_DOMAIN_FAILURE_RATE``.

Spec ref: §2.2 Core crawl loop, §2.5 Layers 2–7, §2.8 Alerting.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import shutil
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import scrapy
from scrapy import signals
from scrapy.http import Request, Response

from grantglobe_crawler.items import GrantItem
from grantglobe_crawler.pagination.pagination_handler import PaginationHandler
from grantglobe_crawler.qa.qa_reporter import QAReporter
from grantglobe_crawler.utils.link_filter import passes_link_filter
from grantglobe_crawler.utils.url_canonicaliser import canonicalise, url_to_hash

# _is_pdf_href: use urlparse to strip query strings and fragments before
# checking the extension, so links like /report.pdf?download=1 are detected.
def _is_pdf_href(href: str) -> bool:
    """Return True if *href* points to a PDF, ignoring query strings and fragments."""
    from urllib.parse import urlparse as _urlparse
    return _urlparse(href).path.lower().endswith(".pdf")

# scrapy-playwright's PageMethod is imported lazily below so that the module
# can be imported (e.g. for tests) even when playwright is not installed.
try:
    from scrapy_playwright.page import PageMethod as _PageMethod
except ImportError:  # pragma: no cover — playwright not installed in test env
    _PageMethod = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_PREFLIGHT_UA = "GrantGlobe-Crawler/1.0"

# ---------------------------------------------------------------------------
# Listing-page detector — URLs that are clearly index/pagination pages and
# should never be sent to Stage 3 for grant extraction.
# The spider still crawls these pages and follows their links; it just does
# not yield a GrantItem so the LLM is never asked to extract from them.
# ---------------------------------------------------------------------------
_LISTING_URL_RE: list[re.Pattern] = [
    re.compile(r'[?&]page=[2-9]'),       # paginated listing page 2+
    re.compile(r'[?&]page=1\d'),         # paginated listing page 10+
    re.compile(r'[?&]pg=[2-9]'),
    re.compile(r'[?&]pg=1\d'),
    re.compile(r'[?&]projects[&$]'),     # faceted project listing (e.g. OII)
    re.compile(r'tx_solr'),              # TYPO3/Solr faceted search (already in link filter)
]


def _is_listing_page_url(url: str) -> bool:
    """Return True if *url* is a listing/pagination page rather than a specific grant page."""
    return any(p.search(url) for p in _LISTING_URL_RE)


class GrantsSpider(scrapy.Spider):
    """GrantGlobe Stage 2 main spider."""

    name = "grants"

    # Scrapy normally drops non-2xx responses before calling the callback.
    # We declare these codes so 429, 403, and 503 arrive in parse() where
    # we can handle each case explicitly.
    # spec §2.5 Layer 7 — retry / backoff table.
    handle_httpstatus_list = [429, 403, 503]

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Per-URL deduplication (supplements Scrapy's built-in fingerprinting).
        self.seen_urls: set[str] = set()
        # Per-domain manifests; loaded during start_requests(), updated in
        # parse() error handlers, flushed to disk in spider_closed().
        self._domain_manifests: dict[str, dict] = {}
        # Pages successfully fetched per domain (for manifest final stats).
        self._domain_pages_crawled: dict[str, int] = defaultdict(int)
        # Number of fully-failed requests per domain (HTTP 403/503 with no
        # retries remaining, plus connection failures).
        self._domain_failed_requests: dict[str, int] = defaultdict(int)
        # PDF extraction counters populated by PDFExtractionPipeline (Phase C).
        self._domain_pdfs_found: dict[str, int] = defaultdict(int)
        self._domain_pdf_failures: dict[str, int] = defaultdict(int)
        # Phase D counters populated during parse() and by ChangeDetectionPipeline.
        self._domain_changed_pages: dict[str, int] = defaultdict(int)
        self._domain_grant_relevant_pages: dict[str, int] = defaultdict(int)
        # Total domains that were enqueued as seed requests.
        self._domains_total: int = 0
        self._crawl_start: datetime | None = None

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        crawler.signals.connect(spider.spider_closed, signal=signals.spider_closed)
        # Instantiate once per spider session — not per-request.
        spider._pagination_handler = PaginationHandler(crawler.settings)
        return spider

    # ------------------------------------------------------------------
    # Seed request generation — spec §2.2 Start requests
    # ------------------------------------------------------------------

    async def start(self):
        """
        Scrapy 2.9+ entry point called by StartSpiderMiddleware.

        The base Spider.start() iterates self.start_urls and does NOT call
        start_requests() in Scrapy 2.12+.  This override restores the
        expected behaviour by delegating to start_requests() so that the
        CSV-based seed logic runs correctly.
        """
        for req in self.start_requests():
            yield req

    def start_requests(self):
        """
        Read the seed CSV, load per-domain manifests, and yield one initial
        Request per live (non-dead) domain.

        Profile A / C → standard Scrapy Request.
        Profile B     → scrapy-playwright Request with networkidle +
                        a single page-bottom scroll (to trigger lazy-load).
        """
        self._crawl_start = datetime.now(timezone.utc)
        csv_path = self.settings.get("SOURCE_LIST_CSV", "")
        crawl_state_dir = Path(
            self.settings.get("CRAWL_STATE_DIR", self.settings.get("RAW_CACHE_DIR", "raw_cache"))
        )
        max_depth = self.settings.getint("MAX_CRAWL_DEPTH", 3)
        global_delay = self.settings.getfloat("DOWNLOAD_DELAY", 4.0)

        if not csv_path or not Path(csv_path).exists():
            logger.error("SOURCE_LIST_CSV not found: %s", csv_path)
            return

        rows = _load_csv(csv_path)
        logger.info("Loaded %d rows from %s", len(rows), csv_path)

        enqueued = 0
        for row in rows:
            domain = (row.get("domain") or "").strip()
            seed_url = (row.get("grants_url") or "").strip()
            if not domain or not seed_url:
                logger.debug("Skipping row with empty domain or URL: %s", row)
                continue

            manifest = _load_manifest(crawl_state_dir, domain)
            self._domain_manifests[domain] = manifest

            # spec §2.2 init: "only enqueue domains where
            # manifest['crawl_status'] is not 'dead_domain_candidate'"
            if manifest.get("dead_domain_candidate", False):
                logger.info("Skipping dead domain candidate: %s", domain)
                continue
            if manifest.get("crawl_status") == "dead_domain_candidate":
                logger.info("Skipping dead domain (crawl_status): %s", domain)
                continue

            profile = manifest.get("crawl_profile", "A")
            domain_max_depth = min(
                manifest.get("max_depth", max_depth), max_depth
            )
            # spec §2.2 init: "use DOWNLOAD_DELAY as floor, raise if manifest
            # value is higher"
            rate_floor = max(
                global_delay,
                float(manifest.get("rate_limit_floor_seconds", global_delay)),
            )

            # ── RSS per-cycle feed polling ─────────────────────────────────
            # spec §2.1 — compare current GUIDs against previous cycle; skip
            # the full depth-crawl when the feed has not changed.
            if manifest.get("rss_feed_url"):
                try:
                    import feedparser          # lazy — may not be installed in tests
                    import requests as _req

                    feed_url = manifest["rss_feed_url"]
                    resp = _req.get(
                        feed_url, timeout=15, headers={"User-Agent": _PREFLIGHT_UA}
                    )
                    feed = feedparser.parse(resp.text)

                    current_guids: set[str] = set()
                    for entry in feed.entries:
                        guid = getattr(entry, "id", None) or getattr(entry, "link", None)
                        if guid:
                            current_guids.add(guid)

                    prev_guids: set[str] = set(manifest.get("rss_guid_set", []))
                    manifest["rss_guid_set"] = list(current_guids)

                    if current_guids and current_guids == prev_guids:
                        manifest["crawl_skip_reason"] = "rss_no_change"
                        _write_manifest_atomic(crawl_state_dir, domain, manifest)
                        logger.info(
                            "Skipping depth-crawl for %s — RSS GUID set unchanged",
                            domain,
                        )
                        continue  # skip to next domain in the for loop

                    new_guids = current_guids - prev_guids
                    for entry in feed.entries:
                        link = getattr(entry, "link", None)
                        guid = getattr(entry, "id", None) or link
                        if (
                            guid in new_guids
                            and link
                            and link.startswith(("http://", "https://"))
                        ):
                            canonical_link = canonicalise(link)
                            if canonical_link not in self.seen_urls:
                                self.seen_urls.add(canonical_link)
                                yield Request(
                                    url=link,
                                    callback=self.parse,
                                    errback=self.handle_error,
                                    meta={
                                        "domain": domain,
                                        "profile": profile,
                                        "depth": 0,
                                        "source_url": feed_url,
                                        "source": "rss",
                                        "domain_max_depth": domain_max_depth,
                                        "rate_limit_floor_seconds": rate_floor,
                                        "is_first_request": False,
                                        "is_pdf": _is_pdf_href(link),
                                        "retry_count": 0,
                                    },
                                )
                except Exception as exc:
                    logger.warning(
                        "RSS poll failed for %s (%s) — proceeding with full crawl",
                        domain,
                        exc,
                    )

            meta: dict = {
                "domain": domain,
                "profile": profile,
                "depth": 0,
                "source_url": None,
                "domain_max_depth": domain_max_depth,
                "rate_limit_floor_seconds": rate_floor,
                "is_first_request": True,
                "retry_count": 0,
                # SecFetchHeadersMiddleware uses is_first_request to emit
                # Sec-Fetch-Site: none on the cold-navigation seed request.
            }

            if profile == "B":
                if _PageMethod is None:
                    logger.warning(
                        "scrapy-playwright not installed; falling back to "
                        "standard request for Profile B domain %s",
                        domain,
                    )
                else:
                    # spec §2.2 start requests: "yield a scrapy-playwright
                    # Request … wait_until='networkidle', timeout 20 seconds.
                    # playwright_page_methods to scroll once to bottom."
                    meta["playwright"] = True
                    meta["playwright_include_page"] = False
                    meta["playwright_page_methods"] = [
                        _PageMethod(
                            "evaluate",
                            "window.scrollTo(0, document.body.scrollHeight)",
                        ),
                        _PageMethod("wait_for_timeout", 1_000),
                    ]
                    meta["playwright_default_navigation_timeout"] = (
                        self.settings.getint(
                            "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT", 20_000
                        )
                    )

            # ── Cookie injection for Profile B ─────────────────────────────
            # Restore previously stored Playwright session cookies so the
            # browser context skips consent dialogs on known domains.
            # COOKIE_ENCRYPTION_KEY is read exclusively from os.environ.
            if profile == "B" and manifest.get("has_stored_cookies"):
                try:
                    import os as _os
                    from grantglobe_crawler.utils.cookie_store import CookieStore
                    _enc_key = _os.environ.get("COOKIE_ENCRYPTION_KEY", "")
                    if _enc_key.strip():
                        _cookie_dir = (
                            Path(self.settings.get("RAW_CACHE_DIR", "raw_cache"))
                            / "cookie_store"
                        )
                        _store = CookieStore(_cookie_dir, _enc_key)
                        stored_cookies = _store.load(domain)
                        if stored_cookies:
                            meta.setdefault("playwright_context_kwargs", {})
                            meta["playwright_context_kwargs"]["storage_state"] = {
                                "cookies": stored_cookies,
                                "origins": [],
                            }
                            logger.debug(
                                "Injected %d stored cookies for %s",
                                len(stored_cookies), domain,
                            )
                except Exception as exc:
                    logger.warning(
                        "Cookie injection failed for %s: %s — proceeding without "
                        "stored session", domain, exc,
                    )

            yield Request(
                url=seed_url,
                callback=self.parse,
                errback=self.handle_error,
                meta=meta,
                dont_filter=False,
            )
            enqueued += 1

            # ── Sitemap URL seeding ────────────────────────────────────────
            # spec §2.1 — grant-relevant URLs extracted from the domain's
            # sitemap during pre-flight are seeded directly at depth=1.
            # Sitemap requests never use Playwright regardless of profile.
            sitemap_urls: list[str] = manifest.get("sitemap_grant_urls", [])
            if len(sitemap_urls) > 50:
                logger.warning(
                    "Sitemap for %s has %d grant URLs — capping at 50",
                    domain,
                    len(sitemap_urls),
                )
                sitemap_urls = sitemap_urls[:50]

            sitemap_source = manifest.get("sitemap_url", "sitemap")
            for smap_url in sitemap_urls:
                if not smap_url.startswith(("http://", "https://")):
                    continue
                canonical_smap = canonicalise(smap_url)
                if canonical_smap in self.seen_urls:
                    continue
                is_pdf = _is_pdf_href(smap_url)
                if not is_pdf and not self._passes_link_filter(canonical_smap, depth=1):
                    continue
                self.seen_urls.add(canonical_smap)
                yield Request(
                    url=smap_url,
                    callback=self.parse,
                    errback=self.handle_error,
                    meta={
                        "domain": domain,
                        "profile": profile,
                        "depth": 1,
                        "source_url": sitemap_source,
                        "source": "sitemap",
                        "domain_max_depth": domain_max_depth,
                        "rate_limit_floor_seconds": rate_floor,
                        "is_first_request": False,
                        "is_pdf": is_pdf,
                        "retry_count": 0,
                    },
                    dont_filter=False,
                )

        self._domains_total = enqueued
        logger.info("Enqueued %d seed requests (skipped dead domains)", enqueued)

    # ------------------------------------------------------------------
    # Link Intelligence Filter — spec §2.2 Tier 1 + Tier 2
    # ------------------------------------------------------------------

    def _passes_link_filter(self, url: str, depth: int = 1) -> bool:
        """
        Thin wrapper around the module-level ``passes_link_filter`` from
        ``utils.link_filter``.  The logic lives there so tests can import
        it without instantiating a spider.

        spec §2.2 Link Intelligence Filter.
        """
        return passes_link_filter(url, depth=depth)

    # ------------------------------------------------------------------
    # Parse — spec §2.2 Parse method
    # ------------------------------------------------------------------

    def parse(self, response: Response):
        """
        Default callback — handles HTML pages, PDF responses, and explicit
        error-status codes (429, 403, 503) declared in handle_httpstatus_list.

        Yields
        ------
        Request   — for each filtered outbound link or PDF.
        GrantItem — for the current page / resource.
        """
        domain: str = response.meta.get("domain", "")
        depth: int = response.meta.get("depth", 0)
        profile: str = response.meta.get("profile", "A")
        source_url: str | None = response.meta.get("source_url")
        domain_max_depth: int = response.meta.get(
            "domain_max_depth", self.settings.getint("MAX_CRAWL_DEPTH", 3)
        )

        # ── Error-status handling ──────────────────────────────────────────
        if response.status == 429:
            yield from self._handle_429(response, domain)
            return

        if response.status in (403, 503):
            self._handle_block(response, domain)
            return

        # ── CAPTCHA detection ─────────────────────────────────────────────
        # spec §2.5 Layer 5 — CAPTCHA detection and escalation.
        body_text = response.text
        for captcha_str in self.settings.getlist("CAPTCHA_DETECTION_STRINGS", []):
            if captcha_str.lower() in body_text.lower():
                logger.warning("CAPTCHA detected at %s", response.url)
                self._record_captcha(response, domain)
                return

        # ── Canonical URL + hash ───────────────────────────────────────────
        canonical = canonicalise(response.url)
        url_hash = url_to_hash(response.url)

        # ── JSON-LD extraction ─────────────────────────────────────────────
        # spec §2.2 step (4): extract <script type="application/ld+json">
        jsonld_data, has_structured_data = _extract_jsonld(response, domain, url_hash, self)

        # ── Build GrantItem ────────────────────────────────────────────────
        ct_header: bytes = response.headers.get("Content-Type", b"")
        if isinstance(ct_header, list):
            ct_header = ct_header[0] if ct_header else b""
        content_type_str = ct_header.decode("utf-8", errors="replace").split(";")[0].strip()

        item = GrantItem(
            url=response.url,
            canonical_url=canonical,
            url_hash=url_hash,
            domain=domain,
            profile=profile,
            depth=depth,
            source_url=source_url,
            html_content=response.body,
            headers=dict(response.headers),
            crawl_timestamp=datetime.now(timezone.utc).isoformat(),
            is_pdf=bool(response.meta.get("is_pdf")),
            has_structured_data=has_structured_data,
            jsonld_data=jsonld_data,
            http_status=response.status,
            content_type=content_type_str,
        )

        # spec §2.7: a page is grant-relevant when its URL passes the link
        # intelligence filter.  PDFs always count as grant-relevant because
        # they bypass the filter (they are explicitly followed links).
        if response.meta.get("is_pdf") or self._passes_link_filter(canonical, depth=depth):
            self._domain_grant_relevant_pages[domain] += 1

        # Do not send paginated listing/index pages to Stage 3 for extraction.
        # These pages contain multiple grants listed without individual URLs,
        # causing the LLM to extract grant records that link back to the listing
        # page rather than to the specific grant page.
        # We still crawl them (to follow links to specific grant pages) but we
        # do not yield the item so the LLM never sees them as extraction targets.
        if not _is_listing_page_url(response.url):
            yield item

        self._domain_pages_crawled[domain] += 1

        # ── PDF responses: no link extraction ─────────────────────────────
        if response.meta.get("is_pdf"):
            return

        # ── Link extraction ────────────────────────────────────────────────
        if depth >= domain_max_depth:
            logger.debug("Depth ceiling reached (%d) at %s", depth, response.url)
            return

        for href in response.css("a::attr(href)").getall():
            if not href or href.startswith(("mailto:", "tel:", "javascript:")):
                continue

            abs_url = urljoin(response.url, href.strip())
            if not abs_url.startswith(("http://", "https://")):
                continue

            canonical_link = canonicalise(abs_url)

            # spec §2.2: "Check for PDF links … yield a separate Request
            # with meta['is_pdf'] = True.  Do not apply link filter to PDFs."
            # Use _is_pdf_href() to strip query strings before the extension
            # check (rstrip("?#") alone misses links like /report.pdf?download=1).
            if _is_pdf_href(href):
                if canonical_link not in self.seen_urls:
                    self.seen_urls.add(canonical_link)
                    yield self._build_request(
                        url=abs_url,
                        response=response,
                        depth=depth + 1,
                        domain=domain,
                        profile=profile,
                        domain_max_depth=domain_max_depth,
                        is_pdf=True,
                    )
                continue

            # spec §2.2 Tier 1 + Tier 2: run through link filter.
            if not self._passes_link_filter(canonical_link, depth=depth + 1):
                continue

            if canonical_link in self.seen_urls:
                continue
            self.seen_urls.add(canonical_link)

            yield self._build_request(
                url=abs_url,
                response=response,
                depth=depth + 1,
                domain=domain,
                profile=profile,
                domain_max_depth=domain_max_depth,
            )

        # ── Pagination — spec §2.3 ─────────────────────────────────────────
        yield from self._handle_pagination(response, domain, profile, depth, domain_max_depth)

    # ------------------------------------------------------------------
    # Pagination wiring — spec §2.3 (five types)
    # ------------------------------------------------------------------

    def _handle_pagination(
        self,
        response: Response,
        domain: str,
        profile: str,
        depth: int,
        domain_max_depth: int,
    ):
        """
        Detect and yield pagination requests for all five types described in
        spec §2.3.

        Called at the end of ``parse()`` after the link-extraction loop so
        that standard link crawling happens before pagination triggers.

        Spec ref: §2.3 Pagination handling.
        """
        manifest = self._domain_manifests.get(domain, {})
        rate_floor: float = response.meta.get("rate_limit_floor_seconds", 4.0)

        def _pagination_meta(**extra) -> dict:
            return {
                "domain": domain,
                "profile": profile,
                "depth": depth,  # pagination never increments depth
                "source_url": response.url,
                "domain_max_depth": domain_max_depth,
                "rate_limit_floor_seconds": rate_floor,
                "is_first_request": False,
                "is_pdf": False,
                "retry_count": 0,
                **extra,
            }

        # ── Type 1: URL-based pagination ──────────────────────────────────
        # spec §2.3 Type 1: pagination does not increment depth — navigating
        # to page 2 of a listing is not a depth increase.
        if depth < domain_max_depth:
            next_url = self._pagination_handler.extract_next_url(response)
            if next_url and next_url not in self.seen_urls:
                self.seen_urls.add(next_url)
                yield Request(
                    url=next_url,
                    callback=self.parse,
                    errback=self.handle_error,
                    meta=_pagination_meta(pagination_type="url_next"),
                    dont_filter=False,
                )

        # ── Types 2–5 only apply to Profile B (Playwright-rendered pages) ─
        if profile != "B":
            return

        # ── Type 2: Load more button ──────────────────────────────────────
        load_more_count: int = response.meta.get("load_more_count", 0)
        max_clicks: int = self.settings.getint("PAGINATION_LOAD_MORE_MAX_CLICKS", 20)
        if load_more_count < max_clicks:
            page_methods = self._pagination_handler.get_load_more_page_methods(response)
            if page_methods:
                yield Request(
                    url=response.url,
                    callback=self.parse,
                    errback=self.handle_error,
                    meta=_pagination_meta(
                        playwright=True,
                        playwright_page_methods=page_methods,
                        pagination_type="load_more",
                        load_more_count=load_more_count + 1,
                    ),
                    dont_filter=True,
                )

        # ── Type 3: Infinite scroll ───────────────────────────────────────
        tab_filters: list = manifest.get("tab_filter", [])
        if "infinite_scroll" in tab_filters:
            scroll_count: int = response.meta.get("scroll_count", 0)
            max_scrolls: int = self.settings.getint(
                "PAGINATION_INFINITE_SCROLL_MAX_ITERATIONS", 30
            )
            if scroll_count < max_scrolls:
                page_methods = self._pagination_handler.get_infinite_scroll_page_methods()
                yield Request(
                    url=response.url,
                    callback=self.parse,
                    errback=self.handle_error,
                    meta=_pagination_meta(
                        playwright=True,
                        playwright_page_methods=page_methods,
                        pagination_type="infinite_scroll",
                        scroll_count=scroll_count + 1,
                    ),
                    dont_filter=True,
                )

        # ── Type 4: Tab / filter navigation ──────────────────────────────
        for tab_selector in tab_filters:
            if tab_selector == "infinite_scroll" or not tab_selector:
                continue
            tab_done_key = f"tab_done_{tab_selector}"
            if response.meta.get(tab_done_key):
                continue
            page_methods = self._pagination_handler.get_tab_page_methods(tab_selector)
            yield Request(
                url=response.url,
                callback=self.parse,
                errback=self.handle_error,
                meta=_pagination_meta(
                    playwright=True,
                    playwright_page_methods=page_methods,
                    pagination_type="tab_filter",
                    **{tab_done_key: True},
                ),
                dont_filter=True,
            )

        # ── Type 5: XHR / API interception ───────────────────────────────
        api_pattern: str | None = manifest.get("api_pattern")
        if api_pattern and not response.meta.get("xhr_intercept_done"):
            page_methods = self._pagination_handler.get_xhr_intercept_page_methods(
                api_pattern
            )
            yield Request(
                url=response.url,
                callback=self.parse,
                errback=self.handle_error,
                meta=_pagination_meta(
                    playwright=True,
                    playwright_page_methods=page_methods,
                    pagination_type="xhr_intercept",
                    xhr_intercept_done=True,
                ),
                dont_filter=True,
            )

    # ------------------------------------------------------------------
    # Request builder helper
    # ------------------------------------------------------------------

    def _build_request(
        self,
        *,
        url: str,
        response: Response,
        depth: int,
        domain: str,
        profile: str,
        domain_max_depth: int,
        is_pdf: bool = False,
    ) -> Request:
        """
        Construct a child Request with the correct meta dict, Profile B
        Playwright settings, and Referer header.
        """
        meta: dict = {
            "domain": domain,
            "profile": profile,
            "depth": depth,
            "source_url": response.url,
            "domain_max_depth": domain_max_depth,
            "rate_limit_floor_seconds": response.meta.get("rate_limit_floor_seconds", 4.0),
            "is_first_request": False,
            "is_pdf": is_pdf,
            "retry_count": 0,
        }

        if profile == "B" and not is_pdf and _PageMethod is not None:
            meta["playwright"] = True
            meta["playwright_include_page"] = False
            meta["playwright_page_methods"] = [
                _PageMethod(
                    "evaluate",
                    "window.scrollTo(0, document.body.scrollHeight)",
                ),
                _PageMethod("wait_for_timeout", 500),
            ]
            meta["playwright_default_navigation_timeout"] = self.settings.getint(
                "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT", 20_000
            )

        return Request(
            url=url,
            callback=self.parse,
            errback=self.handle_error,
            meta=meta,
            headers={"Referer": response.url},
            dont_filter=False,
        )

    # ------------------------------------------------------------------
    # Error handling — spec §2.5 Layer 7
    # ------------------------------------------------------------------

    def _handle_429(self, response: Response, domain: str):
        """
        HTTP 429 Too Many Requests.

        Back off for ``RETRY_429_BACKOFF_BASE ** retry_count`` seconds.
        If the Retry-After header is present and numeric, use that value
        instead.

        spec §2.5 Layer 7 — "429: wait 60, 120, 240 seconds (doubles)".
        """
        retry_count: int = response.meta.get("retry_count", 0)
        max_retries: int = self.settings.getint("RETRY_TIMES", 3)

        retry_after_header = response.headers.get("Retry-After", b"").decode("utf-8", errors="replace").strip()
        if retry_after_header and retry_after_header.isdigit():
            backoff = float(retry_after_header)
        else:
            backoff = (
                self.settings.getfloat("RETRY_429_BACKOFF_BASE", 60.0)
                ** (retry_count + 1)
            )

        logger.warning(
            "HTTP 429 from %s (retry %d/%d) — backoff %.0f s",
            domain,
            retry_count,
            max_retries,
            backoff,
        )

        if retry_count >= max_retries:
            logger.error(
                "Giving up on %s after %d retries (HTTP 429)", response.url, max_retries
            )
            self._domain_failed_requests[domain] += 1
            return

        new_meta = dict(response.meta)
        new_meta["retry_count"] = retry_count + 1
        new_meta["dont_merge_cookies"] = False
        # Note: BehaviouralDelayMiddleware (Phase B) will read
        # 'rate_limit_floor_seconds' from meta to enforce the backoff
        # interval.  For Phase A, we carry the value in meta for audit/logging.
        new_meta["rate_limit_floor_seconds"] = max(
            response.meta.get("rate_limit_floor_seconds", 4.0), backoff
        )

        yield response.request.replace(meta=new_meta, dont_filter=True)

    def _handle_block(self, response: Response, domain: str) -> None:
        """
        HTTP 403 Forbidden or 503 Service Unavailable.

        Do not retry automatically.  Record a ``captcha_history`` entry in
        the manifest and flag for manual review.

        spec §2.5 Layer 7 — "403: retry once … flag for manual review if
        second 403"; "503: retry once … flag if second 503".
        """
        logger.warning(
            "HTTP %d from %s — flagging for manual review (no automatic retry)",
            response.status,
            domain,
        )
        self._record_captcha(response, domain)
        self._domain_failed_requests[domain] += 1

    def _record_captcha(self, response: Response, domain: str) -> None:
        """
        Append a CAPTCHA / block event to the domain's manifest
        ``captcha_history`` list.  Written to disk in spider_closed().

        spec §2.5 Layer 5 — CAPTCHA detection.
        """
        manifest = self._domain_manifests.setdefault(domain, {})
        if "captcha_history" not in manifest:
            manifest["captcha_history"] = []
        manifest["captcha_history"].append(
            {
                "status": response.status,
                "url": response.url,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    def handle_error(self, failure) -> None:
        """
        Errback for connection errors and timeouts.

        Connection timeouts are retried via RETRY_HTTP_CODES configured in
        settings.py; this errback is the last resort when all retries are
        exhausted.  Log and increment the domain failure counter.
        """
        request = failure.request
        domain: str = request.meta.get("domain", "")
        logger.error(
            "Request failed for %s (%s): %s",
            request.url,
            domain,
            failure.getErrorMessage(),
        )
        self._domain_failed_requests[domain] += 1

    # ------------------------------------------------------------------
    # Spider closed — spec §2.8 Alerting + Phase A build sequence
    # ------------------------------------------------------------------

    def spider_closed(self, spider, reason: str) -> None:
        """
        Write final per-domain manifest updates and emit a Critical alert
        if the domain-failure rate exceeds the configured threshold.

        spec §2.8 Alerting table (Critical row):
            "Condition: > 20% of domains in a cycle have all retries
            exhausted.  Severity: Critical."

        Also referred to in Phase A build sequence:
            "include the Critical-severity alert (> 20% domain failures)
            from the outset — this is a 10-line addition to the spider's
            spider_closed handler."
        """
        crawl_end = datetime.now(timezone.utc)
        crawl_state_dir = Path(
            self.settings.get("CRAWL_STATE_DIR", self.settings.get("RAW_CACHE_DIR", "raw_cache"))
        )

        for domain, manifest in self._domain_manifests.items():
            if manifest.get("dead_domain_candidate", False):
                # Domain was skipped in start_requests(); it was never enqueued
                # this cycle so pages and failed counts are both 0.  Preserve
                # the existing dead-domain status and failure history; only
                # refresh the timestamp so the manifest reflects it was seen.
                manifest["last_crawl_timestamp"] = crawl_end.isoformat()
                _write_manifest_atomic(crawl_state_dir, domain, manifest)
                continue

            pages = self._domain_pages_crawled.get(domain, 0)
            failed = self._domain_failed_requests.get(domain, 0)

            manifest.update(
                {
                    "last_crawl_timestamp": crawl_end.isoformat(),
                    "pages_crawled": pages,
                    "crawl_status": "failed" if pages == 0 and failed > 0 else "complete",
                }
            )
            _write_manifest_atomic(crawl_state_dir, domain, manifest)

        # ── Dead domain sunset — spec §2.6 ────────────────────────────────
        # Track consecutive failures and flag dead-domain candidates after
        # exceeding DEAD_DOMAIN_FAILED_CYCLE_THRESHOLD (default 3).
        sunset_threshold = self.settings.getint("DEAD_DOMAIN_FAILED_CYCLE_THRESHOLD", 3)
        for domain, manifest in self._domain_manifests.items():
            # Already-escalated dead candidates were skipped in start_requests()
            # and have no meaningful pages/failures this cycle.  Preserve their
            # failure history and status unchanged.
            if manifest.get("dead_domain_candidate", False):
                continue

            if manifest.get("crawl_status") == "failed":
                manifest["consecutive_failed_cycles"] = (
                    manifest.get("consecutive_failed_cycles", 0) + 1
                )
                manifest["consecutive_unchanged_cycles"] = 0
            else:
                manifest["consecutive_failed_cycles"] = 0

            if (
                manifest["consecutive_failed_cycles"] >= sunset_threshold
                and not manifest.get("dead_domain_candidate", False)
            ):
                manifest["dead_domain_candidate"] = True
                manifest["crawl_status"] = "dead_domain_candidate"
                _append_manual_review(crawl_state_dir, domain, manifest, crawl_end)
                logger.warning(
                    "Dead domain candidate: %s (%d consecutive failed cycles)",
                    domain,
                    manifest["consecutive_failed_cycles"],
                )

            _write_manifest_atomic(crawl_state_dir, domain, manifest)

        # ── Incremental scheduling feedback loop — spec §2.6 ─────────────
        # Downgrade crawl_frequency for stale domains; restore weekly when
        # content change is detected (and flag for triggered re-crawl).
        biweekly_t = self.settings.getint("INCREMENTAL_DOWNGRADE_BIWEEKLY_THRESHOLD", 3)
        monthly_t = self.settings.getint("INCREMENTAL_DOWNGRADE_MONTHLY_THRESHOLD", 6)
        for domain, manifest in self._domain_manifests.items():
            if manifest.get("crawl_status") != "complete":
                continue
            if manifest.get("dead_domain_candidate", False):
                continue
            if manifest.get("downgrade_protected", False):
                continue

            changed_pages = self._domain_changed_pages.get(domain, 0)
            if changed_pages > 0:
                was_downgraded = manifest.get("crawl_frequency") in ("biweekly", "monthly")
                manifest["consecutive_unchanged_cycles"] = 0
                manifest["crawl_frequency"] = "weekly"
                if was_downgraded:
                    logger.info(
                        "Domain %s changed after downgrade — restored to weekly; "
                        "triggered re-crawl scheduled within 1 hour",
                        domain,
                    )
                    manifest["triggered_recrawl_after_change"] = True
            else:
                manifest["consecutive_unchanged_cycles"] = (
                    manifest.get("consecutive_unchanged_cycles", 0) + 1
                )
                unchanged = manifest["consecutive_unchanged_cycles"]
                current_freq = manifest.get("crawl_frequency", "weekly")
                if unchanged >= monthly_t and current_freq != "monthly":
                    manifest["crawl_frequency"] = "monthly"
                    logger.info(
                        "Downgraded %s → monthly (%d unchanged cycles)", domain, unchanged
                    )
                elif unchanged >= biweekly_t and current_freq == "weekly":
                    manifest["crawl_frequency"] = "biweekly"
                    logger.info(
                        "Downgraded %s → biweekly (%d unchanged cycles)", domain, unchanged
                    )

            _write_manifest_atomic(crawl_state_dir, domain, manifest)

        # ── Critical alert ─────────────────────────────────────────────
        total = self._domains_total
        if total > 0:
            failed_domains = sum(
                1
                for m in self._domain_manifests.values()
                if m.get("crawl_status") == "failed"
            )
            failure_rate = failed_domains / total
            threshold = self.settings.getfloat(
                "ALERT_THRESHOLD_DOMAIN_FAILURE_RATE", 0.20
            )
            if failure_rate > threshold:
                _emit_critical_alert(
                    settings=self.settings,
                    failure_rate=failure_rate,
                    failed_domains=failed_domains,
                    total_domains=total,
                    crawl_end=crawl_end,
                )

        duration = (crawl_end - self._crawl_start).total_seconds() if self._crawl_start else 0
        logger.info(
            "Spider closed: reason=%s total_domains=%d pages_crawled=%d "
            "failed_domains=%d duration_s=%.0f",
            reason,
            total,
            sum(self._domain_pages_crawled.values()),
            sum(self._domain_failed_requests.values()),
            duration,
        )

        # Phase D: persist new Playwright session cookies via CookieStore.save().
        # Full persistence requires hooking into Playwright page events
        # (page.context.cookies()) which is not available in the standard Scrapy
        # response cycle without a page handle. Deferred to Phase D.

        # ── QA report — spec §2.7 Quality Assurance ───────────────────────
        raw_cache = Path(
            self.settings.get("RAW_CACHE_DIR", "raw_cache")
        )
        try:
            reporter = QAReporter(raw_cache, self.settings)
            domain_stats = {
                domain: self._build_domain_stats(domain)
                for domain in self._domain_manifests
            }
            report = reporter.generate_report(
                run_date=crawl_end.strftime("%Y-%m-%d"),
                domain_stats=domain_stats,
            )
            reporter.write_report(report)
            reporter.write_summary(report)
        except Exception as exc:  # noqa: BLE001
            logger.error("QAReporter failed: %s", exc)

        # ── Retention sweep — spec §2.6 ────────────────────────────────────
        # Retain the two most recent crawl cycles for HTML pages/ dirs and
        # the four most recent for PDFs pdfs/ dirs.  Older content is deleted.
        # Any failure here is logged at WARNING and does not abort spider_closed.
        try:
            _date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
            raw_cache = Path(self.settings.get("RAW_CACHE_DIR", "raw_cache"))
            for domain in self._domain_manifests:
                domain_dir = raw_cache / domain
                if not domain_dir.is_dir():
                    continue
                cycle_dirs = sorted(
                    d for d in domain_dir.iterdir()
                    if d.is_dir() and _date_re.match(d.name)
                )
                # HTML: keep two most recent cycles.
                for old_dir in cycle_dirs[:-2]:
                    pages_dir = old_dir / "pages"
                    if pages_dir.exists():
                        shutil.rmtree(pages_dir)
                        logger.debug("Retention: removed %s", pages_dir)
                # PDF: keep four most recent cycles.
                for old_dir in cycle_dirs[:-4]:
                    pdfs_dir = old_dir / "pdfs"
                    if pdfs_dir.exists():
                        shutil.rmtree(pdfs_dir)
                        logger.debug("Retention: removed %s", pdfs_dir)
                    # Remove the date dir itself if now empty.
                    try:
                        old_dir.rmdir()
                        logger.debug("Retention: removed empty dir %s", old_dir)
                    except OSError:
                        pass  # Not empty — pages/ or other content still present.
        except Exception as exc:
            logger.warning("Retention sweep failed: %s", exc)

    # ------------------------------------------------------------------
    # QA stats builder — populates the dict consumed by QAReporter
    # ------------------------------------------------------------------

    def _build_domain_stats(self, domain: str) -> dict:
        """
        Build the stats dict expected by ``QAReporter.generate_report()``.

        All counters are now live:
        - ``pages_crawled`` and ``captcha_blocks`` from spider counters / manifest.
        - ``pdfs_found`` and ``pdf_extraction_failures`` from PDFExtractionPipeline.
        - ``grant_relevant_pages`` from parse() link-filter classification.
        - ``changed_pages`` from ChangeDetectionPipeline via _domain_changed_pages.

        Spec ref: §2.7 Domain stats schema.
        """
        manifest = self._domain_manifests.get(domain, {})
        pages = self._domain_pages_crawled.get(domain, 0)
        failed = self._domain_failed_requests.get(domain, 0)
        captcha_history = manifest.get("captcha_history", [])

        crawl_status: str
        if pages == 0 and failed > 0:
            crawl_status = "failed"
        elif manifest.get("dead_domain_candidate", False):
            crawl_status = "dead_domain_candidate"
        else:
            crawl_status = manifest.get("crawl_status", "complete")

        return {
            "pages_crawled": pages,
            "pdfs_found": self._domain_pdfs_found.get(domain, 0),
            "pdf_extraction_failures": self._domain_pdf_failures.get(domain, 0),
            "grant_relevant_pages": self._domain_grant_relevant_pages.get(domain, 0),
            "changed_pages": self._domain_changed_pages.get(domain, 0),
            "captcha_blocks": len(captcha_history),
            "http_errors": {},                # Phase B
            "crawl_status": crawl_status,
        }


# ===========================================================================
# Module-level helpers (no spider state; pure functions)
# ===========================================================================


def _load_csv(csv_path: str) -> list[dict]:
    """
    Read the seed URL CSV and return a list of row dicts.

    Uses the ``csv`` module (not pandas) as specified by the task.
    Handles UTF-8-BOM encoding from Excel exports.
    """
    rows: list[dict] = []
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append(dict(row))
    return rows


def _load_manifest(crawl_state_dir: Path, domain: str) -> dict:
    """
    Load ``crawl_state_dir/{domain}/crawl_manifest.json`` if it exists.

    Returns an empty dict if the file is absent or unreadable so callers
    can use ``.get()`` without guarding against None.
    """
    manifest_path = crawl_state_dir / domain / "crawl_manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        with manifest_path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not load manifest for %s: %s", domain, exc)
        return {}


def _write_manifest_atomic(crawl_state_dir: Path, domain: str, manifest: dict) -> None:
    """
    Atomically write *manifest* to ``crawl_state_dir/{domain}/crawl_manifest.json``.

    Uses write-to-temp + rename to prevent partial writes from corrupting
    the manifest on crash or OS interrupt.
    """
    manifest_dir = crawl_state_dir / domain
    manifest_dir.mkdir(parents=True, exist_ok=True)
    target = manifest_dir / "crawl_manifest.json"

    try:
        fd, tmp_path = tempfile.mkstemp(dir=manifest_dir, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_path, target)
    except OSError as exc:
        logger.error("Failed to write manifest for %s: %s", domain, exc)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _append_manual_review(
    crawl_state_dir: Path,
    domain: str,
    manifest: dict,
    crawl_end: datetime,
) -> None:
    """
    Append a dead-domain-candidate entry to
    ``raw_cache/manual_review_{date}.txt``.

    One line per domain; human reviewers use this file to decide whether
    the domain has moved, is temporarily offline, or has shut down.

    Spec ref: §2.7 — dead domains are listed in manual_review_{date}.txt.
    """
    date_str = crawl_end.strftime("%Y-%m-%d")
    path = crawl_state_dir / f"manual_review_{date_str}.txt"
    line = (
        f"{domain} | consecutive_failed_cycles="
        f"{manifest.get('consecutive_failed_cycles', '?')} | "
        f"last_crawl={manifest.get('last_crawl_timestamp', '?')}\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)


def _extract_jsonld(
    response: Response,
    domain: str,
    url_hash: str,
    spider,
) -> tuple[list[dict], bool]:
    """
    Find ``<script type="application/ld+json">`` blocks in the response,
    parse them, and write a ``.jsonld`` sidecar file.

    Returns (jsonld_data, has_structured_data).

    spec §2.2 step (4): "Check for JSON-LD: look for <script
    type='application/ld+json'> tags.  If found: extract text content,
    store to raw_cache/{domain}/{date}/pages/{url_hash}.jsonld, set
    meta['has_structured_data'] = True."
    """
    raw_scripts = response.css(
        'script[type="application/ld+json"]::text'
    ).getall()

    if not raw_scripts:
        return [], False

    parsed: list[dict] = []
    for script_text in raw_scripts:
        try:
            obj = json.loads(script_text)
            if isinstance(obj, list):
                parsed.extend(obj)
            elif isinstance(obj, dict):
                parsed.append(obj)
        except (json.JSONDecodeError, ValueError):
            logger.debug("Invalid JSON-LD in %s — skipping block", response.url)

    if not parsed:
        return [], False

    # Write sidecar file.
    raw_cache = Path(spider.settings.get("RAW_CACHE_DIR", "raw_cache"))
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    target_dir = raw_cache / domain / date_str / "pages"
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / f"{url_hash}.jsonld"
        with target_file.open("w", encoding="utf-8") as fh:
            json.dump(parsed, fh, ensure_ascii=False, indent=2)
    except OSError as exc:
        logger.warning("Could not write JSON-LD sidecar for %s: %s", response.url, exc)

    return parsed, True


def _emit_critical_alert(
    settings,
    failure_rate: float,
    failed_domains: int,
    total_domains: int,
    crawl_end: datetime,
) -> None:
    """
    Emit a Critical alert when the domain-failure rate exceeds the threshold.

    Writes to ``raw_cache/alerts_{YYYY-MM-DD}.log``.
    Optional email / webhook channels are wired in Phase B when
    ALERT_EMAIL_HOST / ALERT_WEBHOOK_URL are configured in ``.env``.

    spec §2.8 Alerting table (Critical row):
        "> 20% of domains in a cycle have all retries exhausted."
    Phase A build sequence note:
        "include the Critical-severity alert … from the outset."
    """
    message = (
        f"[CRITICAL] GrantGlobe crawl domain-failure rate {failure_rate:.1%} "
        f"({failed_domains}/{total_domains} domains failed) — "
        f"exceeds threshold at {crawl_end.isoformat()}"
    )
    logger.critical(message)

    raw_cache = Path(settings.get("RAW_CACHE_DIR", "raw_cache"))
    raw_cache.mkdir(parents=True, exist_ok=True)
    alert_file = raw_cache / f"alerts_{crawl_end.strftime('%Y-%m-%d')}.log"
    try:
        with alert_file.open("a", encoding="utf-8") as fh:
            fh.write(message + "\n")
    except OSError as exc:
        logger.error("Could not write alert file: %s", exc)

    # Phase B: fire-and-forget email + webhook delivery.
    # Imported inside try/except so that a missing or broken alerts package
    # never prevents spider_closed from completing (QA report must still run).
    try:
        from grantglobe_crawler.alerts.alert_sender import (
            send_email_alert,
            send_webhook_alert,
        )
        email_ok = send_email_alert(message, settings)
        webhook_ok = send_webhook_alert(message, settings)
        logger.debug(
            "Alert delivery — email=%s webhook=%s", email_ok, webhook_ok
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Alert delivery failed: %s", exc)
