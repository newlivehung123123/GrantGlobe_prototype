"""
GrantGlobeRobotsTxtMiddleware — robots.txt enforcement with per-domain override.

Spec §2.5 Layer 1 / spec §2.1 robots.txt policy.

Subclasses Scrapy's built-in ``RobotsTxtMiddleware`` to add one additional
capability: when a domain's ``crawl_manifest.json`` contains:

    "robots_override": true,
    "robots_override_justification": "<non-empty justification text>"

the robots.txt check is bypassed entirely for that domain.  All other domains
continue to go through the standard robots.txt enforcement path.

Rationale (spec §2.1)
----------------------
The manifest-based override exists to handle cases where a funder explicitly
grants crawl permission via email or a terms-of-service clause that supersedes
the robots.txt restrictions.  The mandatory justification text creates an
audit trail and prevents accidental overrides.

Priority: 100 (highest priority — runs first on request, last on response,
matching the priority originally allocated to Scrapy's own
``RobotsTxtMiddleware``).

Spec ref: §2.1 robots.txt policy, §2.5 Layer 1.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import urlparse

from scrapy import signals
from scrapy.downloadermiddlewares.robotstxt import RobotsTxtMiddleware

logger = logging.getLogger(__name__)


class GrantGlobeRobotsTxtMiddleware(RobotsTxtMiddleware):
    """
    Scrapy robots.txt middleware extended with per-domain manifest override.

    When ``crawl_manifest.json["robots_override"]`` is ``True`` **and**
    ``crawl_manifest.json["robots_override_justification"]`` is a non-empty
    string, the middleware skips the robots.txt check for that domain and logs
    a WARNING with the justification text to maintain an audit trail.

    All other behaviour (fetching, parsing, caching, async deferreds) is
    delegated to the parent ``RobotsTxtMiddleware`` unchanged.

    Spec ref: §2.1 robots.txt policy — "operators may set robots_override:
    true … justification must be recorded in manifest".
    """

    @classmethod
    def from_crawler(cls, crawler):
        # super().from_crawler() calls cls(crawler.settings) which creates
        # an instance of our subclass (cls = GrantGlobeRobotsTxtMiddleware).
        obj = super().from_crawler(crawler)
        obj._manifest_cache: dict[str, dict] = {}
        obj._crawl_state_dir = Path(
            crawler.settings.get(
                "CRAWL_STATE_DIR",
                crawler.settings.get("RAW_CACHE_DIR", "raw_cache"),
            )
        )
        crawler.signals.connect(obj.spider_opened, signal=signals.spider_opened)
        return obj

    def spider_opened(self, spider) -> None:
        logger.debug(
            "GrantGlobeRobotsTxtMiddleware enabled for spider '%s' — "
            "per-domain override supported via crawl_manifest.json",
            spider.name,
        )

    async def process_request(self, request, spider):
        """
        Check manifest for per-domain robots.txt override; delegate to parent
        for standard enforcement when no override is in effect.

        Spec ref: §2.1 robots.txt policy.
        """
        domain: str = request.meta.get("domain") or urlparse(request.url).netloc

        if not domain:
            # No domain context — fall through to parent for safety.
            return await super().process_request(request, spider)

        manifest = self._get_manifest(domain)
        justification: str = manifest.get("robots_override_justification") or ""

        if manifest.get("robots_override") is True and justification.strip():
            # spec §2.1 — bypass robots.txt check with audit-trail log.
            logger.warning(
                "[%s] robots.txt check BYPASSED — robots_override=true. "
                "Justification: %s",
                domain,
                justification,
            )
            return None  # Allow request; Scrapy interprets None as "proceed".

        # Standard enforcement: delegate to parent.
        return await super().process_request(request, spider)

    # ------------------------------------------------------------------
    # Manifest cache helper
    # ------------------------------------------------------------------

    def _get_manifest(self, domain: str) -> dict:
        """
        Load and cache the domain's ``crawl_manifest.json`` for this session.

        Returns an empty dict if the manifest is absent or unreadable so that
        callers can use ``.get()`` without guarding against None.

        Spec ref: §2.1 — "load crawl_manifest.json per domain".
        """
        if domain not in self._manifest_cache:
            manifest_path = self._crawl_state_dir / domain / "crawl_manifest.json"
            if manifest_path.exists():
                try:
                    with manifest_path.open(encoding="utf-8") as fh:
                        self._manifest_cache[domain] = json.load(fh)
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning(
                        "Could not load manifest for %s: %s — treating as no override",
                        domain,
                        exc,
                    )
                    self._manifest_cache[domain] = {}
            else:
                self._manifest_cache[domain] = {}
        return self._manifest_cache[domain]
