"""
Tests for the dead-domain sunset logic in GrantsSpider.spider_closed().

Calls spider_closed() directly on a manually-built spider (no Scrapy
framework required).  _write_manifest_atomic and file-writing helpers are
patched so no real I/O occurs; _append_manual_review writes to tmp_path.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

_MODULE = "grantglobe_crawler.spiders.grants_spider"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


class _Settings:
    _D = {
        "CRAWL_STATE_DIR": None,          # overridden per-test with tmp_path
        "RAW_CACHE_DIR": None,
        "DEAD_DOMAIN_FAILED_CYCLE_THRESHOLD": 3,
        "INCREMENTAL_DOWNGRADE_BIWEEKLY_THRESHOLD": 3,
        "INCREMENTAL_DOWNGRADE_MONTHLY_THRESHOLD": 6,
        "ALERT_THRESHOLD_DOMAIN_FAILURE_RATE": 0.20,
        "ALERT_THRESHOLD_CAPTCHA_BLOCKED_DOMAINS": 10,
        "ALERT_THRESHOLD_ZERO_GRANT_PAGES_DOMAINS": 5,
    }

    def __init__(self, crawl_state_dir: str):
        self._D = dict(self._D)
        self._D["CRAWL_STATE_DIR"] = crawl_state_dir
        self._D["RAW_CACHE_DIR"] = crawl_state_dir

    def get(self, key, default=None):
        return self._D.get(key, default)

    def getint(self, key, default=0):
        val = self._D.get(key)
        return int(val) if val is not None else default

    def getfloat(self, key, default=0.0):
        val = self._D.get(key)
        return float(val) if val is not None else default

    def getlist(self, key, default=None):
        return default or []


def _make_spider(tmp_path: Path, domain: str = "x.org"):
    """Build a minimal GrantsSpider without Scrapy machinery."""
    from grantglobe_crawler.spiders.grants_spider import GrantsSpider

    spider = object.__new__(GrantsSpider)
    spider.seen_urls = set()
    spider._domain_manifests = {}
    spider._domain_pages_crawled = defaultdict(int)
    spider._domain_failed_requests = defaultdict(int)
    spider._domain_pdfs_found = defaultdict(int)
    spider._domain_pdf_failures = defaultdict(int)
    spider._domain_changed_pages = defaultdict(int)
    spider._domain_grant_relevant_pages = defaultdict(int)
    spider._domains_total = 0
    spider._crawl_start = None
    spider._pagination_handler = MagicMock()
    spider.settings = _Settings(str(tmp_path))
    return spider


def _last_saved_manifest(write_mock, domain: str) -> dict | None:
    """
    Return the manifest dict from the last _write_manifest_atomic call for
    *domain*.  The helper is called as _write_manifest_atomic(dir, domain, manifest).
    """
    last = None
    for c in write_mock.call_args_list:
        if c[0][1] == domain:
            last = c[0][2]
    return last


def _run_spider_closed(spider, *, patch_write=True):
    """
    Call spider_closed() with all heavy I/O mocked except _append_manual_review
    (which writes to the real tmp_path so we can assert on file contents).

    Returns the write_mock if patch_write is True.
    """
    patches = [
        patch(f"{_MODULE}.QAReporter"),
    ]
    if patch_write:
        patches.append(patch(f"{_MODULE}._write_manifest_atomic"))

    with patch(f"{_MODULE}.QAReporter"):
        with patch(f"{_MODULE}._write_manifest_atomic") as write_mock:
            spider.spider_closed(spider=spider, reason="finished")
            return write_mock


# ---------------------------------------------------------------------------
# Test 1 — failed cycle increments consecutive_failed_cycles
# ---------------------------------------------------------------------------


class TestFailureCycleTracking:
    def test_consecutive_failed_cycles_incremented(self, tmp_path):
        """
        Domain with pages=0 and failed>0 gets crawl_status='failed' in the
        first loop, then consecutive_failed_cycles is incremented by 1 in the
        sunset block.
        """
        spider = _make_spider(tmp_path)
        spider._domain_manifests["x.org"] = {
            "crawl_status": "complete",
            "consecutive_failed_cycles": 0,
        }
        spider._domain_pages_crawled["x.org"] = 0
        spider._domain_failed_requests["x.org"] = 1
        spider._domains_total = 1

        write_mock = _run_spider_closed(spider)

        saved = _last_saved_manifest(write_mock, "x.org")
        assert saved is not None
        assert saved["consecutive_failed_cycles"] == 1

    def test_failed_cycles_reset_on_success(self, tmp_path):
        """
        A domain with pages>0 gets crawl_status='complete' and
        consecutive_failed_cycles reset to 0.
        """
        spider = _make_spider(tmp_path)
        spider._domain_manifests["x.org"] = {
            "crawl_status": "complete",
            "consecutive_failed_cycles": 2,
        }
        spider._domain_pages_crawled["x.org"] = 5
        spider._domain_failed_requests["x.org"] = 0
        spider._domains_total = 1

        write_mock = _run_spider_closed(spider)

        saved = _last_saved_manifest(write_mock, "x.org")
        assert saved["consecutive_failed_cycles"] == 0


# ---------------------------------------------------------------------------
# Test 2 — three consecutive failures → dead_domain_candidate: True
# ---------------------------------------------------------------------------


class TestDeadDomainEscalation:
    def test_dead_domain_candidate_set_after_threshold(self, tmp_path):
        """
        With consecutive_failed_cycles already at 2 and another failure cycle,
        the total hits 3 (== threshold) → dead_domain_candidate: True.
        """
        spider = _make_spider(tmp_path)
        spider._domain_manifests["x.org"] = {
            "crawl_status": "complete",
            "consecutive_failed_cycles": 2,
            "dead_domain_candidate": False,
        }
        spider._domain_pages_crawled["x.org"] = 0
        spider._domain_failed_requests["x.org"] = 1
        spider._domains_total = 1

        write_mock = _run_spider_closed(spider)

        saved = _last_saved_manifest(write_mock, "x.org")
        assert saved["dead_domain_candidate"] is True
        assert saved["crawl_status"] == "dead_domain_candidate"

    def test_dead_domain_not_set_below_threshold(self, tmp_path):
        """Two failures (threshold 3) must NOT set dead_domain_candidate."""
        spider = _make_spider(tmp_path)
        spider._domain_manifests["x.org"] = {
            "crawl_status": "complete",
            "consecutive_failed_cycles": 1,
            "dead_domain_candidate": False,
        }
        spider._domain_pages_crawled["x.org"] = 0
        spider._domain_failed_requests["x.org"] = 1
        spider._domains_total = 1

        write_mock = _run_spider_closed(spider)

        saved = _last_saved_manifest(write_mock, "x.org")
        assert saved.get("dead_domain_candidate", False) is False


# ---------------------------------------------------------------------------
# Test 2b — pre-existing dead_domain_candidate: manifest state preserved
# ---------------------------------------------------------------------------


class TestPreExistingDeadCandidate:
    def test_previously_dead_domain_not_overwritten(self, tmp_path):
        """
        A domain already flagged dead_domain_candidate=True in a prior cycle
        is skipped in start_requests() and has pages=0, failed=0 this cycle.
        spider_closed() must NOT overwrite crawl_status to 'complete' or
        reset consecutive_failed_cycles to 0.
        """
        spider = _make_spider(tmp_path)
        spider._domain_manifests["x.org"] = {
            "crawl_status": "dead_domain_candidate",
            "dead_domain_candidate": True,
            "consecutive_failed_cycles": 4,
        }
        # Domain was skipped — no pages or failures recorded this cycle.
        spider._domain_pages_crawled["x.org"] = 0
        spider._domain_failed_requests["x.org"] = 0
        spider._domains_total = 0

        write_mock = _run_spider_closed(spider)

        saved = _last_saved_manifest(write_mock, "x.org")
        assert saved is not None
        assert saved["dead_domain_candidate"] is True
        assert saved["crawl_status"] == "dead_domain_candidate"
        assert saved["consecutive_failed_cycles"] == 4  # preserved, not reset


# ---------------------------------------------------------------------------
# Test 3 — successful crawl resets consecutive_failed_cycles
# ---------------------------------------------------------------------------


class TestSuccessfulCrawlReset:
    def test_success_resets_failed_cycles(self, tmp_path):
        """
        A domain that was previously failing but now returns pages resets
        consecutive_failed_cycles to 0.
        """
        spider = _make_spider(tmp_path)
        spider._domain_manifests["x.org"] = {
            "crawl_status": "complete",
            "consecutive_failed_cycles": 2,
        }
        spider._domain_pages_crawled["x.org"] = 5
        spider._domain_failed_requests["x.org"] = 0
        spider._domains_total = 1

        write_mock = _run_spider_closed(spider)

        saved = _last_saved_manifest(write_mock, "x.org")
        assert saved["consecutive_failed_cycles"] == 0


# ---------------------------------------------------------------------------
# Test 4 — manual_review file written for dead candidate
# ---------------------------------------------------------------------------


class TestManualReviewFile:
    def test_manual_review_file_created(self, tmp_path):
        """
        When dead_domain_candidate is triggered, a manual_review_{date}.txt
        file is created in crawl_state_dir containing the domain name.
        """
        spider = _make_spider(tmp_path)
        spider._domain_manifests["x.org"] = {
            "crawl_status": "complete",
            "consecutive_failed_cycles": 2,
            "dead_domain_candidate": False,
        }
        spider._domain_pages_crawled["x.org"] = 0
        spider._domain_failed_requests["x.org"] = 1
        spider._domains_total = 1

        # Run without patching _write_manifest_atomic so the real file
        # path logic for _append_manual_review executes against tmp_path.
        # But we still need to suppress the actual manifest file writes.
        with patch(f"{_MODULE}._write_manifest_atomic"):
            with patch(f"{_MODULE}.QAReporter"):
                spider.spider_closed(spider=spider, reason="finished")

        review_files = list(tmp_path.glob("manual_review_*.txt"))
        assert len(review_files) == 1, "Expected exactly one manual_review file"
        content = review_files[0].read_text(encoding="utf-8")
        assert "x.org" in content
