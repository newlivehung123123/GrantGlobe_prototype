"""
Unit tests for ProxyRotationMiddleware.

Tests:
- Profile D with all credentials: proxy is set in request.meta["proxy"]
- Profile A with all credentials: proxy is NOT set
- Profile D with missing credentials: no proxy, WARNING logged once
- Playwright Profile D: playwright_context_kwargs["proxy"] is set correctly
- Proxy URL is constructed correctly from settings
- Credentials never appear in log output (caplog inspection)
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
from scrapy.http import Request

from grantglobe_crawler.middlewares.proxy import ProxyRotationMiddleware

_HOST = "proxy.example.com"
_PORT = "8080"
_USER = "myuser"
_PASS = "s3cr3t"


def _make_middleware(
    host=_HOST,
    port=_PORT,
    username=_USER,
    password=_PASS,
    enabled=True,          # existing tests exercise the active middleware
) -> ProxyRotationMiddleware:
    return ProxyRotationMiddleware(
        proxy_host=host,
        proxy_port=port,
        proxy_username=username,
        proxy_password=password,
        enabled=enabled,
    )


def _make_request(url="https://blocked.org/", profile="D", **meta) -> Request:
    m = {"domain": "blocked.org", "profile": profile} | meta
    return Request(url, meta=m)


def _make_spider():
    s = MagicMock()
    s.name = "grants"
    return s


class TestProxyRotationMiddleware:
    def test_profile_d_with_credentials_sets_proxy(self):
        """Profile D + complete credentials → proxy meta is set."""
        mw = _make_middleware()
        req = _make_request(profile="D")
        mw.process_request(req, _make_spider())

        assert "proxy" in req.meta
        expected = f"http://{_USER}:{_PASS}@{_HOST}:{_PORT}"
        assert req.meta["proxy"] == expected

    def test_profile_a_with_credentials_no_proxy(self):
        """Profile A (non-bot-protected) never gets a proxy, even with credentials."""
        mw = _make_middleware()
        for profile in ("A", "B", "C"):
            req = _make_request(profile=profile)
            mw.process_request(req, _make_spider())
            assert "proxy" not in req.meta, f"Profile {profile} should not get a proxy"

    def test_profile_d_missing_credentials_no_proxy(self):
        """Profile D with incomplete credentials: no proxy is injected."""
        mw = _make_middleware(host="", port="", username="", password="")
        req = _make_request(profile="D")
        mw.process_request(req, _make_spider())
        assert "proxy" not in req.meta

    def test_profile_d_missing_credentials_warns_once(self, caplog):
        """WARNING is emitted once (not per request) when credentials are missing."""
        mw = _make_middleware(host="", port="", username="", password="")
        spider = _make_spider()

        with caplog.at_level(logging.WARNING, logger="grantglobe_crawler.middlewares.proxy"):
            for _ in range(3):
                req = _make_request(profile="D")
                mw.process_request(req, spider)

        # The warning should fire exactly once despite 3 requests.
        warn_records = [
            r for r in caplog.records if "proxy credentials are not configured" in r.message
        ]
        assert len(warn_records) == 1

    def test_proxy_url_constructed_correctly(self):
        """Proxy URL follows the format http://user:pass@host:port."""
        mw = _make_middleware(host="rp.example.net", port="9999", username="u1", password="p1")
        req = _make_request(profile="D")
        mw.process_request(req, _make_spider())
        assert req.meta["proxy"] == "http://u1:p1@rp.example.net:9999"

    def test_playwright_profile_d_sets_context_proxy(self):
        """Playwright Profile D requests also get playwright_context_kwargs["proxy"]."""
        mw = _make_middleware()
        req = _make_request(profile="D", playwright=True)
        mw.process_request(req, _make_spider())

        ctx = req.meta.get("playwright_context_kwargs")
        assert isinstance(ctx, dict), "playwright_context_kwargs must be a dict"
        assert "proxy" in ctx
        assert ctx["proxy"]["server"] == f"http://{_HOST}:{_PORT}"
        assert ctx["proxy"]["username"] == _USER
        assert ctx["proxy"]["password"] == _PASS

    def test_playwright_profile_a_no_context_proxy(self):
        """Non-Profile-D Playwright requests do not get a proxy context."""
        mw = _make_middleware()
        req = _make_request(profile="A", playwright=True)
        mw.process_request(req, _make_spider())

        ctx = req.meta.get("playwright_context_kwargs")
        if ctx is not None:
            assert "proxy" not in ctx

    def test_credentials_not_in_logs(self, caplog):
        """Password must not appear in any log output."""
        mw = _make_middleware()
        spider = _make_spider()
        spider.name = "grants"

        with caplog.at_level(logging.DEBUG, logger="grantglobe_crawler.middlewares.proxy"):
            mw.spider_opened(spider)
            req = _make_request(profile="D")
            mw.process_request(req, spider)

        full_log = "\n".join(r.getMessage() for r in caplog.records)
        assert _PASS not in full_log, f"Password '{_PASS}' must not appear in log output"
