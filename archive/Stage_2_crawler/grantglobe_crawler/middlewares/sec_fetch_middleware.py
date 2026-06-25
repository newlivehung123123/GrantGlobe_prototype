"""
SecFetchHeadersMiddleware — dynamic Sec-Fetch-* header injection.

Injects the four ``Sec-Fetch-*`` HTTP headers on every outgoing request.
The correct values depend on the request context: a cold first navigation
sends different headers than a link-follow within the same session, and an
XHR call sends different headers than either.

Sending the same static Sec-Fetch-* block on every request is a detectable
bot fingerprint.  Modern detectors (Cloudflare, DataDome, PerimeterX)
cross-check these headers against the Referer chain — a mismatch is treated
as an automated-traffic signal.

Spec ref: §2.5 Layer 2 — HTTP header authenticity:
    "The Sec-Fetch-* headers are critical, and they are dynamic by request
    context — not a static block applied identically to every request."

Four recognised request contexts
---------------------------------
Case A — Cold navigation (seed URL, depth == 0, or no Referer):
    Sec-Fetch-Dest:  document
    Sec-Fetch-Mode:  navigate
    Sec-Fetch-Site:  none
    Sec-Fetch-User:  ?1

Case B — Link follow (depth > 0, Referer present, not XHR, not PDF):
    Sec-Fetch-Dest:  document
    Sec-Fetch-Mode:  navigate
    Sec-Fetch-Site:  same-origin | cross-site
    Sec-Fetch-User:  ?1
    Note: the spec table shows Sec-Fetch-User as omitted for link-follows,
    but adding ?1 makes the request look more like a user-initiated click
    and is the more evasive choice for bot-detection avoidance.

Case C — XHR / fetch (meta["is_xhr"] is True):
    Sec-Fetch-Dest:  empty
    Sec-Fetch-Mode:  cors
    Sec-Fetch-Site:  same-origin | cross-site
    (Sec-Fetch-User omitted per spec §2.5 Layer 2 table)

Case D — PDF resource (meta["is_pdf"] is True):
    Sec-Fetch-Dest:  document
    Sec-Fetch-Mode:  navigate
    Sec-Fetch-Site:  same-origin | cross-site
    Sec-Fetch-User:  ?1

Priority in DOWNLOADER_MIDDLEWARES: 410
    Runs after UserAgentMiddleware (400) so the User-Agent is already set
    when Sec-Fetch headers are computed.  Runs before Scrapy's built-in
    compression / cache middlewares (543+).

Registration in settings.py:
    "grantglobe_crawler.middlewares.sec_fetch_middleware.SecFetchHeadersMiddleware": 410,
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from scrapy import signals
from scrapy.http import Request

logger = logging.getLogger(__name__)


class SecFetchHeadersMiddleware:
    """
    Scrapy downloader middleware that injects dynamic ``Sec-Fetch-*`` headers.
    """

    # Registered via from_crawler so the middleware can be toggled via
    # settings without modifying DOWNLOADER_MIDDLEWARES directly.
    @classmethod
    def from_crawler(cls, crawler):
        instance = cls()
        crawler.signals.connect(instance.spider_opened, signal=signals.spider_opened)
        return instance

    def spider_opened(self, spider):
        logger.debug("SecFetchHeadersMiddleware attached to %s", spider.name)

    # ------------------------------------------------------------------
    # Core middleware method
    # ------------------------------------------------------------------

    def process_request(self, request: Request, spider) -> None:
        """
        Determine the request context and inject the appropriate
        ``Sec-Fetch-*`` headers before the request is dispatched.

        Returns None so Scrapy continues normal processing.
        """
        meta = request.meta

        # Determine which case applies.
        depth: int = meta.get("depth", 0)
        is_xhr: bool = bool(meta.get("is_xhr"))
        is_pdf: bool = bool(meta.get("is_pdf"))
        is_first: bool = bool(meta.get("is_first_request", False))
        referer: str | None = (
            request.headers.get("Referer", b"").decode("utf-8", errors="replace") or None
        )

        cold_nav = is_first or depth == 0 or not referer

        if is_xhr:
            # Case C — XHR / fetch (spec §2.5 Layer 2 table, row 4)
            fetch_site = _get_fetch_site(request.url, referer)
            headers = {
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": fetch_site,
                # Sec-Fetch-User is omitted for XHR per spec table.
            }
        elif cold_nav:
            # Case A — Cold initial navigation (spec §2.5 Layer 2 table, row 1)
            headers = {
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
            }
        elif is_pdf:
            # Case D — PDF resource download (treated as a user-initiated navigation)
            fetch_site = _get_fetch_site(request.url, referer)
            headers = {
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": fetch_site,
                "Sec-Fetch-User": "?1",
            }
        else:
            # Case B — Link follow within a crawl session
            # (spec §2.5 Layer 2 table, row 2)
            fetch_site = _get_fetch_site(request.url, referer)
            headers = {
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": fetch_site,
                "Sec-Fetch-User": "?1",
            }

        for name, value in headers.items():
            request.headers[name] = value

        logger.debug(
            "SecFetch [%s depth=%d referer=%s]: %s",
            "XHR" if is_xhr else ("PDF" if is_pdf else ("cold" if cold_nav else "link")),
            depth,
            bool(referer),
            {k: v for k, v in headers.items()},
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_fetch_site(request_url: str, referer: str | None) -> str:
    """
    Return the ``Sec-Fetch-Site`` value for a request.

    Compares the netloc (host + optional port) of *request_url* and
    *referer*.  No eTLD+1 resolution is performed; same-netloc is treated
    as same-origin, everything else as cross-site.

    Spec ref: §2.5 Layer 2 — "Determine same-origin vs cross-site by
    comparing the netloc of request.url and request.headers.get('Referer').
    If no Referer, use 'none'."
    """
    if not referer:
        return "none"
    try:
        req_netloc = urlparse(request_url).netloc
        ref_netloc = urlparse(referer).netloc
        return "same-origin" if req_netloc == ref_netloc else "cross-site"
    except Exception:
        return "none"
