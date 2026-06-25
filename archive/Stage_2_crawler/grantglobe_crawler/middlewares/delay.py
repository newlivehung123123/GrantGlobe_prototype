"""
BehaviouralDelayMiddleware — Gaussian inter-request delay with reading pauses.

Spec §2.5 Layer 3 — Behavioural humanisation.

Design notes
------------
- The delay is drawn from a Gaussian distribution (mean DELAY_MEAN, SD
  DELAY_SD) clipped to [DELAY_MIN, DELAY_MAX], then floored by the per-domain
  ``rate_limit_floor_seconds`` recorded in the domain's crawl manifest
  (e.g. from ``Crawl-delay`` in robots.txt).
- With probability EXTENDED_PAUSE_PROBABILITY an additional 15–45 s pause is
  appended to simulate a human reading an opportunity page before navigating
  to the next link.
- ``random.gauss()`` is used for the main delay — never ``random.uniform()``
  (which would produce a rectangular distribution easily fingerprinted by
  traffic-analysis bots).
- The sleep is applied synchronously in ``process_request`` rather than as a
  Deferred/coroutine so that the exact delay accounting matches Scrapy's
  single-request-per-domain concurrency cap.
- Priority: 400 (after UA middleware at 300, before SecFetch at 410).

Spec ref: §2.5 Layer 3 — "mean 4s, SD 1.5s, clipped to [2, 10]",
"With 15% probability, append reading pause 15–45 s".
"""

from __future__ import annotations

import logging
import random
import time
from urllib.parse import urlparse

from scrapy import signals

logger = logging.getLogger(__name__)


class BehaviouralDelayMiddleware:
    """
    Applies a per-request Gaussian-distributed delay before each request is
    dispatched, with an optional extended reading pause.

    Spec ref: §2.5 Layer 3 — Behavioural humanisation.
    """

    def __init__(
        self,
        delay_mean: float,
        delay_sd: float,
        delay_min: float,
        delay_max: float,
        extended_pause_prob: float,
        extended_pause_min: float,
        extended_pause_max: float,
    ) -> None:
        self._delay_mean = delay_mean
        self._delay_sd = delay_sd
        self._delay_min = delay_min
        self._delay_max = delay_max
        self._extended_pause_prob = extended_pause_prob
        self._extended_pause_min = extended_pause_min
        self._extended_pause_max = extended_pause_max

    @classmethod
    def from_crawler(cls, crawler):
        s = crawler.settings
        obj = cls(
            delay_mean=s.getfloat("DOWNLOAD_DELAY", 4.0),
            delay_sd=s.getfloat("DELAY_SD", 1.5),
            delay_min=s.getfloat("DELAY_MIN", 2.0),
            delay_max=s.getfloat("DELAY_MAX", 10.0),
            extended_pause_prob=s.getfloat("EXTENDED_PAUSE_PROBABILITY", 0.15),
            extended_pause_min=s.getfloat("EXTENDED_PAUSE_MIN", 15.0),
            extended_pause_max=s.getfloat("EXTENDED_PAUSE_MAX", 45.0),
        )
        crawler.signals.connect(obj.spider_opened, signal=signals.spider_opened)
        return obj

    def spider_opened(self, spider) -> None:
        logger.debug(
            "BehaviouralDelayMiddleware enabled for spider '%s' — "
            "mean=%.1fs SD=%.1fs range=[%.1f, %.1f] extended_prob=%.0f%%",
            spider.name,
            self._delay_mean,
            self._delay_sd,
            self._delay_min,
            self._delay_max,
            self._extended_pause_prob * 100,
        )

    def process_request(self, request, spider) -> None:  # noqa: D401
        """
        Compute and apply the inter-request delay.

        Algorithm (spec §2.5 Layer 3):
        1. Read ``rate_limit_floor_seconds`` from request meta (default: DELAY_MEAN).
        2. Draw ``raw = gauss(DELAY_MEAN, DELAY_SD)``.
        3. ``delay = max(rate_floor, raw)``  — never go below the floor.
        4. Clip ``delay`` to ``[DELAY_MIN, DELAY_MAX]``.
        5. With probability EXTENDED_PAUSE_PROBABILITY add uniform(EXTENDED_PAUSE_MIN,
           EXTENDED_PAUSE_MAX).
        6. ``time.sleep(delay)``.
        """
        # Per-domain rate floor from manifest (set by start_requests).
        rate_floor: float = float(
            request.meta.get("rate_limit_floor_seconds", self._delay_mean)
        )

        # Step 2–4: Gaussian draw, floor, clip.
        raw: float = random.gauss(self._delay_mean, self._delay_sd)
        # Floor: honour per-domain Crawl-delay even if Gaussian draws below it.
        delay: float = max(rate_floor, raw)
        # Clip to absolute bounds.
        delay = max(self._delay_min, min(delay, self._delay_max))

        # Step 5: optional extended reading pause.
        if random.random() < self._extended_pause_prob:
            pause = random.uniform(self._extended_pause_min, self._extended_pause_max)
            delay += pause

        domain: str = request.meta.get("domain") or urlparse(request.url).netloc
        logger.debug("Delay %s: %.2fs", domain, delay)

        time.sleep(delay)
