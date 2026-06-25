"""
Tests for ChangeDetectionPipeline (Phase D full implementation).

Uses tmp_path for a real (but temporary) raw_cache directory.
Does NOT rely on Scrapy machinery — instantiates the pipeline directly.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from grantglobe_crawler.items import GrantItem
from grantglobe_crawler.pipelines.change_detection import ChangeDetectionPipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pipeline(tmp_path: Path) -> ChangeDetectionPipeline:
    return ChangeDetectionPipeline(raw_cache_dir=tmp_path)


def _make_item(body: bytes = b"hello world", domain: str = "example.org") -> GrantItem:
    return GrantItem(
        url=f"https://{domain}/page",
        canonical_url=f"https://{domain}/page/",
        url_hash="abc123",
        domain=domain,
        profile="A",
        depth=1,
        html_content=body,
        crawl_timestamp="2026-05-23T12:00:00+00:00",
        is_pdf=False,
        has_structured_data=False,
    )


def _make_spider(with_counter: bool = True):
    spider = MagicMock()
    if with_counter:
        spider._domain_changed_pages = defaultdict(int)
    else:
        # Simulate spider that has no _domain_changed_pages attribute.
        del spider._domain_changed_pages
    return spider


# ---------------------------------------------------------------------------
# Test 1 — New content hash → item["changed"] is True
# ---------------------------------------------------------------------------


class TestNewHash:
    def test_changed_true_for_new_hash(self, tmp_path):
        pipeline = _make_pipeline(tmp_path)
        pipeline.open_spider(None)
        item = _make_item(b"brand new content")
        spider = _make_spider()

        result = pipeline.process_item(item, spider)

        assert result["changed"] is True

    def test_hash_written_to_seen_list(self, tmp_path):
        """After processing a new item the hash is in the in-memory list."""
        pipeline = _make_pipeline(tmp_path)
        pipeline.open_spider(None)
        body = b"fresh content"
        item = _make_item(body)
        spider = _make_spider()

        pipeline.process_item(item, spider)

        expected = hashlib.sha256(body).hexdigest()
        assert expected in pipeline._seen_hashes.get("example.org", [])


# ---------------------------------------------------------------------------
# Test 2 — Same hash twice → second call sets item["changed"] to False
# ---------------------------------------------------------------------------


class TestRepeatedHash:
    def test_second_call_changed_false(self, tmp_path):
        pipeline = _make_pipeline(tmp_path)
        pipeline.open_spider(None)
        body = b"same content"
        spider = _make_spider()

        pipeline.process_item(_make_item(body), spider)
        item2 = _make_item(body)
        pipeline.process_item(item2, spider)

        assert item2["changed"] is False


# ---------------------------------------------------------------------------
# Test 3 — Changed counter incremented on first-seen hash
# ---------------------------------------------------------------------------


class TestChangedCounter:
    def test_counter_incremented_on_new_hash(self, tmp_path):
        pipeline = _make_pipeline(tmp_path)
        pipeline.open_spider(None)
        spider = _make_spider(with_counter=True)
        body = b"new page body"

        pipeline.process_item(_make_item(body), spider)

        assert spider._domain_changed_pages["example.org"] == 1


# ---------------------------------------------------------------------------
# Test 4 — Counter not incremented on repeated hash
# ---------------------------------------------------------------------------


class TestCounterNotRepeated:
    def test_counter_stays_at_one_after_duplicate(self, tmp_path):
        pipeline = _make_pipeline(tmp_path)
        pipeline.open_spider(None)
        spider = _make_spider(with_counter=True)
        body = b"duplicate content"

        pipeline.process_item(_make_item(body), spider)
        pipeline.process_item(_make_item(body), spider)

        assert spider._domain_changed_pages["example.org"] == 1


# ---------------------------------------------------------------------------
# Test 5 — No AttributeError when spider lacks _domain_changed_pages
# ---------------------------------------------------------------------------


class TestMissingCounter:
    def test_no_attribute_error_when_counter_absent(self, tmp_path):
        pipeline = _make_pipeline(tmp_path)
        pipeline.open_spider(None)
        spider = _make_spider(with_counter=False)
        item = _make_item(b"some content")

        # Must not raise AttributeError.
        result = pipeline.process_item(item, spider)
        assert result["changed"] is True


# ---------------------------------------------------------------------------
# Test 6 — content_sha256 written onto item
# ---------------------------------------------------------------------------


class TestSha256Written:
    def test_content_sha256_set_on_item(self, tmp_path):
        pipeline = _make_pipeline(tmp_path)
        pipeline.open_spider(None)
        body = b"sha256 test body"
        item = _make_item(body)
        spider = _make_spider()

        pipeline.process_item(item, spider)

        expected = hashlib.sha256(body).hexdigest()
        assert item["content_sha256"] == expected


# ---------------------------------------------------------------------------
# Test 7 — PDF item: sha256 computed from html_content (raw bytes)
# ---------------------------------------------------------------------------


class TestPdfItem:
    def test_pdf_item_sha256_set_and_changed_true(self, tmp_path):
        pipeline = _make_pipeline(tmp_path)
        pipeline.open_spider(None)
        body = b"%PDF-1.4 fake pdf bytes"
        item = _make_item(body)
        item["is_pdf"] = True
        spider = _make_spider()

        pipeline.process_item(item, spider)

        expected = hashlib.sha256(body).hexdigest()
        assert item["content_sha256"] == expected
        assert item["changed"] is True


# ---------------------------------------------------------------------------
# Test 8 — Pre-computed sha256 is not overwritten
# ---------------------------------------------------------------------------


class TestPrecomputedSha256NotOverwritten:
    def test_existing_sha256_preserved(self, tmp_path):
        """
        If item['content_sha256'] is already set when process_item is called,
        ChangeDetectionPipeline must NOT overwrite it.
        """
        pipeline = _make_pipeline(tmp_path)
        pipeline.open_spider(None)
        body = b"real content"
        item = _make_item(body)
        item["content_sha256"] = "precomputed"
        spider = _make_spider()

        pipeline.process_item(item, spider)

        assert item["content_sha256"] == "precomputed"

    def test_existing_sha256_used_for_dedup(self, tmp_path):
        """
        The precomputed sha256 is used for the seen-hashes lookup so the
        dedup decision is based on the pre-set value.
        """
        pipeline = _make_pipeline(tmp_path)
        pipeline.open_spider(None)
        spider = _make_spider()

        # First pass with precomputed sha256 "precomputed".
        item1 = _make_item(b"content A")
        item1["content_sha256"] = "precomputed"
        pipeline.process_item(item1, spider)
        assert item1["changed"] is True

        # Second pass with the same precomputed sha256 → should be unchanged.
        item2 = _make_item(b"content B")  # different body, same hash key
        item2["content_sha256"] = "precomputed"
        pipeline.process_item(item2, spider)
        assert item2["changed"] is False
