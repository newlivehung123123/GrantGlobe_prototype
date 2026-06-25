"""
Tests for sitemap URL seeding in GrantsSpider.start_requests().

Sitemap URLs from manifest['sitemap_grant_urls'] are yielded as depth=1
Requests AFTER the seed Request.  PDF URLs bypass the link filter.
No Playwright meta is set regardless of domain profile.

Patches:
  _load_csv / _load_manifest (module helpers)
  pathlib.Path.exists → True
"""

from __future__ import annotations

import logging
from collections import defaultdict
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

_MODULE = "grantglobe_crawler.spiders.grants_spider"


# ---------------------------------------------------------------------------
# Shared helpers (duplicated from test_rss_polling to keep files standalone)
# ---------------------------------------------------------------------------


class _Settings:
    _D = {
        "SOURCE_LIST_CSV": "/fake/source_list.csv",
        "CRAWL_STATE_DIR": "/fake/raw_cache",
        "RAW_CACHE_DIR": "/fake/raw_cache",
    }

    def get(self, key, default=None):
        return self._D.get(key, default)

    def getint(self, key, default=0):
        return int({"MAX_CRAWL_DEPTH": 3, "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT": 20000}.get(key, default))

    def getfloat(self, key, default=0.0):
        return float({"DOWNLOAD_DELAY": 4.0}.get(key, default))

    def getlist(self, key, default=None):
        return default or []


def _make_spider():
    from grantglobe_crawler.spiders.grants_spider import GrantsSpider
    spider = object.__new__(GrantsSpider)
    spider.seen_urls = set()
    spider._domain_manifests = {}
    spider._domain_pages_crawled = defaultdict(int)
    spider._domain_failed_requests = defaultdict(int)
    spider._domain_pdfs_found = defaultdict(int)
    spider._domain_pdf_failures = defaultdict(int)
    spider._domains_total = 0
    spider._crawl_start = None
    spider._pagination_handler = MagicMock()
    spider.settings = _Settings()
    return spider


_CSV_ROW = [{"domain": "example.org", "grants_url": "https://example.org/grants"}]


def _run(spider, manifest):
    """Execute start_requests() with all I/O mocked; return list of Requests."""
    with ExitStack() as stack:
        stack.enter_context(patch(f"{_MODULE}._load_csv", return_value=_CSV_ROW))
        stack.enter_context(patch(f"{_MODULE}._load_manifest", return_value=dict(manifest)))
        stack.enter_context(patch(f"{_MODULE}._write_manifest_atomic"))
        stack.enter_context(patch("pathlib.Path.exists", return_value=True))
        return list(spider.start_requests())


# ---------------------------------------------------------------------------
# Test 1: Three passing sitemap URLs → three depth-1 Requests after seed
# ---------------------------------------------------------------------------


class TestSitemapSeeding:
    def test_three_grant_urls_yield_three_requests(self):
        """Three sitemap URLs that pass the link filter → three depth=1 Requests."""
        spider = _make_spider()
        manifest = {
            "crawl_profile": "A",
            "rate_limit_floor_seconds": 4.0,
            "sitemap_grant_urls": [
                "https://example.org/grants/scheme-a",
                "https://example.org/grants/scheme-b",
                "https://example.org/grants/scheme-c",
            ],
            "sitemap_url": "https://example.org/sitemap.xml",
        }

        reqs = _run(spider, manifest)

        sitemap_reqs = [r for r in reqs if r.meta.get("source") == "sitemap"]
        assert len(sitemap_reqs) == 3

    def test_sitemap_requests_have_depth_1(self):
        """Sitemap Requests must have depth=1 (not depth=0)."""
        spider = _make_spider()
        manifest = {
            "crawl_profile": "A",
            "rate_limit_floor_seconds": 4.0,
            "sitemap_grant_urls": ["https://example.org/grants/scheme-a"],
        }

        reqs = _run(spider, manifest)

        sitemap_reqs = [r for r in reqs if r.meta.get("source") == "sitemap"]
        assert all(r.meta["depth"] == 1 for r in sitemap_reqs)

    def test_sitemap_requests_have_no_playwright_key(self):
        """Sitemap Requests MUST NOT have 'playwright' in meta (Profile B domain)."""
        spider = _make_spider()
        manifest = {
            "crawl_profile": "B",  # Profile B domain
            "rate_limit_floor_seconds": 4.0,
            "sitemap_grant_urls": ["https://example.org/grants/scheme-a"],
        }

        reqs = _run(spider, manifest)

        sitemap_reqs = [r for r in reqs if r.meta.get("source") == "sitemap"]
        assert sitemap_reqs, "Expected at least one sitemap Request"
        for r in sitemap_reqs:
            assert "playwright" not in r.meta, (
                f"Sitemap Request for {r.url} must never use Playwright"
            )

    def test_seed_request_comes_before_sitemap_requests(self):
        """Seed Request is yielded first; sitemap Requests follow."""
        spider = _make_spider()
        manifest = {
            "crawl_profile": "A",
            "rate_limit_floor_seconds": 4.0,
            "sitemap_grant_urls": ["https://example.org/grants/award-2026"],
        }

        reqs = _run(spider, manifest)

        assert len(reqs) >= 2
        assert reqs[0].url == "https://example.org/grants"  # seed first


# ---------------------------------------------------------------------------
# Test 2: URL already in seen_urls → skipped
# ---------------------------------------------------------------------------


