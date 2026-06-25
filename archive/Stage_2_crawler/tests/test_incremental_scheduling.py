"""
Tests for the incremental scheduling feedback loop in spider_closed().

Same minimal-spider helper as test_dead_domain_sunset.py.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_MODULE = "grantglobe_crawler.spiders.grants_spider"


# ---------------------------------------------------------------------------
# Shared helpers (duplicated from test_dead_domain_sunset for standalone use)
# ---------------------------------------------------------------------------


class _Settings:
    _DEFAULTS = {
        "DEAD_DOMAIN_FAILED_CYCLE_THRESHOLD": 3,
        "INCREMENTAL_DOWNGRADE_BIWEEKLY_THRESHOLD": 3,
        "INCREMENTAL_DOWNGRADE_MONTHLY_THRESHOLD": 6,
        "ALERT_THRESHOLD_DOMAIN_FAILURE_RATE": 0.20,
        "ALERT_THRESHOLD_CAPTCHA_BLOCKED_DOMAINS": 10,
        "ALERT_THRESHOLD_ZERO_GRANT_PAGES_DOMAINS": 5,
    }

    def __init__(self, crawl_state_dir: str):
        self._D = dict(self._DEFAULTS)
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
    """Return the manifest dict from the last _write_manifest_atomic call for domain."""
    last = None
    for c in write_mock.call_args_list:
        if c[0][1] == domain:
            last = c[0][2]
    return last


def _run_closed(spider):
    """Call spider_closed() with manifest writes and QA reporter mocked."""
    with patch(f"{_MODULE}._write_manifest_atomic") as write_mock:
        with patch(f"{_MODULE}.QAReporter"):
            spider.spider_closed(spider=spider, reason="finished")
    return write_mock


# ---------------------------------------------------------------------------
# Test 1 — zero changed pages increments consecutive_unchanged_cycles
# ---------------------------------------------------------------------------


class TestUnchangedCyclesIncrement:
    def test_unchanged_cycles_incremented_on_zero_changes(self, tmp_path):
        """
        A complete domain with no changed pages increments
        consecutive_unchanged_cycles by 1.
        """
        spider = _make_spider(tmp_path)
        spider._domain_manifests["x.org"] = {
            "crawl_status": "complete",
            "crawl_frequency": "weekly",
            "consecutive_unchanged_cycles": 0,
        }
        spider._domain_pages_crawled["x.org"] = 5
        spider._domain_changed_pages["x.org"] = 0
        spider._domains_total = 1

        write_mock = _run_closed(spider)

        saved = _last_saved_manifest(write_mock, "x.org")
        assert saved["consecutive_unchanged_cycles"] == 1


# ---------------------------------------------------------------------------
# Test 2 — three unchanged cycles → biweekly downgrade
# ---------------------------------------------------------------------------


class TestBiweeklyDowngrade:
    def test_three_unchanged_cycles_triggers_biweekly(self, tmp_path):
        """
        consecutive_unchanged_cycles goes from 2 → 3 (== threshold) and the
        domain's crawl_frequency is downgraded to 'biweekly'.
        """
        spider = _make_spider(tmp_path)
        spider._domain_manifests["x.org"] = {
            "crawl_status": "complete",
            "crawl_frequency": "weekly",
            "consecutive_unchanged_cycles": 2,
        }
        spider._domain_pages_crawled["x.org"] = 5
        spider._domain_changed_pages["x.org"] = 0
        spider._domains_total = 1

        write_mock = _run_closed(spider)

        saved = _last_saved_manifest(write_mock, "x.org")
        assert saved["crawl_frequency"] == "biweekly"

    def test_below_biweekly_threshold_stays_weekly(self, tmp_path):
        """Two unchanged cycles (threshold 3) must NOT trigger a downgrade."""
        spider = _make_spider(tmp_path)
        spider._domain_manifests["x.org"] = {
            "crawl_status": "complete",
            "crawl_frequency": "weekly",
            "consecutive_unchanged_cycles": 1,
        }
        spider._domain_pages_crawled["x.org"] = 5
        spider._domain_changed_pages["x.org"] = 0
        spider._domains_total = 1

        write_mock = _run_closed(spider)

        saved = _last_saved_manifest(write_mock, "x.org")
        assert saved["crawl_frequency"] == "weekly"


# ---------------------------------------------------------------------------
# Test 3 — six unchanged cycles → monthly downgrade
# ---------------------------------------------------------------------------


class TestMonthlyDowngrade:
    def test_six_unchanged_cycles_triggers_monthly(self, tmp_path):
        """
        consecutive_unchanged_cycles goes from 5 → 6 (== monthly threshold)
        → crawl_frequency becomes 'monthly'.
        """
        spider = _make_spider(tmp_path)
        spider._domain_manifests["x.org"] = {
            "crawl_status": "complete",
            "crawl_frequency": "biweekly",
            "consecutive_unchanged_cycles": 5,
        }
        spider._domain_pages_crawled["x.org"] = 5
        spider._domain_changed_pages["x.org"] = 0
        spider._domains_total = 1

        write_mock = _run_closed(spider)

        saved = _last_saved_manifest(write_mock, "x.org")
        assert saved["crawl_frequency"] == "monthly"


# ---------------------------------------------------------------------------
# Test 4 — changed pages after downgrade → restored to weekly
# ---------------------------------------------------------------------------


class TestRestoreAfterChange:
    def test_changed_pages_restore_weekly_frequency(self, tmp_path):
        """
        A domain previously downgraded to 'monthly' that now has changed
        pages is restored to 'weekly'.
        """
        spider = _make_spider(tmp_path)
        spider._domain_manifests["x.org"] = {
            "crawl_status": "complete",
            "crawl_frequency": "monthly",
            "consecutive_unchanged_cycles": 8,
        }
        spider._domain_pages_crawled["x.org"] = 5
        spider._domain_changed_pages["x.org"] = 3
        spider._domains_total = 1

        write_mock = _run_closed(spider)

        saved = _last_saved_manifest(write_mock, "x.org")
        assert saved["crawl_frequency"] == "weekly"
        assert saved["consecutive_unchanged_cycles"] == 0

    def test_triggered_recrawl_flag_set_after_restore(self, tmp_path):
        """triggered_recrawl_after_change flag is written to manifest."""
        spider = _make_spider(tmp_path)
        spider._domain_manifests["x.org"] = {
            "crawl_status": "complete",
            "crawl_frequency": "biweekly",
            "consecutive_unchanged_cycles": 4,
        }
        spider._domain_pages_crawled["x.org"] = 5
        spider._domain_changed_pages["x.org"] = 2
        spider._domains_total = 1

        write_mock = _run_closed(spider)

        saved = _last_saved_manifest(write_mock, "x.org")
        assert saved.get("triggered_recrawl_after_change") is True


# ---------------------------------------------------------------------------
# Test 5 — downgrade_protected: True → frequency never changed
# ---------------------------------------------------------------------------


class TestDowngradeProtected:
    def test_protected_domain_not_downgraded(self, tmp_path):
        """downgrade_protected=True domains are skipped by the scheduling loop."""
        spider = _make_spider(tmp_path)
        spider._domain_manifests["x.org"] = {
            "crawl_status": "complete",
            "crawl_frequency": "weekly",
            "downgrade_protected": True,
            "consecutive_unchanged_cycles": 10,
        }
        spider._domain_pages_crawled["x.org"] = 5
        spider._domain_changed_pages["x.org"] = 0
        spider._domains_total = 1

        write_mock = _run_closed(spider)

        # The scheduling loop skips this domain — the manifest write for
        # this domain only comes from the initial loop (crawl_status update).
        # Verify that crawl_frequency was not mutated to biweekly/monthly.
        saved = _last_saved_manifest(write_mock, "x.org")
        # The initial manifest loop writes crawl_status; it does not touch
        # crawl_frequency.  The scheduling loop is skipped entirely.
        assert saved.get("crawl_frequency", "weekly") == "weekly"
        assert saved.get("consecutive_unchanged_cycles", 10) == 10
