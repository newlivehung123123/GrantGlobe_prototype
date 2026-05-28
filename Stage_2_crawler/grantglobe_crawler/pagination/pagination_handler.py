"""
PaginationHandler — five pagination-type detection and page-method builder.

Spec §2.3 — Pagination handling.

Five pagination types supported:
  Type 1 — URL-based: <a rel="next">, "Next" button text, URL param increment.
  Type 2 — Load more button: Playwright click + networkidle wait.
  Type 3 — Infinite scroll: Playwright scroll + networkidle wait.
  Type 4 — Tab / filter navigation: Playwright click + networkidle wait.
  Type 5 — XHR / API interception: Playwright route interception setup.

``PaginationHandler`` is a standalone class — not a Scrapy middleware or
pipeline.  It is instantiated once per spider (in ``from_crawler``) and called
from within ``parse()``.

scrapy-playwright dependency
----------------------------
Types 2–5 return lists of ``PageMethod`` objects.  If ``scrapy-playwright`` is
not installed, a lightweight stub class (``_PageMethodStub``) is used as a
drop-in replacement so that the handler remains importable and testable without
a Playwright installation.  The stub has the same ``method``, ``args``, and
``kwargs`` interface as the real ``PageMethod``.

Spec ref: §2.3 Pagination handling.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import (
    parse_qs,
    urlencode,
    urljoin,
    urlparse,
    urlunparse,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PageMethod — use the real class when available, otherwise a stub.
# ---------------------------------------------------------------------------

try:
    from scrapy_playwright.page import PageMethod as _PageMethod  # type: ignore[import]
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False

    class _PageMethod:  # type: ignore[no-redef]
        """
        Lightweight stub that mirrors the ``PageMethod`` interface used by
        scrapy-playwright.  Allows the pagination handler to produce
        page-method lists that are structurally correct even when
        scrapy-playwright is not installed (e.g. in the test environment).

        When scrapy-playwright IS installed this class is shadowed by the real
        ``PageMethod``; the stub is never used in production.
        """

        __slots__ = ("method", "args", "kwargs")

        def __init__(self, method: str, *args, **kwargs) -> None:
            self.method = method
            self.args = args
            self.kwargs = kwargs

        def __repr__(self) -> str:  # pragma: no cover
            kw = ", ".join(f"{k}={v!r}" for k, v in self.kwargs.items())
            args_str = ", ".join(repr(a) for a in self.args)
            all_args = ", ".join(filter(None, [args_str, kw]))
            return f"PageMethod({self.method!r}, {all_args})"

        def __eq__(self, other) -> bool:
            if not isinstance(other, _PageMethod):
                return NotImplemented
            return (
                self.method == other.method
                and self.args == other.args
                and self.kwargs == other.kwargs
            )


# ---------------------------------------------------------------------------
# Pattern lists
# ---------------------------------------------------------------------------

_NEXT_PAGE_PATTERNS: tuple[str, ...] = ("next page", "next", "›", "»", ">", "→")
# Sorted longest-first so "next page" is matched before "next".
_NEXT_PAGE_PATTERNS = tuple(
    sorted(_NEXT_PAGE_PATTERNS, key=len, reverse=True)
)

_LOAD_MORE_PATTERNS: tuple[str, ...] = (
    "load more",
    "show more",
    "view more",
    "load results",
    "more results",
    "more grants",
)

# Query-string params that carry page/offset information.
_PAGE_PARAMS: tuple[str, ...] = ("page", "p", "pg")   # increment by 1
_OFFSET_PARAMS: tuple[str, ...] = ("offset", "start")  # infer step from siblings


# ---------------------------------------------------------------------------
# PaginationHandler
# ---------------------------------------------------------------------------


class PaginationHandler:
    """
    Detect pagination signals in HTTP responses and produce either next-page
    URLs (Type 1) or lists of Playwright ``PageMethod`` objects (Types 2–5).

    Parameters
    ----------
    settings:
        Scrapy settings object **or** dict-like.  Used to read
        ``PAGINATION_LOAD_MORE_MAX_CLICKS``,
        ``PAGINATION_INFINITE_SCROLL_MAX_ITERATIONS``, and
        ``PAGINATION_NETWORKIDLE_TIMEOUT_MS``.
    """

    def __init__(self, settings) -> None:
        self._max_clicks: int = int(
            settings.get("PAGINATION_LOAD_MORE_MAX_CLICKS", 20)
        )
        self._max_scroll_iters: int = int(
            settings.get("PAGINATION_INFINITE_SCROLL_MAX_ITERATIONS", 30)
        )
        self._networkidle_timeout_ms: int = int(
            settings.get("PAGINATION_NETWORKIDLE_TIMEOUT_MS", 20_000)
        )

    # ------------------------------------------------------------------
    # TYPE 1 — URL-based pagination
    # ------------------------------------------------------------------

    def extract_next_url(self, response) -> str | None:
        """
        Return the canonicalised next-page URL using a three-strategy cascade.

        Strategy 1 — rel="next"
            Look for ``<a rel="next">`` or ``<link rel="next">``; this is the
            canonical pagination signal used by WordPress, Drupal, and most
            grant-portal themes.

        Strategy 2 — "Next" button text
            Look for ``<a>`` tags whose visible text matches
            ``["next page", "next", "›", "»", ">", "→"]``
            (case-insensitive; whitespace stripped; checked longest-first so
            "next page" is not shadowed by "next").

        Strategy 3 — Pagination query-parameter increment
            If the current URL contains a recognised pagination parameter
            (``page``, ``p``, ``pg``, ``offset``, ``start``), increment it
            and return the new URL.  For ``offset``/``start``, the step size
            is inferred from sibling pagination links on the page (see
            ``_infer_offset_step``); for ``page``/``p``/``pg`` the step is
            always 1.

        Returns
        -------
        str | None
            Canonicalised next-page URL, or ``None`` if no signal found.

        Notes
        -----
        The caller (spider) is responsible for checking ``seen_urls`` before
        enqueuing the returned URL.

        Spec ref: §2.3 Type 1.
        """
        from grantglobe_crawler.utils.url_canonicaliser import canonicalise

        # ── Strategy 1: rel="next" ─────────────────────────────────────
        for selector in ('a[rel="next"]::attr(href)', 'link[rel="next"]::attr(href)'):
            href = response.css(selector).get()
            if href:
                abs_url = urljoin(response.url, href.strip())
                return canonicalise(abs_url)

        # ── Strategy 2: "Next" button/link text ──────────────────────
        # Iterate each <a> element individually so that the href and combined
        # text are always from the same element.  Using zip(a::attr(href),
        # a::text) is unsafe: `a::text` returns only *direct* text children,
        # skipping <a> tags that contain child elements (span, strong, etc.),
        # so the zip misaligns hrefs with text from different elements.
        for a_el in response.css("a"):
            combined = "".join(a_el.css("*::text").getall()).strip().lower()
            href = a_el.attrib.get("href", "")
            if not href or href.startswith(("mailto:", "tel:", "javascript:")):
                continue
            for pattern in _NEXT_PAGE_PATTERNS:
                if combined == pattern:
                    abs_url = urljoin(response.url, href.strip())
                    return canonicalise(abs_url)

        # ── Strategy 3: pagination query-parameter increment ──────────
        parsed = urlparse(response.url)
        params = parse_qs(parsed.query, keep_blank_values=True)

        for param in _PAGE_PARAMS:
            if param in params:
                try:
                    current = int(params[param][0])
                except (ValueError, IndexError):
                    continue
                next_url = _build_url_with_param(response.url, param, current + 1)
                return canonicalise(next_url)

        for param in _OFFSET_PARAMS:
            if param in params:
                try:
                    current = int(params[param][0])
                except (ValueError, IndexError):
                    continue
                step = self._infer_offset_step(response, param, current)
                next_url = _build_url_with_param(response.url, param, current + step)
                return canonicalise(next_url)

        return None

    def _infer_offset_step(self, response, param: str, current_value: int) -> int:
        """
        Infer the pagination step for ``offset``/``start`` parameters by
        inspecting sibling pagination links on the page.

        Collects all numeric values of *param* seen in ``<a href>`` tags,
        sorts them, and returns the minimum positive difference between
        adjacent values (the page size).

        Falls back to ``current_value`` (correct for page 2 where
        offset == page_size) or ``20`` if ``current_value == 0``.

        Spec ref: §2.3 Type 1 — "infer step from sibling links".
        """
        values: set[int] = {current_value}

        for href in response.css("a::attr(href)").getall():
            try:
                abs_href = urljoin(response.url, href)
                q = parse_qs(urlparse(abs_href).query)
                if param in q:
                    values.add(int(q[param][0]))
            except (ValueError, IndexError):
                continue

        sorted_vals = sorted(values)
        if len(sorted_vals) >= 2:
            diffs = [
                sorted_vals[i + 1] - sorted_vals[i]
                for i in range(len(sorted_vals) - 1)
                if sorted_vals[i + 1] > sorted_vals[i]
            ]
            if diffs:
                return min(diffs)

        # Fallback: on page 2, offset == step (offset = 1 * page_size).
        return current_value if current_value > 0 else 20

    # ------------------------------------------------------------------
    # TYPE 2 — Button / JS "Load more"
    # ------------------------------------------------------------------

    def get_load_more_page_methods(self, response) -> list | None:
        """
        Detect a "Load more" button and return Playwright ``PageMethod``
        objects to click it, or ``None`` if no matching element is found.

        Detection scans ``<button>`` and ``<a>`` elements for text that
        contains any string in ``load_more_patterns`` (case-insensitive
        partial match):
        ``["load more", "show more", "view more", "load results",
          "more results", "more grants"]``.

        Returns
        -------
        list | None
            ``[PageMethod("click", selector),
               PageMethod("wait_for_load_state", "networkidle",
                          timeout=PAGINATION_NETWORKIDLE_TIMEOUT_MS)]``
            where *selector* is the CSS selector for the first matching
            element, or ``None`` if no element matched.

        Spec ref: §2.3 Type 2.
        """
        for tag in ("button", "a"):
            for el in response.css(tag):
                text = "".join(el.css("*::text").getall()).strip().lower()
                for pattern in _LOAD_MORE_PATTERNS:
                    if pattern in text:
                        # Build a CSS selector that identifies this element.
                        el_id = el.attrib.get("id")
                        el_class = el.attrib.get("class", "").split()
                        if el_id:
                            selector = f"{tag}#{el_id}"
                        elif el_class:
                            selector = f"{tag}.{'.'.join(el_class[:2])}"
                        else:
                            selector = tag
                        return [
                            _PageMethod("click", selector),
                            _PageMethod(
                                "wait_for_load_state",
                                "networkidle",
                                timeout=self._networkidle_timeout_ms,
                            ),
                        ]
        return None

    # ------------------------------------------------------------------
    # TYPE 3 — Infinite scroll
    # ------------------------------------------------------------------

    def get_infinite_scroll_page_methods(self) -> list:
        """
        Return ``PageMethod`` objects that scroll to the bottom and wait for
        new content to load.

        The third item evaluates ``document.body.scrollHeight`` after the
        networkidle wait; the spider compares this value against the previous
        ``scrollHeight`` to detect when the page is fully loaded (no new
        content added) and stops scrolling when they are equal.

        Returns
        -------
        list
            ``[PageMethod("evaluate", "window.scrollTo(0, document.body.scrollHeight)"),
               PageMethod("wait_for_load_state", "networkidle",
                          timeout=PAGINATION_NETWORKIDLE_TIMEOUT_MS),
               PageMethod("evaluate", "document.body.scrollHeight")]``

        Spec ref: §2.3 Type 3.
        """
        return [
            _PageMethod(
                "evaluate",
                "window.scrollTo(0, document.body.scrollHeight)",
            ),
            _PageMethod(
                "wait_for_load_state",
                "networkidle",
                timeout=self._networkidle_timeout_ms,
            ),
            _PageMethod(
                "evaluate",
                "document.body.scrollHeight",
            ),
        ]

    # ------------------------------------------------------------------
    # TYPE 4 — Tab / filter navigation
    # ------------------------------------------------------------------

    def get_tab_page_methods(self, tab_selector: str) -> list:
        """
        Return ``PageMethod`` objects to click a tab or filter element and
        wait for the content pane to update.

        Parameters
        ----------
        tab_selector:
            CSS selector for the tab element, as recorded in the domain's
            ``crawl_manifest.json["tab_filter"]`` list.

        Returns
        -------
        list
            ``[PageMethod("click", tab_selector),
               PageMethod("wait_for_load_state", "networkidle",
                          timeout=PAGINATION_NETWORKIDLE_TIMEOUT_MS)]``

        Spec ref: §2.3 Type 4.
        """
        return [
            _PageMethod("click", tab_selector),
            _PageMethod(
                "wait_for_load_state",
                "networkidle",
                timeout=self._networkidle_timeout_ms,
            ),
        ]

    # ------------------------------------------------------------------
    # TYPE 5 — XHR / API interception
    # ------------------------------------------------------------------

    def get_xhr_intercept_page_methods(self, api_pattern: str) -> list:
        """
        Return ``PageMethod`` objects to set up Playwright route interception
        for XHR/fetch requests matching *api_pattern*.

        .. important::

            **This method only sets up the route intercept.**  It does NOT
            capture the response body automatically.  The spider must also
            register a ``page.on("response", handler)`` event listener (via
            an additional ``PageMethod("on", "response", handler)`` object or
            by using a Playwright page context manager) to actually read the
            response payload.  Without the listener, the route passthrough is
            established but the JSON data is not captured.

        Parameters
        ----------
        api_pattern:
            URL substring or Playwright glob pattern matching the XHR/fetch
            endpoint to intercept (e.g. ``"**/api/grants*"``).

        Returns
        -------
        list
            ``[PageMethod("route", api_pattern,
                          handler=lambda route, request: route.continue_())]``

        Spec ref: §2.3 Type 5.
        """
        return [
            _PageMethod(
                "route",
                api_pattern,
                handler=lambda route, request: route.continue_(),
            ),
        ]


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _build_url_with_param(base_url: str, param: str, value: int) -> str:
    """
    Return *base_url* with the query parameter *param* set to *value*.

    All other query parameters are preserved unchanged.  The fragment is
    stripped (handled by canonicalise() in the caller).
    """
    parsed = urlparse(base_url)
    # parse_qs returns lists; rebuild as single-value dict for urlencode.
    params = {k: v[0] for k, v in parse_qs(parsed.query, keep_blank_values=True).items()}
    params[param] = str(value)
    new_query = urlencode(params)
    return urlunparse(parsed._replace(query=new_query, fragment=""))