class TestSitemapSeenUrls:
    def test_already_seen_url_not_re_yielded(self):
        """A sitemap URL already in seen_urls is not enqueued a second time."""
        spider = _make_spider()
        # Canonicalised form — trailing slash added by canonicalise().
        spider.seen_urls.add("https://example.org/grants/scheme-a/")

        manifest = {
            "crawl_profile": "A",
            "rate_limit_floor_seconds": 4.0,
            "sitemap_grant_urls": [
                "https://example.org/grants/scheme-a",
                "https://example.org/grants/scheme-b",
            ],
        }

        reqs = _run(spider, manifest)

        sitemap_urls = [r.url for r in reqs if r.meta.get("source") == "sitemap"]
        assert "https://example.org/grants/scheme-a" not in sitemap_urls
        # The other URL is still yielded.
        assert any("scheme-b" in u for u in sitemap_urls)


# ---------------------------------------------------------------------------
# Test 3: More than 50 URLs → WARNING + exactly 50 Requests
# ---------------------------------------------------------------------------


class TestSitemapCap:
    def test_cap_at_50_urls(self, caplog):
        """More than 50 sitemap URLs → WARNING logged, exactly 50 enqueued."""
        spider = _make_spider()
        # 55 URLs — all with "grants" in path so they pass the link filter.
        sitemap_urls = [
            f"https://example.org/grants/item-{i}" for i in range(55)
        ]
        manifest = {
            "crawl_profile": "A",
            "rate_limit_floor_seconds": 4.0,
            "sitemap_grant_urls": sitemap_urls,
        }

        with caplog.at_level(logging.WARNING, logger=_MODULE):
            reqs = _run(spider, manifest)

        sitemap_reqs = [r for r in reqs if r.meta.get("source") == "sitemap"]
        assert len(sitemap_reqs) == 50

        warn_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("capping at 50" in m for m in warn_messages)


# ---------------------------------------------------------------------------
# Test 4: PDF URL in sitemap → is_pdf=True, link filter bypassed
# ---------------------------------------------------------------------------


class TestSitemapPdf:
    def test_pdf_url_yielded_with_is_pdf_true(self):
        """PDF URL in sitemap_grant_urls → Request with meta['is_pdf']=True."""
        spider = _make_spider()
        manifest = {
            "crawl_profile": "A",
            "rate_limit_floor_seconds": 4.0,
            "sitemap_grant_urls": ["https://example.org/publications/report.pdf"],
        }

        reqs = _run(spider, manifest)

        pdf_reqs = [r for r in reqs if r.meta.get("source") == "sitemap" and r.meta.get("is_pdf")]
        assert len(pdf_reqs) == 1
        assert pdf_reqs[0].url == "https://example.org/publications/report.pdf"

    def test_pdf_in_sitemap_does_not_need_grant_signal(self):
        """PDF URL does not need to pass the link filter (bypassed for PDFs)."""
        spider = _make_spider()
        # URL has no grant signals in path — would fail link filter for HTML.
        manifest = {
            "crawl_profile": "A",
            "rate_limit_floor_seconds": 4.0,
            "sitemap_grant_urls": ["https://example.org/staff/minutes.pdf"],
        }

        reqs = _run(spider, manifest)

        sitemap_reqs = [r for r in reqs if r.meta.get("source") == "sitemap"]
        assert len(sitemap_reqs) == 1
        assert sitemap_reqs[0].meta["is_pdf"] is True


# ---------------------------------------------------------------------------
# Test 5: Non-grant URL that fails link filter → not yielded
# ---------------------------------------------------------------------------


class TestSitemapLinkFilter:
    def test_non_grant_url_filtered_out(self):
        """Sitemap HTML URL with no grant signals and negative scores → not enqueued."""
        spider = _make_spider()
        # Only negative signals (about, staff) → score < 0, fails filter at depth=1.
        manifest = {
            "crawl_profile": "A",
            "rate_limit_floor_seconds": 4.0,
            "sitemap_grant_urls": [
                "https://example.org/about/staff-team",
                "https://example.org/grants/award-2026",  # should pass
            ],
        }

        reqs = _run(spider, manifest)

        sitemap_reqs = [r for r in reqs if r.meta.get("source") == "sitemap"]
        urls = [r.url for r in sitemap_reqs]
        assert "https://example.org/about/staff-team" not in urls
        assert any("award" in u for u in urls)


# ---------------------------------------------------------------------------
# Test 6: Empty sitemap_grant_urls → only seed Request
# ---------------------------------------------------------------------------


class TestSitemapEmpty:
    def test_empty_sitemap_yields_only_seed(self):
        """Empty sitemap_grant_urls → exactly one Request (the seed)."""
        spider = _make_spider()
        manifest = {
            "crawl_profile": "A",
            "rate_limit_floor_seconds": 4.0,
            "sitemap_grant_urls": [],
        }

        reqs = _run(spider, manifest)

        assert len(reqs) == 1
        assert reqs[0].url == "https://example.org/grants"

    def test_missing_sitemap_key_yields_only_seed(self):
        """If manifest has no 'sitemap_grant_urls' key, only seed is yielded."""
        spider = _make_spider()
        manifest = {
            "crawl_profile": "A",
            "rate_limit_floor_seconds": 4.0,
        }

        reqs = _run(spider, manifest)

        assert len(reqs) == 1
        assert reqs[0].url == "https://example.org/grants"
