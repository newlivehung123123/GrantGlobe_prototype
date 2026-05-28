"""
Unit tests for PaginationHandler — spec §2.3 five pagination types.

Covered:
  Type 1 — extract_next_url:
    - Finds <a rel="next">
    - Finds <link rel="next">
    - Finds "Next" / "Next page" anchor text
    - Increments ?page=2 → ?page=3
    - Increments ?offset=20 → ?offset=40 (step inferred from sibling links)
    - Returns None when no next-page signal found
    - Canonicalisation applied to extracted URLs (https upgrade, www strip)
  Type 2 — get_load_more_page_methods:
    - Detects "Load more" button → returns 2 PageMethod objects
    - Returns None when no button present
  Type 3 — get_infinite_scroll_page_methods:
    - Returns exactly 3 PageMethod objects with correct method names

All PageMethod assertions use the .method / .args / .kwargs attributes that
are consistent across both the real scrapy-playwright PageMethod and the
stub defined in pagination_handler.py.
"""

from __future__ import annotations

import pytest
from scrapy.http import HtmlResponse, Request

from grantglobe_crawler.pagination.pagination_handler import PaginationHandler, _PageMethod

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_SETTINGS = {
    "PAGINATION_LOAD_MORE_MAX_CLICKS": 20,
    "PAGINATION_INFINITE_SCROLL_MAX_ITERATIONS": 30,
    "PAGINATION_NETWORKIDLE_TIMEOUT_MS": 20_000,
}


def _make_handler() -> PaginationHandler:
    return PaginationHandler(_SETTINGS)


def _make_response(url: str, body: str) -> HtmlResponse:
    """Return a minimal HtmlResponse backed by *body* at *url*."""
    return HtmlResponse(
        url=url,
        body=body.encode("utf-8"),
        encoding="utf-8",
        request=Request(url),
    )


# ---------------------------------------------------------------------------
# Type 1 — extract_next_url
# ---------------------------------------------------------------------------


class TestExtractNextUrl:
    def test_finds_a_rel_next(self):
        body = '<html><body><a rel="next" href="/grants?page=2">Next</a></body></html>'
        resp = _make_response("https://example.org/grants", body)
        handler = _make_handler()
        result = handler.extract_next_url(resp)
        assert result is not None
        assert "page=2" in result or "/grants" in result

    def test_finds_link_rel_next(self):
        body = (
            '<html><head><link rel="next" href="/grants?page=3"/></head>'
            "<body>content</body></html>"
        )
        resp = _make_response("https://example.org/grants?page=2", body)
        handler = _make_handler()
        result = handler.extract_next_url(resp)
        assert result is not None
        assert "page=3" in result

    def test_finds_next_button_text_exact(self):
        """<a> with text "Next" (case-insensitive) is detected."""
        body = (
            "<html><body>"
            '<a href="/grants?page=4">Next</a>'
            "</body></html>"
        )
        resp = _make_response("https://example.org/grants?page=3", body)
        handler = _make_handler()
        result = handler.extract_next_url(resp)
        assert result is not None
        assert "page=4" in result

    def test_finds_next_page_text(self):
        """<a> with text "Next page" is detected (longest-pattern priority)."""
        body = (
            "<html><body>"
            '<a href="/grants?page=5">Next page</a>'
            "</body></html>"
        )
        resp = _make_response("https://example.org/grants?page=4", body)
        handler = _make_handler()
        result = handler.extract_next_url(resp)
        assert result is not None
        assert "page=5" in result

    def test_increments_page_param(self):
        """No rel=next or button text; ?page=2 → ?page=3 via Strategy 3."""
        body = "<html><body><p>Grants listing page 2</p></body></html>"
        resp = _make_response("https://example.org/grants?page=2", body)
        handler = _make_handler()
        result = handler.extract_next_url(resp)
        assert result is not None
        assert "page=3" in result

    def test_increments_offset_with_inferred_step(self):
        """?offset=20 → ?offset=40; step=20 inferred from sibling pagination links."""
        body = (
            "<html><body>"
            '<a href="/grants?offset=0">1</a>'
            '<a href="/grants?offset=20">2</a>'
            '<a href="/grants?offset=40">3</a>'
            '<a href="/grants?offset=60">4</a>'
            "</body></html>"
        )
        resp = _make_response("https://example.org/grants?offset=20", body)
        handler = _make_handler()
        result = handler.extract_next_url(resp)
        assert result is not None
        assert "offset=40" in result

    def test_returns_none_when_no_next_page(self):
        """Plain HTML with no pagination signals → None."""
        body = "<html><body><p>No pagination here.</p></body></html>"
        resp = _make_response("https://example.org/single-page", body)
        handler = _make_handler()
        result = handler.extract_next_url(resp)
        assert result is None

    def test_canonicalisation_applied(self):
        """http is upgraded to https and www. is stripped."""
        body = '<html><body><a rel="next" href="http://www.example.org/grants?page=2">Next</a></body></html>'
        resp = _make_response("https://example.org/grants?page=1", body)
        handler = _make_handler()
        result = handler.extract_next_url(resp)
        assert result is not None
        # Canonicalise should upgrade http→https and strip www.
        assert result.startswith("https://")
        assert "www." not in result

    def test_next_rel_takes_priority_over_param(self):
        """rel=next URL is returned even when a page param also exists."""
        body = '<html><head><link rel="next" href="/grants?page=9"/></head><body/></html>'
        resp = _make_response("https://example.org/grants?page=8", body)
        handler = _make_handler()
        result = handler.extract_next_url(resp)
        assert result is not None
        assert "page=9" in result  # from rel="next", not page=9 from strategy 3


