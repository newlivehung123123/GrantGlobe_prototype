"""
ContentStoragePipeline — writes crawled resources to the structured cache.

Priority: 500 (runs after ChangeDetectionPipeline at 100 and
PDFExtractionPipeline at 400).

Storage layout (spec §2.6 Content Storage Schema):

  raw_cache/{domain}/{YYYY-MM-DD}/pages/{url_hash}.html       gzip-compressed HTML
  raw_cache/{domain}/{YYYY-MM-DD}/pages/{url_hash}.meta.json  sidecar metadata
  raw_cache/{domain}/{YYYY-MM-DD}/pdfs/{sha256}.pdf           raw PDF binary
  raw_cache/{domain}/{YYYY-MM-DD}/pdfs/{sha256}.meta.json     PDF sidecar

Change detection is handled upstream by ChangeDetectionPipeline (priority 100),
which sets item['content_sha256'] and item['changed'] before this pipeline runs.
This pipeline trusts those values; it only writes the gzip HTML file when
item['changed'] is True (or absent — treated as True for safety).  The
.meta.json sidecar is always written.

PDF url-map (spec §2.4 Step 2):
  raw_cache/{domain}/crawl_manifest.json → pdf_url_map: {canonical_url: sha256}

All file writes are atomic (temp-file + os.replace).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from grantglobe_crawler.items import GrantItem

logger = logging.getLogger(__name__)


class ContentStoragePipeline:
    """
    Scrapy item pipeline that persists crawled HTML and PDF resources.

    Registered in ITEM_PIPELINES at priority 500.  Runs after
    PDFExtractionPipeline (400), which means ``item['language']``,
    ``item['char_count']``, and ``item['content_sha256']`` are already
    populated for PDF items when this pipeline runs.
    """

    def __init__(self, raw_cache_dir: Path) -> None:
        self._raw_cache_dir = raw_cache_dir

    @classmethod
    def from_crawler(cls, crawler):
        raw_cache_dir = Path(crawler.settings.get("RAW_CACHE_DIR", "raw_cache"))
        return cls(raw_cache_dir=raw_cache_dir)

    # ------------------------------------------------------------------
    # Scrapy pipeline interface
    # ------------------------------------------------------------------

    def open_spider(self, spider) -> None:
        self._raw_cache_dir.mkdir(parents=True, exist_ok=True)
        logger.info("ContentStoragePipeline: writing to %s", self._raw_cache_dir)

    def process_item(self, item, spider):
        """
        Persist the item to the raw cache and write the sidecar meta.json.

        All GrantItem instances are processed.  Non-GrantItem items
        (if any future pipeline adds them) pass through unchanged.
        """
        if not isinstance(item, GrantItem):
            return item

        domain: str = item.get("domain") or ""
        if not domain:
            logger.warning("GrantItem missing 'domain' — skipping storage")
            return item

        date_str = _date_from_timestamp(item.get("crawl_timestamp"))

        if item.get("is_pdf"):
            self._store_pdf(item, domain, date_str)
        else:
            self._store_html(item, domain, date_str)

        return item

    # ------------------------------------------------------------------
    # HTML storage
    # ------------------------------------------------------------------

    def _store_html(self, item: GrantItem, domain: str, date_str: str) -> None:
        """
        Steps (spec §2.6 HTML storage):
        1. Trust item['content_sha256'] set by ChangeDetectionPipeline (priority 100).
           Fall back to computing it if somehow absent (defensive).
        2. Trust item['changed'] set by ChangeDetectionPipeline.
           Only write the gzip HTML file when changed is True (or absent — treated
           as True for safety so no data is silently dropped).
        3. Always write the .meta.json sidecar regardless of changed status.
        """
        body: bytes = item.get("html_content") or b""
        url_hash: str = item.get("url_hash") or ""

        if not url_hash:
            logger.warning(
                "GrantItem missing 'url_hash' for %s — skipping HTML storage",
                item.get("url"),
            )
            return

        # Reuse sha256 set by ChangeDetectionPipeline; compute as fallback.
        content_sha256: str = (
            item.get("content_sha256") or hashlib.sha256(body).hexdigest()
        )

        pages_dir = self._raw_cache_dir / domain / date_str / "pages"

        # ── Write compressed HTML only when content has changed ───────────
        # item['changed'] is False when ChangeDetectionPipeline found the hash
        # in the previous cycle's seen_hashes.json.  Absent key → True (safe).
        if item.get("changed", True):
            html_path = pages_dir / f"{url_hash}.html"
            compressed = gzip.compress(body, compresslevel=6)
            _write_bytes_atomic(html_path, compressed)
            logger.debug(
                "Stored HTML %s (%.1f KB gzip)", html_path.name, len(compressed) / 1024
            )

        # ── Write .meta.json sidecar (always) ────────────────────────────
        meta_path = pages_dir / f"{url_hash}.meta.json"
        meta = _build_meta(item, content_sha256)
        _write_json_atomic(meta_path, meta)

    # ------------------------------------------------------------------
    # PDF storage
    # ------------------------------------------------------------------

    def _store_pdf(self, item: GrantItem, domain: str, date_str: str) -> None:
        """
        Steps (spec §2.6 PDF storage):
        1. Compute content_sha256 (or reuse value set by PDFExtractionPipeline).
        2. Write raw PDF bytes to pdfs/{content_sha256}.pdf.
        3. Write PDF .meta.json sidecar.
        4. Update raw_cache/{domain}/crawl_manifest.json pdf_url_map.
        """
        body: bytes = item.get("html_content") or b""

        # PDFExtractionPipeline (priority 400) sets content_sha256 before we run.
        content_sha256: str = item.get("content_sha256") or hashlib.sha256(body).hexdigest()
        item["content_sha256"] = content_sha256

        pdfs_dir = self._raw_cache_dir / domain / date_str / "pdfs"

        # Write raw PDF binary.
        pdf_path = pdfs_dir / f"{content_sha256}.pdf"
        _write_bytes_atomic(pdf_path, body)
        logger.debug(
            "Stored PDF %s (%.1f KB)", pdf_path.name, len(body) / 1024
        )

        # Write .meta.json sidecar.
        meta_path = pdfs_dir / f"{content_sha256}.meta.json"
        meta = _build_meta(item, content_sha256)
        meta["file_size_bytes"] = len(body)
        _write_json_atomic(meta_path, meta)

        # Update pdf_url_map in crawl_manifest.json.
        self._update_pdf_url_map(
            domain,
            canonical_url=item.get("canonical_url") or item.get("url") or "",
            content_sha256=content_sha256,
        )

    def _update_pdf_url_map(
        self, domain: str, canonical_url: str, content_sha256: str
    ) -> None:
        """
        Add ``canonical_url → content_sha256`` to the domain's
        ``crawl_manifest.json`` pdf_url_map.

        Spec ref: §2.4 Step 2 — "The URL-to-content-hash mapping is written
        to crawl_manifest.json as a pdf_url_map object."
        """
        manifest_path = self._raw_cache_dir / domain / "crawl_manifest.json"
        manifest: dict = {}
        if manifest_path.exists():
            try:
                with manifest_path.open(encoding="utf-8") as fh:
                    manifest = json.load(fh)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not load manifest for %s: %s", domain, exc)

        if "pdf_url_map" not in manifest or not isinstance(manifest["pdf_url_map"], dict):
            manifest["pdf_url_map"] = {}
        manifest["pdf_url_map"][canonical_url] = content_sha256

        _write_json_atomic(manifest_path, manifest)



# ===========================================================================
# Module-level helpers (pure functions — no pipeline state)
# ===========================================================================


def _date_from_timestamp(crawl_timestamp: str | None) -> str:
    """
    Extract ``YYYY-MM-DD`` from an ISO 8601 crawl_timestamp string.
    Falls back to today's UTC date if the field is absent or malformed.
    """
    if crawl_timestamp and len(crawl_timestamp) >= 10:
        candidate = crawl_timestamp[:10]
        if candidate.count("-") == 2:
            return candidate
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _build_meta(item: GrantItem, content_sha256: str) -> dict:
    """
    Build the .meta.json sidecar dict from *item* fields.

    Schema matches spec §2.6 meta.json sidecar.
    """
    return {
        "url": item.get("url"),
        "canonical_url": item.get("canonical_url"),
        "url_hash": item.get("url_hash"),
        "content_sha256": content_sha256,
        "domain": item.get("domain"),
        "profile": item.get("profile"),
        "depth": item.get("depth"),
        "source_url": item.get("source_url"),
        "crawl_timestamp": item.get("crawl_timestamp"),
        "is_pdf": item.get("is_pdf"),
        "has_structured_data": item.get("has_structured_data"),
        "page_type": item.get("page_type"),
        "changed": item.get("changed"),
        "char_count": item.get("char_count"),
        "http_status": item.get("http_status"),
        "content_type": item.get("content_type"),
        "language": item.get("language"),
    }


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    """Write *data* bytes to *path* atomically (temp + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _write_json_atomic(path: Path, data) -> None:
    """Serialise *data* to JSON and write to *path* atomically."""
    encoded = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    _write_bytes_atomic(path, encoded)
