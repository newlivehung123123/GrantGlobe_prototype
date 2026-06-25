"""
Tests for the PDF counter wiring between PDFExtractionPipeline and GrantsSpider.

Verifies:
1. process_item() increments spider._domain_pdfs_found[domain] for each PDF.
2. process_item() increments spider._domain_pdf_failures[domain] when extraction fails.
3. process_item() does not raise AttributeError when the spider has no counter attrs.
4. _build_domain_stats() reads from the spider's PDF counters correctly.
5. _build_domain_stats() returns 0 for both when the domain has no counter entries.
"""

from __future__ import annotations

from collections import defaultdict
from unittest.mock import MagicMock, patch

import pytest

from grantglobe_crawler.items import GrantItem
from grantglobe_crawler.pipelines.pdf_pipeline import PDFExtractionPipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SETTINGS = {
    "RAW_CACHE_DIR": "raw_cache",
    "PDF_OCR_THRESHOLD": 0.40,
    "PDF_OCR_MIN_CHARS_PER_PAGE": 100,
    "PDF_OCR_DPI": 300,
    "PDF_OCR_PAGE_BATCH_SIZE": 10,
    "PDF_OCR_LANGUAGES": ["eng"],
    "PDF_FOOTER_REPEAT_THRESHOLD": 0.70,
    "LINGUA_LANGUAGES": ["ENGLISH"],
}


def _make_pipeline() -> PDFExtractionPipeline:
    from pathlib import Path
    class _S(dict):
        def get(self, key, default=None): return super().get(key, default)
        def getfloat(self, key, default=0.0): return float(self.get(key, default))
        def getint(self, key, default=0): return int(self.get(key, default))
        def getlist(self, key, default=None): return self.get(key, default or [])

    s = _S(_SETTINGS)
    return PDFExtractionPipeline(
        raw_cache_dir=Path("raw_cache"),
        ocr_threshold=0.40,
        ocr_min_chars=100,
        ocr_dpi=300,
        ocr_page_batch_size=10,
        ocr_languages=["eng"],
        footer_repeat_threshold=0.70,
        lingua_languages=["ENGLISH"],
    )


def _make_pdf_item(domain: str = "example.org") -> GrantItem:
    """Return a minimal GrantItem with is_pdf=True and non-empty html_content."""
    return GrantItem(
        url=f"https://{domain}/report.pdf",
        canonical_url=f"https://{domain}/report.pdf",
        url_hash="abc123",
        domain=domain,
        profile="A",
        depth=1,
        source_url=None,
        html_content=b"%PDF-1.4 fake pdf bytes",
        headers={},
        crawl_timestamp="2026-05-23T10:00:00+00:00",
        is_pdf=True,
        has_structured_data=False,
    )


def _make_spider_with_counters(domain: str = "example.org"):
    spider = MagicMock()
    spider._domain_pdfs_found = defaultdict(int)
    spider._domain_pdf_failures = defaultdict(int)
    return spider


# ---------------------------------------------------------------------------
# Test 1: process_item() increments pdfs_found
# ---------------------------------------------------------------------------

class TestPdfFoundCounter:
    def test_increments_pdfs_found_on_successful_extraction(self, tmp_path):
        """process_item() increments spider._domain_pdfs_found by 1 for a PDF item."""
        pipeline = _make_pipeline()
        pipeline._raw_cache_dir = tmp_path
        spider = _make_spider_with_counters("example.org")
        item = _make_pdf_item("example.org")

        # Patch _extract_text to return a non-empty string (successful extraction).
        with patch.object(
            pipeline, "_extract_text", return_value=("Extracted grant text.", {})
        ):
            pipeline.process_item(item, spider)

        assert spider._domain_pdfs_found["example.org"] == 1

    def test_increments_pdfs_found_accumulates_across_items(self, tmp_path):
        """Counter accumulates correctly across multiple PDF items for same domain."""
        pipeline = _make_pipeline()
        pipeline._raw_cache_dir = tmp_path
        spider = _make_spider_with_counters("multi.org")

        with patch.object(
            pipeline, "_extract_text", return_value=("Some text.", {})
        ):
            for _ in range(3):
                pipeline.process_item(_make_pdf_item("multi.org"), spider)

        assert spider._domain_pdfs_found["multi.org"] == 3


# ---------------------------------------------------------------------------
# Test 2: process_item() increments pdf_failures on extraction failure
# ---------------------------------------------------------------------------