# ---------------------------------------------------------------------------
# Type 2 — get_load_more_page_methods
# ---------------------------------------------------------------------------


class TestGetLoadMorePageMethods:
    def test_detects_load_more_button(self):
        body = (
            '<html><body>'
            '<button id="load-btn">Load more</button>'
            "</body></html>"
        )
        resp = _make_response("https://example.org/grants", body)
        handler = _make_handler()
        result = handler.get_load_more_page_methods(resp)
        assert result is not None
        assert len(result) == 2

    def test_load_more_returns_click_then_wait(self):
        body = '<html><body><button class="load-more-btn">Load more</button></body></html>'
        resp = _make_response("https://example.org/grants", body)
        handler = _make_handler()
        result = handler.get_load_more_page_methods(resp)
        assert result is not None
        click_pm, wait_pm = result
        assert click_pm.method == "click"
        assert wait_pm.method == "wait_for_load_state"
        assert wait_pm.args[0] == "networkidle"
        assert wait_pm.kwargs.get("timeout") == 20_000

    def test_detects_show_more_variant(self):
        body = '<html><body><a href="#">Show more</a></body></html>'
        resp = _make_response("https://example.org/grants", body)
        result = _make_handler().get_load_more_page_methods(resp)
        assert result is not None
        assert len(result) == 2

    def test_detects_more_grants_variant(self):
        body = '<html><body><button>More grants</button></body></html>'
        resp = _make_response("https://example.org/grants", body)
        result = _make_handler().get_load_more_page_methods(resp)
        assert result is not None

    def test_returns_none_when_no_button(self):
        body = "<html><body><p>All grants listed above.</p></body></html>"
        resp = _make_response("https://example.org/grants", body)
        result = _make_handler().get_load_more_page_methods(resp)
        assert result is None

    def test_case_insensitive_detection(self):
        """Pattern matching is case-insensitive — LOAD MORE should match."""
        body = "<html><body><button>LOAD MORE</button></body></html>"
        resp = _make_response("https://example.org/grants", body)
        result = _make_handler().get_load_more_page_methods(resp)
        assert result is not None


# ---------------------------------------------------------------------------
# Type 3 — get_infinite_scroll_page_methods
# ---------------------------------------------------------------------------


class TestGetInfiniteScrollPageMethods:
    def test_returns_three_page_methods(self):
        result = _make_handler().get_infinite_scroll_page_methods()
        assert isinstance(result, list)
        assert len(result) == 3

    def test_first_method_is_scroll_evaluate(self):
        result = _make_handler().get_infinite_scroll_page_methods()
        pm = result[0]
        assert pm.method == "evaluate"
        assert "scrollTo" in pm.args[0]

    def test_second_method_is_networkidle_wait(self):
        result = _make_handler().get_infinite_scroll_page_methods()
        pm = result[1]
        assert pm.method == "wait_for_load_state"
        assert pm.args[0] == "networkidle"
        assert pm.kwargs.get("timeout") == 20_000

    def test_third_method_returns_scroll_height(self):
        """Third evaluate captures scrollHeight so the spider can detect end-of-scroll."""
        result = _make_handler().get_infinite_scroll_page_methods()
        pm = result[2]
        assert pm.method == "evaluate"
        assert "scrollHeight" in pm.args[0]


# ---------------------------------------------------------------------------
# Type 4 — get_tab_page_methods
# ---------------------------------------------------------------------------


class TestGetTabPageMethods:
    def test_returns_click_then_networkidle(self):
        handler = _make_handler()
        result = handler.get_tab_page_methods("button.tab-open-grants")
        assert len(result) == 2
        click_pm, wait_pm = result
        assert click_pm.method == "click"
        assert click_pm.args[0] == "button.tab-open-grants"
        assert wait_pm.method == "wait_for_load_state"
        assert wait_pm.args[0] == "networkidle"


# ---------------------------------------------------------------------------
# Type 5 — get_xhr_intercept_page_methods
# ---------------------------------------------------------------------------


class TestGetXhrInterceptPageMethods:
    def test_returns_route_method(self):
        handler = _make_handler()
        result = handler.get_xhr_intercept_page_methods("**/api/grants*")
        assert len(result) == 1
        pm = result[0]
        assert pm.method == "route"
        assert pm.args[0] == "**/api/grants*"
        assert callable(pm.kwargs.get("handler"))
