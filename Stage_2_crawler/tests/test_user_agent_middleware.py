"""
Unit tests for UserAgentMiddleware.

Tests:
- First request for a domain gets a UA from the pool
- Second request for the same domain gets the SAME UA (session-stable)
- Two different domains get independent UAs
- UA is set in request.headers["User-Agent"]
- Playwright meta gets playwright_context_kwargs with user_agent key
- Existing playwright_context_kwargs dict is extended (not replaced)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from scrapy.http import Request

from grantglobe_crawler.middlewares.user_agent import UserAgentMiddleware

_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) Chrome/130.0",
    "Mozilla/5.0 (X11; Linux x86_64) Firefox/125.0",
]


def _make_middleware(pool=None) -> UserAgentMiddleware:
    return UserAgentMiddleware(ua_pool=pool or _POOL)


def _make_request(url: str, domain: str | None = None, **meta) -> Request:
    m = {"domain": domain or "example.org"} | meta
    return Request(url, meta=m)


def _make_spider():
    spider = MagicMock()
    spider.name = "grants"
    return spider


class TestUserAgentMiddleware:
    def test_first_request_gets_ua_from_pool(self):
        mw = _make_middleware()
        req = _make_request("https://example.org/grants")
        mw.process_request(req, _make_spider())

        ua = req.headers.get("User-Agent")
        assert ua is not None
        decoded = ua.decode("utf-8") if isinstance(ua, bytes) else ua
        assert decoded in _POOL

    def test_second_request_same_domain_gets_same_ua(self):
        mw = _make_middleware()
        spider = _make_spider()
        req1 = _make_request("https://example.org/page1")
        req2 = _make_request("https://example.org/page2")

        mw.process_request(req1, spider)
        mw.process_request(req2, spider)

        ua1 = req1.headers.get("User-Agent")
        ua2 = req2.headers.get("User-Agent")
        assert ua1 == ua2, "Same domain must receive identical UA across requests"

    def test_two_domains_get_independent_uas(self):
        """Two domains are assigned UAs independently (may differ by chance)."""
        # Use a pool with only two distinct UAs so we can control the assignment
        # via seeding; instead we just verify that the assignments are made
        # independently (each domain has its own stored UA).
        mw = _make_middleware()
        spider = _make_spider()
        req_a = _make_request("https://alpha.org/grants", domain="alpha.org")
        req_b = _make_request("https://beta.org/grants", domain="beta.org")

        mw.process_request(req_a, spider)
        mw.process_request(req_b, spider)

        # Each domain must have its own entry in the cache.
        assert "alpha.org" in mw._domain_ua
        assert "beta.org" in mw._domain_ua
        # Both assigned UAs must come from the pool.
        assert mw._domain_ua["alpha.org"] in _POOL
        assert mw._domain_ua["beta.org"] in _POOL

    def test_ua_set_in_headers(self):
        mw = _make_middleware()
        req = _make_request("https://example.org/")
        mw.process_request(req, _make_spider())

        raw = req.headers.get("User-Agent")
        assert raw is not None
        decoded = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        assert len(decoded) > 20, "User-Agent should be a real browser string"

    def test_playwright_meta_gets_playwright_context_kwargs(self):
        mw = _make_middleware()
        req = _make_request(
            "https://example.org/",
            playwright=True,
        )
        mw.process_request(req, _make_spider())

        ctx = req.meta.get("playwright_context_kwargs")
        assert isinstance(ctx, dict), "playwright_context_kwargs must be a dict"
        assert "user_agent" in ctx, "user_agent key must be injected"
        assert ctx["user_agent"] in _POOL

    def test_existing_playwright_context_kwargs_extended_not_replaced(self):
        """If playwright_context_kwargs already exists, user_agent is added to it."""
        mw = _make_middleware()
        existing_ctx = {"locale": "en-US", "viewport": {"width": 1280, "height": 800}}
        req = _make_request(
            "https://example.org/",
            playwright=True,
            playwright_context_kwargs=existing_ctx,
        )
        mw.process_request(req, _make_spider())

        ctx = req.meta["playwright_context_kwargs"]
        assert ctx["locale"] == "en-US", "Existing keys must be preserved"
        assert "user_agent" in ctx

    def test_playwright_false_does_not_inject_context_kwargs(self):
        mw = _make_middleware()
        req = _make_request("https://example.org/page.pdf", playwright=False)
        mw.process_request(req, _make_spider())

        # No playwright_context_kwargs should be created for non-Playwright requests.
        ctx = req.meta.get("playwright_context_kwargs")
        assert ctx is None

    def test_fallback_to_url_netloc_when_domain_meta_absent(self):
        """Middleware falls back to URL netloc if meta['domain'] is not set."""
        mw = _make_middleware()
        req = Request("https://fallback.org/page", meta={})  # no 'domain' key
        mw.process_request(req, _make_spider())

        assert "fallback.org" in mw._domain_ua
        raw = req.headers.get("User-Agent")
        assert raw is not None
