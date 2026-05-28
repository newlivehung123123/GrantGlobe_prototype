"""
UserAgentMiddleware — per-domain session-stable User-Agent assignment.

Spec §2.5 Layer 2 — UA pool.

Design notes
------------
- One UA is randomly selected from USERAGENT_POOL on the **first** request
  for a domain and then held constant for the entire spider session.
- Rotating mid-session (different UA per request to the same domain) is a
  well-known bot-detection signal on session-aware sites — the spec explicitly
  forbids it.
- For Profile B Playwright requests the same UA is injected into
  ``request.meta["playwright_context_kwargs"]["user_agent"]`` so that
  the Chromium browser launched by playwright matches the HTTP-layer UA.
- Priority: 300 (after robots.txt at 100, before delay middleware at 400).

Spec ref: §2.5 Layer 2 — "Select UA from pool once per domain per session".
"""

from __future__ import annotations

import logging
import random
from urllib.parse import urlparse

from scrapy import signals
from scrapy.exceptions import NotConfigured

logger = logging.getLogger(__name__)


class UserAgentMiddleware:
    """
    Assigns one User-Agent string from ``settings.USERAGENT_POOL`` to each
    domain at the start of that domain's crawl.  The same UA is re-used on
    every subsequent request to that domain within the spider session.

    Spec ref: §2.5 Layer 2 — UA pool.
    """

    def __init__(self, ua_pool: list[str]) -> None:
        if not ua_pool:
            raise NotConfigured("USERAGENT_POOL is empty — cannot assign UAs.")
        self._ua_pool = ua_pool
        # Maps netloc → assigned UA string for this spider session.
        self._domain_ua: dict[str, str] = {}

    @classmethod
    def from_crawler(cls, crawler):
        ua_pool = crawler.settings.getlist("USERAGENT_POOL", [])
        obj = cls(ua_pool)
        crawler.signals.connect(obj.spider_opened, signal=signals.spider_opened)
        return obj

    def spider_opened(self, spider) -> None:
        logger.debug(
            "UserAgentMiddleware enabled for spider '%s' — pool size=%d",
            spider.name,
            len(self._ua_pool),
        )

    def process_request(self, request, spider) -> None:  # noqa: D401
        """
        Inject the domain's assigned UA into the request headers.

        Domain is taken from ``request.meta["domain"]`` (set by the spider's
        ``start_requests``); falls back to the URL netloc for requests that
        bypass the spider's meta injection (e.g. robots.txt fetches).

        Spec ref: §2.5 Layer 2.
        """
        domain: str = request.meta.get("domain") or urlparse(request.url).netloc

        # Lazy assignment: first request for the domain picks a random UA.
        if domain not in self._domain_ua:
            self._domain_ua[domain] = random.choice(self._ua_pool)

        assigned_ua: str = self._domain_ua[domain]

        # Set the HTTP-layer User-Agent header.
        request.headers["User-Agent"] = assigned_ua

        # For Profile B Playwright requests, also set the browser context UA
        # so the browser fingerprint matches the HTTP-layer identity.
        # spec §2.5 Layer 2 — "Playwright context UA must match HTTP UA".
        if request.meta.get("playwright") is True:
            ctx = request.meta.get("playwright_context_kwargs")
            if isinstance(ctx, dict):
                # Preserve any existing keys (e.g. viewport, locale).
                ctx.setdefault("user_agent", assigned_ua)
            else:
                request.meta["playwright_context_kwargs"] = {"user_agent": assigned_ua}
