"""
Tests for Playwright session-cookie injection in GrantsSpider.start_requests().

Patches:
  - grantglobe_crawler.spiders.grants_spider._load_csv / _load_manifest
  - pathlib.Path.exists → True
  - grantglobe_crawler.utils.cookie_store.CookieStore (full class mock)
  - os.environ.get inside the spider (via sys.modules injection)

Does NOT instantiate GrantsSpider via Scrapy machinery; uses __new__ +
manual attribute setup identical to the other start_requests() test files.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from contextlib import ExitStack
from unittest.mock import MagicMock, patch, call

import pytest

_MODULE = "grantglobe_crawler.spiders.grants_spider"


# ---------------------------------------------------------------------------
# Shared helpers
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
        return int(
            {"MAX_CRAWL_DEPTH": 3, "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT": 20_000}.get(
                key, default
            )
        )

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


def _run(spider, manifest, *, enc_key="VALID_FERNET_KEY", cookie_store_cls=None):
    """
    Execute start_requests() with all external I/O mocked.

    *enc_key*         — value returned by os.environ.get("COOKIE_ENCRYPTION_KEY")
    *cookie_store_cls*— replacement for CookieStore class (MagicMock by default)

    Returns list of yielded Requests.
    """
    csv_rows = [{"domain": "example.org", "grants_url": "https://example.org/grants"}]

    # Build a fake 'os' module whose .environ.get() returns our key.
    fake_os = MagicMock()
    fake_os.environ.get.side_effect = (
        lambda k, default="": enc_key if k == "COOKIE_ENCRYPTION_KEY" else default
    )

    # Default CookieStore mock returns None from .load().
    if cookie_store_cls is None:
        cookie_store_cls = MagicMock(spec=["load"])
        cookie_store_cls.return_value.load.return_value = None

    fake_sys_modules = dict(sys.modules)
    fake_sys_modules["os"] = fake_os

    with ExitStack() as stack:
        stack.enter_context(patch(f"{_MODULE}._load_csv", return_value=csv_rows))
        stack.enter_context(patch(f"{_MODULE}._load_manifest", return_value=dict(manifest)))
        stack.enter_context(patch(f"{_MODULE}._write_manifest_atomic"))
        stack.enter_context(patch("pathlib.Path.exists", return_value=True))
        # Patch CookieStore at its definition point so the lazy import gets the mock.
        stack.enter_context(
            patch("grantglobe_crawler.utils.cookie_store.CookieStore", cookie_store_cls)
        )
        # Also patch it at the import path used inside the spider's try block.
        stack.enter_context(
            patch(
                "grantglobe_crawler.spiders.grants_spider.CookieStore",
                cookie_store_cls,
                create=True,
            )
        )
        stack.enter_context(patch.dict(sys.modules, fake_sys_modules))
        return list(spider.start_requests())


# ---------------------------------------------------------------------------
# Test 1 — Profile B + valid key + cookies returned → storage_state injected
# ---------------------------------------------------------------------------


class TestCookieInjectionHappyPath:
    def test_cookies_injected_into_playwright_context(self):
        """
        Profile B domain with has_stored_cookies=True and a valid key:
        CookieStore.load() returns cookies → seed Request has
        meta['playwright_context_kwargs']['storage_state']['cookies'] set.
        """
        spider = _make_spider()

        fake_cookies = [{"name": "session", "value": "abc123", "domain": "example.org"}]
        store_instance = MagicMock()
        store_instance.load.return_value = fake_cookies
        CookieStoreCls = MagicMock(return_value=store_instance)

        manifest = {
            "crawl_profile": "B",
            "rate_limit_floor_seconds": 4.0,
            "has_stored_cookies": True,
        }

        reqs = _run(spider, manifest, enc_key="VALID_KEY", cookie_store_cls=CookieStoreCls)

        seed = next((r for r in reqs if r.url == "https://example.org/grants"), None)
        assert seed is not None
        ctx = seed.meta.get("playwright_context_kwargs", {})
        storage = ctx.get("storage_state", {})
        assert storage.get("cookies") == fake_cookies

    def test_storage_state_origins_is_empty_list(self):
        """origins must always be [] in the injected storage_state."""
        spider = _make_spider()

        fake_cookies = [{"name": "token", "value": "xyz", "domain": "example.org"}]
        store_instance = MagicMock()
        store_instance.load.return_value = fake_cookies
        CookieStoreCls = MagicMock(return_value=store_instance)

        manifest = {
            "crawl_profile": "B",
            "rate_limit_floor_seconds": 4.0,
            "has_stored_cookies": True,
        }

        reqs = _run(spider, manifest, enc_key="KEY", cookie_store_cls=CookieStoreCls)

        seed = reqs[0]
        origins = seed.meta["playwright_context_kwargs"]["storage_state"]["origins"]
        assert origins == []


# ---------------------------------------------------------------------------
# Test 2 — Profile A → CookieStore never instantiated
# ---------------------------------------------------------------------------


class TestCookieInjectionProfileA:
    def test_profile_a_does_not_instantiate_cookie_store(self):
        """Profile A domain: CookieStore must never be created."""
        spider = _make_spider()

        CookieStoreCls = MagicMock()

        manifest = {
            "crawl_profile": "A",
            "rate_limit_floor_seconds": 4.0,
            "has_stored_cookies": True,
        }

        reqs = _run(spider, manifest, enc_key="VALID_KEY", cookie_store_cls=CookieStoreCls)

        CookieStoreCls.assert_not_called()
        # Seed request is still yielded.
        assert any(r.url == "https://example.org/grants" for r in reqs)

    def test_profile_a_seed_has_no_storage_state(self):
        """Profile A seed Request must not contain storage_state in meta."""
        spider = _make_spider()

        manifest = {
            "crawl_profile": "A",
            "rate_limit_floor_seconds": 4.0,
            "has_stored_cookies": True,
        }

        reqs = _run(spider, manifest, enc_key="VALID_KEY")

        seed = next(r for r in reqs if r.url == "https://example.org/grants")
        ctx = seed.meta.get("playwright_context_kwargs", {})
        assert "storage_state" not in ctx


# ---------------------------------------------------------------------------
# Test 3 — load() returns None → no storage_state, seed still yielded
# ---------------------------------------------------------------------------


class TestCookieInjectionLoadNone:
    def test_seed_yielded_when_load_returns_none(self):
        """CookieStore.load() returns None → seed yielded without storage_state."""
        spider = _make_spider()

        store_instance = MagicMock()
        store_instance.load.return_value = None
        CookieStoreCls = MagicMock(return_value=store_instance)

        manifest = {
            "crawl_profile": "B",
            "rate_limit_floor_seconds": 4.0,
            "has_stored_cookies": True,
        }

        reqs = _run(spider, manifest, enc_key="VALID_KEY", cookie_store_cls=CookieStoreCls)

        seed = next(r for r in reqs if r.url == "https://example.org/grants")
        ctx = seed.meta.get("playwright_context_kwargs", {})
        assert "storage_state" not in ctx

    def test_no_exception_when_load_returns_none(self):
        """No exception must propagate when CookieStore.load() returns None."""
        spider = _make_spider()

        store_instance = MagicMock()
        store_instance.load.return_value = None
        CookieStoreCls = MagicMock(return_value=store_instance)

        manifest = {
            "crawl_profile": "B",
            "rate_limit_floor_seconds": 4.0,
            "has_stored_cookies": True,
        }

        # Should not raise:
        reqs = _run(spider, manifest, enc_key="VALID_KEY", cookie_store_cls=CookieStoreCls)
        assert isinstance(reqs, list)


# ---------------------------------------------------------------------------
# Test 4 — empty COOKIE_ENCRYPTION_KEY → CookieStore never instantiated
# ---------------------------------------------------------------------------


class TestCookieInjectionNoKey:
    def test_empty_key_skips_cookie_store(self):
        """COOKIE_ENCRYPTION_KEY absent (empty string) → CookieStore not created."""
        spider = _make_spider()

        CookieStoreCls = MagicMock()

        manifest = {
            "crawl_profile": "B",
            "rate_limit_floor_seconds": 4.0,
            "has_stored_cookies": True,
        }

        reqs = _run(spider, manifest, enc_key="", cookie_store_cls=CookieStoreCls)

        CookieStoreCls.assert_not_called()

    def test_empty_key_still_yields_seed(self):
        """Seed Request is still yielded even when no encryption key is configured."""
        spider = _make_spider()

        manifest = {
            "crawl_profile": "B",
            "rate_limit_floor_seconds": 4.0,
            "has_stored_cookies": True,
        }

        reqs = _run(spider, manifest, enc_key="")

        assert any(r.url == "https://example.org/grants" for r in reqs)


# ---------------------------------------------------------------------------
# Test 5 — CookieStore.__init__() raises ValueError → WARNING, seed yielded
# ---------------------------------------------------------------------------


class TestCookieInjectionInitError:
    def test_cookie_store_init_raises_warning_logged(self, caplog):
        """ValueError from CookieStore.__init__() → WARNING logged, no crash."""
        import logging

        spider = _make_spider()

        CookieStoreCls = MagicMock(side_effect=ValueError("bad key"))

        manifest = {
            "crawl_profile": "B",
            "rate_limit_floor_seconds": 4.0,
            "has_stored_cookies": True,
        }

        with caplog.at_level(logging.WARNING, logger=_MODULE):
            reqs = _run(spider, manifest, enc_key="BAD_KEY", cookie_store_cls=CookieStoreCls)

        warn_msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("Cookie injection failed" in m for m in warn_msgs)

    def test_seed_yielded_when_cookie_store_init_raises(self):
        """Seed Request is still yielded when CookieStore raises on init."""
        spider = _make_spider()

        CookieStoreCls = MagicMock(side_effect=ValueError("bad key"))

        manifest = {
            "crawl_profile": "B",
            "rate_limit_floor_seconds": 4.0,
            "has_stored_cookies": True,
        }

        reqs = _run(spider, manifest, enc_key="BAD_KEY", cookie_store_cls=CookieStoreCls)

        assert any(r.url == "https://example.org/grants" for r in reqs)
