"""
ChangeDetectionPipeline — Phase D full implementation.

Priority: 100 — runs first in the pipeline chain, before PDFExtractionPipeline
(400) and ContentStoragePipeline (500), so that ``item['content_sha256']`` and
``item['changed']`` are set for all downstream pipelines.

Responsibilities (spec §2.6 Change detection):
  1. Compute ``content_sha256 = SHA-256(html_content)`` (unless already set by
     an earlier step — guard prevents overwrite).
  2. Compare the hash against ``raw_cache/{domain}/seen_hashes.json`` loaded
     from the previous crawl cycle.
  3. Set ``item['changed'] = True`` for new content, ``False`` for unchanged.
  4. Increment the spider's ``_domain_changed_pages`` counter when changed.
  5. Flush updated hash lists to disk on ``close_spider`` (atomic write).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from collections import defaultdict
from pathlib import Path

from grantglobe_crawler.items import GrantItem

logger = logging.getLogger(__name__)


class ChangeDetectionPipeline:
    """
    Full change-detection pipeline (Phase D).

    Computes each item's content SHA-256, compares it to the previous cycle's
    stored hash list, and sets ``item['changed']`` accordingly.

    Spec ref: §2.6 Change detection — "On subsequent crawl cycles, each newly
    fetched page's content hash is compared to the previous cycle's stored
    content hash.  Pages with changed content are flagged as changed: true."
    """

    def __init__(self, raw_cache_dir: Path) -> None:
        self._raw_cache_dir = Path(raw_cache_dir)
        # In-memory hash store: domain → list[str].  Lazy-loaded per domain.
        self._seen_hashes: dict[str, list[str]] = {}

    @classmethod
    def from_crawler(cls, crawler):
        raw_cache_dir = Path(crawler.settings.get("RAW_CACHE_DIR", "raw_cache"))
        return cls(raw_cache_dir=raw_cache_dir)

    # ------------------------------------------------------------------
    # Scrapy pipeline interface
    # ------------------------------------------------------------------

    def open_spider(self, spider) -> None:
        self._raw_cache_dir.mkdir(parents=True, exist_ok=True)
        logger.debug("ChangeDetectionPipeline: using cache dir %s", self._raw_cache_dir)

    def close_spider(self, spider) -> None:
        """Flush every domain's updated hash list to disk atomically."""
        flushed = 0
        for domain, hashes in self._seen_hashes.items():
            try:
                self._write_seen_hashes(domain, hashes)
                flushed += 1
            except Exception as exc:
                logger.warning(
                    "ChangeDetectionPipeline: failed to flush seen_hashes for %s: %s",
                    domain, exc,
                )
        logger.info(
            "ChangeDetectionPipeline: flushed seen_hashes for %d domain(s)", flushed
        )

    def process_item(self, item, spider):
        """
        Compute content_sha256, compare with seen hashes, set item['changed'].

        Non-GrantItem items pass through unchanged.
        Items without a domain pass through unchanged.
        """
        if not isinstance(item, GrantItem):
            return item

        domain: str = item.get("domain") or ""
        if not domain:
            return item

        body: bytes = item.get("html_content") or b""

        # Guard: if content_sha256 already set (e.g. by a prior processing step
        # on re-crawl), reuse it rather than recomputing.  spec §2.6.
        if not item.get("content_sha256"):
            item["content_sha256"] = hashlib.sha256(body).hexdigest()
        content_sha256: str = item["content_sha256"]

        # ── Deduplication against previous cycle ─────────────────────────
        seen = self._get_seen_hashes(domain)

        if content_sha256 in seen:
            item["changed"] = False
        else:
            item["changed"] = True
            seen.append(content_sha256)
            # Increment spider counter if it was initialised (spec §2.7).
            counter = getattr(spider, "_domain_changed_pages", None)
            if counter is not None:
                counter[domain] += 1

        return item

    # ------------------------------------------------------------------
    # Seen-hashes helpers
    # ------------------------------------------------------------------

    def _get_seen_hashes(self, domain: str) -> list[str]:
        """
        Lazily load ``seen_hashes.json`` for *domain*.

        Returns the in-memory list (mutable; callers append to it directly).
        On JSONDecodeError or OSError, logs a warning and starts with an empty
        list so the domain is processed normally.
        """
        if domain not in self._seen_hashes:
            path = self._raw_cache_dir / domain / "seen_hashes.json"
            if path.exists():
                try:
                    with path.open(encoding="utf-8") as fh:
                        loaded = json.load(fh)
                    self._seen_hashes[domain] = list(loaded) if isinstance(loaded, list) else []
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning(
                        "ChangeDetectionPipeline: could not load seen_hashes for %s: %s",
                        domain, exc,
                    )
                    self._seen_hashes[domain] = []
            else:
                self._seen_hashes[domain] = []
        return self._seen_hashes[domain]

    def _write_seen_hashes(self, domain: str, hashes: list[str]) -> None:
        """Write *hashes* atomically to ``raw_cache/{domain}/seen_hashes.json``."""
        path = self._raw_cache_dir / domain / "seen_hashes.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(hashes, ensure_ascii=False, indent=2).encode("utf-8")
        fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(encoded)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