class TestPdfFailureCounter:
    def test_increments_failures_when_extraction_raises(self, tmp_path):
        """extraction_failed=True when _extract_text raises → failure counter incremented."""
        pipeline = _make_pipeline()
        pipeline._raw_cache_dir = tmp_path
        spider = _make_spider_with_counters("fail.org")
        item = _make_pdf_item("fail.org")

        with patch.object(
            pipeline, "_extract_text", side_effect=RuntimeError("fitz exploded")
        ):
            pipeline.process_item(item, spider)

        assert spider._domain_pdfs_found["fail.org"] == 1    # still counted as found
        assert spider._domain_pdf_failures["fail.org"] == 1

    def test_increments_failures_when_char_count_is_zero(self, tmp_path):
        """extraction_failed=True when extracted text is empty (char_count=0)."""
        pipeline = _make_pipeline()
        pipeline._raw_cache_dir = tmp_path
        spider = _make_spider_with_counters("empty.org")
        item = _make_pdf_item("empty.org")

        with patch.object(
            pipeline, "_extract_text", return_value=("", {})
        ):
            pipeline.process_item(item, spider)

        assert spider._domain_pdfs_found["empty.org"] == 1
        assert spider._domain_pdf_failures["empty.org"] == 1

    def test_no_failure_increment_when_text_extracted(self, tmp_path):
        """No failure counted when extraction succeeds (non-empty text)."""
        pipeline = _make_pipeline()
        pipeline._raw_cache_dir = tmp_path
        spider = _make_spider_with_counters("good.org")
        item = _make_pdf_item("good.org")

        with patch.object(
            pipeline, "_extract_text", return_value=("Grant details here.", {})
        ):
            pipeline.process_item(item, spider)

        assert spider._domain_pdf_failures["good.org"] == 0


# ---------------------------------------------------------------------------
# Test 3: no AttributeError when spider has no counter attributes
# ---------------------------------------------------------------------------

class TestMissingCounterAttributes:
    def test_no_attribute_error_when_counters_absent(self, tmp_path):
        """
        When the spider mock lacks _domain_pdfs_found / _domain_pdf_failures,
        process_item() uses getattr(..., None) safely — no AttributeError raised.
        """
        pipeline = _make_pipeline()
        pipeline._raw_cache_dir = tmp_path

        # Plain MagicMock: attribute access returns a new Mock, not None.
        # We want to simulate a spider without those attrs by spec-restricting it.
        spider = MagicMock(spec=[])  # spec=[] → no attributes defined
        item = _make_pdf_item("noattr.org")

        with patch.object(
            pipeline, "_extract_text", return_value=("Some text.", {})
        ):
            # Must not raise
            result = pipeline.process_item(item, spider)

        assert result is item  # item returned unchanged


# ---------------------------------------------------------------------------
# Test 4: _build_domain_stats() reads from spider counters
# ---------------------------------------------------------------------------

class TestBuildDomainStats:
    def test_returns_correct_pdf_stats_from_counters(self):
        """_build_domain_stats() reads pdfs_found and pdf_failures from counters."""
        from grantglobe_crawler.spiders.grants_spider import GrantsSpider

        # Minimal Scrapy spider instantiation — patch signals to avoid setup overhead.
        with patch("grantglobe_crawler.spiders.grants_spider.signals"):
            spider = GrantsSpider.__new__(GrantsSpider)
            spider.seen_urls = set()
            spider._domain_manifests = {"example.org": {"crawl_status": "complete"}}
            spider._domain_pages_crawled = defaultdict(int)
            spider._domain_failed_requests = defaultdict(int)
            spider._domain_pdfs_found = defaultdict(int)
            spider._domain_pdf_failures = defaultdict(int)
            spider._domain_changed_pages = defaultdict(int)
            spider._domain_grant_relevant_pages = defaultdict(int)
            spider._domains_total = 1
            spider._crawl_start = None
            # Attach a minimal settings mock
            mock_settings = MagicMock()
            mock_settings.get = lambda key, default=None: default
            spider.settings = mock_settings

        spider._domain_pdfs_found["example.org"] = 7
        spider._domain_pdf_failures["example.org"] = 2

        stats = spider._build_domain_stats("example.org")

        assert stats["pdfs_found"] == 7
        assert stats["pdf_extraction_failures"] == 2

    def test_returns_zero_when_no_entries_for_domain(self):
        """_build_domain_stats() returns 0 for both when domain has no counter entries."""
        from grantglobe_crawler.spiders.grants_spider import GrantsSpider

        with patch("grantglobe_crawler.spiders.grants_spider.signals"):
            spider = GrantsSpider.__new__(GrantsSpider)
            spider.seen_urls = set()
            spider._domain_manifests = {"new.org": {}}
            spider._domain_pages_crawled = defaultdict(int)
            spider._domain_failed_requests = defaultdict(int)
            spider._domain_pdfs_found = defaultdict(int)
            spider._domain_pdf_failures = defaultdict(int)
            spider._domain_changed_pages = defaultdict(int)
            spider._domain_grant_relevant_pages = defaultdict(int)
            spider._domains_total = 0
            spider._crawl_start = None
            mock_settings = MagicMock()
            mock_settings.get = lambda key, default=None: default
            spider.settings = mock_settings

        stats = spider._build_domain_stats("new.org")

        assert stats["pdfs_found"] == 0
        assert stats["pdf_extraction_failures"] == 0
