"""
ProxyRotationMiddleware — residential proxy injection for Profile D domains.

Spec §2.5 Layer 6 — Proxy configuration (~40 lines).

Profile D domains are classified during pre-flight as bot-protected
(Cloudflare, Sucuri, Akamai WAF, etc.) and cannot be crawled without a
residential proxy.  This middleware injects the proxy URL into every Profile D
request's meta dict so that Scrapy (and the Playwright browser context for
JS-rendered pages) routes the connection through the proxy pool.

Security notes
--------------
- Proxy credentials (PROXY_USERNAME / PROXY_PASSWORD) are loaded from .env
  and **never** written to log files — log statements deliberately omit them.
- The plain-text proxy URL (including credentials) is placed in
  ``request.meta["proxy"]``, which Scrapy handles internally and does not
  log unless the log level is set to DEBUG with ``LOG_LEVEL = "DEBUG"`` AND
  the HTTPCACHE middleware is also logging raw request metadata.  Operators
  should set ``LOG_LEVEL = "INFO"`` in production to avoid credential leaks.

Enabled/disabled
----------------
The pipeline entry is set to ``None`` (disabled) by default in settings.py
and must be explicitly enabled (assigned an integer priority) once a proxy
service is configured.  Spec §2.5 Layer 6 — "disabled until production".

Priority: 500 (lower priority than delay middleware at 400 so that proxy
injection happens after the delay has been observed, reducing the chance of
the proxy provider seeing burst patterns).

Spec ref: §2.5 Layer 6.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from scrapy import signals

logger = logging.getLogger(__name__)


class ProxyRotationMiddleware:
    """
    Injects a residential proxy URL into Profile D requests.

    All non-Profile-D requests pass through unchanged.  If proxy credentials
    are incomplete and a Profile D request arrives, a WARNING is logged once
    per spider session and the request proceeds without a proxy.

    Spec ref: §2.5 Layer 6 — "inject proxy only for Profile D".
    """

    def __init__(
        self,
        proxy_host: str | None,
        proxy_port: str | None,
        proxy_username: str | None,
        proxy_password: str | None,
        enabled: bool = False,
    ) -> None:
        self._enabled: bool = enabled
        self._proxy_host = proxy_host or ""
        self._proxy_port = proxy_port or ""
        self._proxy_username = proxy_username or ""
        self._proxy_password = proxy_password or ""
        self._credentials_complete: bool = all(
            [self._proxy_host, self._proxy_port, self._proxy_username, self._proxy_password]
        )
        self._missing_creds_warned: bool = False

    @classmethod
    def from_crawler(cls, crawler):
        s = crawler.settings
        obj = cls(
            proxy_host=s.get("PROXY_HOST"),
            proxy_port=s.get("PROXY_PORT"),
            proxy_username=s.get("PROXY_USERNAME"),
            proxy_password=s.get("PROXY_PASSWORD"),
            enabled=s.getbool("PROXY_ENABLED", False),
        )
        crawler.signals.connect(obj.spider_opened, signal=signals.spider_opened)
        return obj

    def spider_opened(self, spider) -> None:
        if self._credentials_complete:
            # Log proxy host only — never log username or password.
            logger.debug(
                "ProxyRotationMiddleware enabled for spider '%s' — proxy=%s:%s",
                spider.name,
                self._proxy_host,
                self._proxy_port,
            )
        else:
            logger.warning(
                "ProxyRotationMiddleware enabled but proxy credentials are incomplete. "
                "Profile D domains will not be proxied."
            )

    def process_request(self, request, spider) -> None:  # noqa: D401
        """
        Inject proxy into Profile D requests.

        Non-Profile-D requests are returned unchanged.
        If credentials are missing and the request is Profile D, log a WARNING
        once and proceed without a proxy.

        Spec ref: §2.5 Layer 6.
        """
        if not self._enabled:
            return None

        if request.meta.get("profile") != "D":
            return None

        if not self._credentials_complete:
            if not self._missing_creds_warned:
                logger.warning(
                    "Profile D request received but proxy credentials are not configured. "
                    "Set PROXY_HOST, PROXY_PORT, PROXY_USERNAME, PROXY_PASSWORD in .env. "
                    "Request will proceed WITHOUT a proxy: %s",
                    request.url,
                )
                self._missing_creds_warned = True
            return None

        # Construct proxy URL — credentials embedded; Scrapy handles auth.
        proxy_url = (
            f"http://{self._proxy_username}:{self._proxy_password}"
            f"@{self._proxy_host}:{self._proxy_port}"
        )
        request.meta["proxy"] = proxy_url

        # For Playwright Profile D, also configure the browser context proxy
        # so that the Chromium process routes through the same proxy.
        # spec §2.5 Layer 6 — "Playwright browser context must also use proxy".
        if request.meta.get("playwright") is True:
            ctx = request.meta.setdefault("playwright_context_kwargs", {})
            ctx["proxy"] = {
                "server": f"http://{self._proxy_host}:{self._proxy_port}",
                "username": self._proxy_username,
                "password": self._proxy_password,
            }
