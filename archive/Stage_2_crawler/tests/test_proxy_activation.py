"""
Tests for the PROXY_ENABLED gate in ProxyRotationMiddleware.

Verifies that:
  - PROXY_ENABLED=False → process_request is a no-op regardless of profile.
  - PROXY_ENABLED=True, Profile D → proxy meta is injected (existing behaviour).
  - PROXY_ENABLED=True, Profile A → proxy not injected (existing behaviour).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from scrapy.http import Request

from grantglobe_crawler.middlewares.proxy import ProxyRotationMiddleware

_HOST = "proxy.example.com"
_PORT = "8080"
_USER = "myuser"
_PASS = "s3cr3t"


def _make_middleware(*, enabled: bool, host=_HOST, port=_PORT, user=_USER, password=_PASS):
    return ProxyRotationMiddleware(
        proxy_host=host,
        proxy_port=port,
        proxy_username=user,
        proxy_password=password,
        enabled=enabled,
    )


def _make_request(profile: str = "D", **extra_meta) -> Request:
    meta = {"domain": "example.org", "profile": profile} | extra_meta
    return Request("https://example.org/page", meta=meta)


def _spider():
    s = MagicMock()
    s.name = "grants"
    return s


# ---------------------------------------------------------------------------
# Test 1 — PROXY_ENABLED=False → immediate no-op
# ---------------------------------------------------------------------------


class TestProxyDisabled:
    def test_process_request_returns_none_when_disabled(self):
        """PROXY_ENABLED=False: process_request returns None for Profile D."""
        mw = _make_middleware(enabled=False)
        req = _make_request(profile="D")
        result = mw.process_request(req, _spider())
        assert result is None

    def test_no_proxy_meta_set_when_disabled(self):
        """PROXY_ENABLED=False: proxy key must not appear in request.meta."""
        mw = _make_middleware(enabled=False)
        req = _make_request(profile="D")
        mw.process_request(req, _spider())
        assert "proxy" not in req.meta

    def test_no_playwright_proxy_when_disabled(self):
        """PROXY_ENABLED=False: Playwright Profile D also gets no proxy context."""
        mw = _make_middleware(enabled=False)
        req = _make_request(profile="D", playwright=True)
        mw.process_request(req, _spider())
        ctx = req.meta.get("playwright_context_kwargs", {})
        assert "proxy" not in ctx


# ---------------------------------------------------------------------------
# Test 2 — PROXY_ENABLED=True, Profile D → proxy injected
# ---------------------------------------------------------------------------


class TestProxyEnabledProfileD:
    def test_proxy_meta_set_for_profile_d(self):
        """PROXY_ENABLED=True + Profile D → request.meta['proxy'] is set."""
        mw = _make_middleware(enabled=True)
        req = _make_request(profile="D")
        mw.process_request(req, _spider())
        assert "proxy" in req.meta
        assert req.meta["proxy"] == f"http://{_USER}:{_PASS}@{_HOST}:{_PORT}"

    def test_playwright_proxy_context_set_for_profile_d(self):
        """PROXY_ENABLED=True, Playwright Profile D → context proxy is set."""
        mw = _make_middleware(enabled=True)
        req = _make_request(profile="D", playwright=True)
        mw.process_request(req, _spider())
        ctx = req.meta.get("playwright_context_kwargs", {})
        assert "proxy" in ctx
        assert ctx["proxy"]["server"] == f"http://{_HOST}:{_PORT}"
        assert ctx["proxy"]["username"] == _USER
        assert ctx["proxy"]["password"] == _PASS


# ---------------------------------------------------------------------------
# Test 3 — PROXY_ENABLED=True, Profile A → proxy not injected
# ---------------------------------------------------------------------------


class TestProxyEnabledProfileA:
    def test_no_proxy_for_profile_a_when_enabled(self):
        """PROXY_ENABLED=True but Profile A/B/C → proxy must not be injected."""
        mw = _make_middleware(enabled=True)
        for profile in ("A", "B", "C"):
            req = _make_request(profile=profile)
            mw.process_request(req, _spider())
            assert "proxy" not in req.meta, (
                f"Profile {profile} must not receive a proxy even when PROXY_ENABLED=True"
            )

    def test_no_playwright_proxy_for_non_d_profiles(self):
        """Playwright non-Profile-D requests must not get a proxy context."""
        mw = _make_middleware(enabled=True)
        req = _make_request(profile="A", playwright=True)
        mw.process_request(req, _spider())
        ctx = req.meta.get("playwright_context_kwargs", {})
        assert "proxy" not in ctx
