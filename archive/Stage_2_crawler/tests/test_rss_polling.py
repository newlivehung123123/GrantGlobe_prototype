"""
Tests for the RSS per-cycle feed polling in GrantsSpider.start_requests().

Patches:
  - _load_csv / _load_manifest / _write_manifest_atomic (module-level helpers)
  - pathlib.Path.exists → True (so the CSV path check passes)
  - sys.modules["feedparser"] / sys.modules["requests"] (lazy imports inside try)

Does NOT instantiate GrantsSpider via Scrapy machinery; uses __new__ + manual
attribute setup so no Scrapy framework is required.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from contextlib import ExitStack
from unittest.mock import MagicMock, call, patch

import pytest
from scrapy.http import Request

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_MODULE = "grantglobe_crawler.spiders.grants_spider"


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


def _make_fp_entry(guid: str, link: str):
    e = MagicMock(spec=[])
    e.id = guid
    e.link = link
    return e


def _mock_feedparser_module(entries):
    """Return a fake 'feedparser' module whose .parse() returns *entries*."""
    mod = MagicMock()
    feed = MagicMock()
    feed.entries = entries
    mod.parse.return_value = feed
    return mod


def _mock_requests_module():
    """Return a fake 'requests' module whose .get() returns a mock response."""
    mod = MagicMock()
    resp = MagicMock()
    resp.text = "<rss/>"
    mod.get.return_value = resp
    return mod


_CSV_ROW = [{"domain": "example.org", "grants_url": "https://example.org/grants"}]


def _run(spider, manifest, feedparser_entries=None, *, raise_on_get=False):
    """
    Execute spider.start_requests() with all external I/O mocked.

    Returns list of yielded scrapy.http.Request objects.
    """
    fp_mod = _mock_feedparser_module(feedparser_entries or [])
    req_mod = _mock_requests_module()
    if raise_on_get:
        req_mod.get.side_effect = ConnectionError("network down")

    # Inject fresh sys.modules mocks for lazy imports inside the try block.
    fake_sys_modules = dict(sys.modules)
    fake_sys_modules["feedparser"] = fp_mod
    fake_sys_modules["requests"] = req_mod

    with ExitStack() as stack:
        stack.enter_context(patch(f"{_MODULE}._load_csv", return_value=_CSV_ROW))
        stack.enter_context(patch(f"{_MODULE}._load_manifest", return_value=dict(manifest)))
        write_mock = stack.enter_context(patch(f"{_MODULE}._write_manifest_atomic"))
        stack.enter_context(patch("pathlib.Path.exists", return_value=True))
        stack.enter_context(patch.dict(sys.modules, fake_sys_modules))

        reqs = list(spider.start_requests())

    return reqs, write_mock


# ---------------------------------------------------------------------------
# Test 1: GUID set unchanged → skip
# ---------------------------------------------------------------------------


class TestRssGuidUnchanged:
    def test_no_seed_request_when_guid_set_unchanged(self):
        """When current GUIDs == previous GUIDs, the domain is skipped entirely."""
        spider = _make_spider()
        manifest = {
            "crawl_profile": "A",
            "rate_limit_floor_seconds": 4.0,
            "rss_feed_url": "https://example.org/feed",
            "rss_guid_set": ["guid1", "guid2"],
        }
        entries = [_make_fp_entry("guid1", "https://example.org/p1"),
                   _make_fp_entry("guid2", "https://example.org/p2")]

        reqs, write_mock = _run(spider, manifest, entries)

        # All Requests are suppressed (continue was hit).
        assert reqs == []

    def test_crawl_skip_reason_written(self):
        """crawl_skip_reason='rss_no_change' is written to the manifest on skip."""
        spider = _make_spider()
        manifest = {
            "crawl_profile": "A",
            "rate_limit_floor_seconds": 4.0,
            "rss_feed_url": "https://example.org/feed",
            "rss_guid_set": ["guid1"],
        }
        entries = [_make_fp_entry("guid1", "https://example.org/p1")]

        reqs, write_mock = _run(spider, manifest, entries)

        write_mock.assert_called_once()
        # Third positional arg to _write_manifest_atomic is the manifest dict.
        saved_manifest = write_mock.call_args[0][2]
        assert saved_manifest.get("crawl_skip_reason") == "rss_no_change"


# ---------------------------------------------------------------------------
# Test 2: New GUIDs → RSS item Requests + seed Request
# ---------------------------------------------------------------------------


class TestRssNewGuids:
    def test_seed_request_yielded_when_new_guids(self):
        """When new GUIDs exist, the seed Request IS yielded."""
        spider = _make_spider()
        manifest = {
            "crawl_profile": "A",
            "rate_limit_floor_seconds": 4.0,
            "rss_feed_url": "https://example.org/feed",
            "rss_guid_set": ["guid1"],
        }
        entries = [
            _make_fp_entry("guid1", "https://example.org/p1"),
            _make_fp_entry("guid2", "https://example.org/p2-new"),
        ]

        reqs, _ = _run(spider, manifest, entries)

        # At least the seed Request must be present.
        seed_reqs = [r for r in reqs if r.url == "https://example.org/grants"]
        assert len(seed_reqs) == 1

    def test_rss_item_requests_have_source_meta(self):
        """New-GUID Requests carry meta['source'] == 'rss' and depth == 0."""
        spider = _make_spider()
        manifest = {
            "crawl_profile": "A",
            "rate_limit_floor_seconds": 4.0,
            "rss_feed_url": "https://example.org/feed",
            "rss_guid_set": [],
        }
        entries = [_make_fp_entry("guid1", "https://example.org/grant-page")]

        reqs, _ = _run(spider, manifest, entries)

        rss_reqs = [r for r in reqs if r.meta.get("source") == "rss"]
        assert len(rss_reqs) == 1
        assert rss_reqs[0].url == "https://example.org/grant-page"
        assert rss_reqs[0].meta["depth"] == 0


# ---------------------------------------------------------------------------
# Test 3: RSS fetch raises → seed Request still yielded
# ---------------------------------------------------------------------------


class TestRssFetchError:
    def test_seed_request_yielded_on_rss_exception(self):
        """If requests.get raises, the spider falls through to the seed Request."""
        spider = _make_spider()
        manifest = {
            "crawl_profile": "A",
            "rate_limit_floor_seconds": 4.0,
            "rss_feed_url": "https://example.org/feed",
            "rss_guid_set": [],
        }

        reqs, _ = _run(spider, manifest, raise_on_get=True)

        seed_reqs = [r for r in reqs if r.url == "https://example.org/grants"]
        assert len(seed_reqs) == 1

    def test_no_exception_propagates_on_rss_failure(self):
        """RSS fetch failure must never raise; start_requests() completes normally."""
        spider = _make_spider()
        manifest = {
            "crawl_profile": "A",
            "rate_limit_floor_seconds": 4.0,
            "rss_feed_url": "https://example.org/feed",
            "rss_guid_set": [],
        }
        # Should not raise:
        reqs, _ = _run(spider, manifest, raise_on_get=True)
        assert isinstance(reqs, list)


# ---------------------------------------------------------------------------
# Test 4: rss_guid_set is updated (and serialisable as JSON list)
# ---------------------------------------------------------------------------


class TestRssGuidSetUpdated:
    def test_guid_set_updated_on_skip_path(self):
        """manifest['rss_guid_set'] written as a list (JSON-serialisable) on skip."""
        spider = _make_spider()
        manifest = {
            "crawl_profile": "A",
            "rate_limit_floor_seconds": 4.0,
            "rss_feed_url": "https://example.org/feed",
            "rss_guid_set": ["guid1"],
        }
        entries = [_make_fp_entry("guid1", "https://example.org/p1")]

        reqs, write_mock = _run(spider, manifest, entries)

        saved = write_mock.call_args[0][2]
        guid_set = saved["rss_guid_set"]
        assert isinstance(guid_set, list), "rss_guid_set must be a list, not a set"
        assert set(guid_set) == {"guid1"}

    def test_guid_set_updated_on_new_guid_path(self):
        """manifest['rss_guid_set'] contains current GUIDs even on the crawl path."""
        spider = _make_spider()
        manifest = {
            "crawl_profile": "A",
            "rate_limit_floor_seconds": 4.0,
            "rss_feed_url": "https://example.org/feed",
            "rss_guid_set": ["guid1"],
        }
        entries = [
            _make_fp_entry("guid1", "https://example.org/p1"),
            _make_fp_entry("guid2", "https://example.org/p2"),
        ]

        reqs, _ = _run(spider, manifest, entries)

        # manifest is live in spider._domain_manifests after start_requests.
        stored = spider._domain_manifests.get("example.org", {})
        assert isinstance(stored.get("rss_guid_set"), list)
        assert set(stored["rss_guid_set"]) == {"guid1", "guid2"}


# ---------------------------------------------------------------------------
# Test 5: No rss_feed_url → normal seed Request
# ---------------------------------------------------------------------------


class TestNoRssFeedUrl:
    def test_seed_request_yielded_when_no_rss_feed_url(self):
        """Domains without rss_feed_url proceed to normal seed Request unaffected."""
        spider = _make_spider()
        manifest = {
            "crawl_profile": "A",
            "rate_limit_floor_seconds": 4.0,
            # No rss_feed_url key
        }

        reqs, _ = _run(spider, manifest)

        seed_reqs = [r for r in reqs if r.url == "https://example.org/grants"]
        assert len(seed_reqs) == 1
        # No extra RSS requests.
        assert all(r.meta.get("source") != "rss" for r in reqs)


# ---------------------------------------------------------------------------
# Test 6: RSS item already in seen_urls → not re-yielded
# ---------------------------------------------------------------------------


class TestRssSeenUrls:
    def test_seen_url_not_re_yielded(self):
        """If a new-GUID link is already in seen_urls, it is skipped."""
        spider = _make_spider()
        # Pre-populate seen_urls with the new item's canonical URL.
        spider.seen_urls.add("https://example.org/grant-new/")

        manifest = {
            "crawl_profile": "A",
            "rate_limit_floor_seconds": 4.0,
            "rss_feed_url": "https://example.org/feed",
            "rss_guid_set": [],
        }
        # This entry's canonicalised URL is already in seen_urls.
        entries = [_make_fp_entry("guid-new", "https://example.org/grant-new/")]

        reqs, _ = _run(spider, manifest, entries)

        rss_reqs = [r for r in reqs if r.meta.get("source") == "rss"]
        assert rss_reqs == [], "Already-seen URL must not be re-yielded"
        # The seed Request is still yielded.
        seed_reqs = [r for r in reqs if r.url == "https://example.org/grants"]
        assert len(seed_reqs) == 1
