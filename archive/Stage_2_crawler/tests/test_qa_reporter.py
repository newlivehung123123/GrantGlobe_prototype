"""
Unit tests for grantglobe_crawler.qa.qa_reporter.QAReporter.

Tests cover:
- Zero-domain edge cases (no ZeroDivisionError)
- All alert_flags triggered when thresholds exceeded
- No alert_flags when all metrics are within bounds
- Per-domain classification lists are computed correctly
- write_report writes valid JSON to the correct path
- write_summary writes a non-empty text file to the correct path
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from grantglobe_crawler.qa.qa_reporter import QAReporter


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_SETTINGS = {
    "QA_GRANT_RELEVANCE_MIN_RATIO": 0.20,
    "QA_PDF_SUCCESS_MIN_RATE": 0.80,
    "QA_HIGH_CHANGE_THRESHOLD": 0.30,
    "ALERT_THRESHOLD_DOMAIN_FAILURE_RATE": 0.20,
    "ALERT_THRESHOLD_CAPTCHA_BLOCKED_DOMAINS": 10,
    "ALERT_THRESHOLD_ZERO_GRANT_PAGES_DOMAINS": 30,
}

_RUN_DATE = "2026-05-23"


def _make_reporter(tmp_path: Path) -> QAReporter:
    return QAReporter(raw_cache_dir=tmp_path, settings=_SETTINGS)


def _healthy_domain_stats(domain: str = "example.org", pages: int = 100) -> dict:
    """Return a stats dict that triggers no alerts for a domain."""
    return {
        "pages_crawled": pages,
        "pdfs_found": 10,
        "pdf_extraction_failures": 1,       # 10 % failure — below 20 % threshold
        "grant_relevant_pages": 30,          # 30 % — above 20 % threshold
        "changed_pages": 20,                 # 20 % — below 30 % threshold
        "captcha_blocks": 0,
        "http_errors": {},
        "crawl_status": "complete",
    }


# ---------------------------------------------------------------------------
# Zero-domain edge cases
# ---------------------------------------------------------------------------


class TestZeroDomains:
    def test_zero_domains_structure(self, tmp_path):
        reporter = _make_reporter(tmp_path)
        report = reporter.generate_report(_RUN_DATE, {})

        assert report["report_date"] == _RUN_DATE
        assert report["total_domains"] == 0
        assert report["domains_complete"] == 0
        assert report["domains_failed"] == 0
        assert report["domains_dead_candidate"] == 0
        assert report["total_pages_crawled"] == 0
        assert report["total_pdfs_found"] == 0
        assert report["total_pdf_extraction_failures"] == 0
        assert report["pdf_extraction_failure_rate"] == 0.0
        assert report["total_grant_relevant_pages"] == 0
        assert report["grant_relevance_rate"] == 0.0
        assert report["total_changed_pages"] == 0
        assert report["total_captcha_blocks"] == 0
        assert report["alert_flags"] == []

    def test_no_division_by_zero_pdfs(self, tmp_path):
        """pdf_extraction_failure_rate must be 0.0 when total_pdfs_found == 0."""
        reporter = _make_reporter(tmp_path)
        stats = {
            "d.org": {
                "pages_crawled": 50,
                "pdfs_found": 0,
                "pdf_extraction_failures": 0,
                "grant_relevant_pages": 20,
                "changed_pages": 5,
                "captcha_blocks": 0,
                "http_errors": {},
                "crawl_status": "complete",
            }
        }
        report = reporter.generate_report(_RUN_DATE, stats)
        assert report["pdf_extraction_failure_rate"] == 0.0

    def test_no_division_by_zero_pages(self, tmp_path):
        """grant_relevance_rate must be 0.0 when total_pages_crawled == 0."""
        reporter = _make_reporter(tmp_path)
        stats = {
            "d.org": {
                "pages_crawled": 0,
                "pdfs_found": 0,
                "pdf_extraction_failures": 0,
                "grant_relevant_pages": 0,
                "changed_pages": 0,
                "captcha_blocks": 0,
                "http_errors": {},
                "crawl_status": "failed",
            }
        }
        report = reporter.generate_report(_RUN_DATE, stats)
        assert report["grant_relevance_rate"] == 0.0


# ---------------------------------------------------------------------------
# Alert flag logic
# ---------------------------------------------------------------------------


class TestAlertFlags:
    def test_no_alerts_when_within_thresholds(self, tmp_path):
        reporter = _make_reporter(tmp_path)
        stats = {f"d{i}.org": _healthy_domain_stats(f"d{i}.org") for i in range(10)}
        report = reporter.generate_report(_RUN_DATE, stats)
        assert report["alert_flags"] == []

    def test_pdf_failure_rate_alert(self, tmp_path):
        """'HIGH: PDF extraction failure rate' when failure rate > 20 %."""
        reporter = _make_reporter(tmp_path)
        stats = {
            "bad.org": {
                "pages_crawled": 100,
                "pdfs_found": 10,
                "pdf_extraction_failures": 5,  # 50 % — above 20 % threshold
                "grant_relevant_pages": 30,
                "changed_pages": 20,
                "captcha_blocks": 0,
                "http_errors": {},
                "crawl_status": "complete",
            }
        }
        report = reporter.generate_report(_RUN_DATE, stats)
        matching = [f for f in report["alert_flags"] if f.startswith("HIGH: PDF")]
        assert len(matching) == 1
        assert "50.0%" in matching[0]

    def test_critical_domain_failure_alert(self, tmp_path):
        """'CRITICAL: N domains failed' when > 20 % of domains fail."""
        reporter = _make_reporter(tmp_path)
        # 3 failed out of 10 → 30 %, above 20 % threshold
        stats: dict[str, dict] = {}
        for i in range(7):
            stats[f"ok{i}.org"] = _healthy_domain_stats(f"ok{i}.org")
        for i in range(3):
            stats[f"fail{i}.org"] = {
                "pages_crawled": 0,
                "pdfs_found": 0,
                "pdf_extraction_failures": 0,
                "grant_relevant_pages": 0,
                "changed_pages": 0,
                "captcha_blocks": 0,
                "http_errors": {"500": 5},
                "crawl_status": "failed",
            }
        report = reporter.generate_report(_RUN_DATE, stats)
        matching = [f for f in report["alert_flags"] if f.startswith("CRITICAL")]
        assert len(matching) == 1
        assert "3 domains failed" in matching[0]

    def test_captcha_alert(self, tmp_path):
        """'HIGH: N CAPTCHA-blocked' when total_captcha_blocks > 10."""
        reporter = _make_reporter(tmp_path)
        # 11 captcha blocks in total from a single domain
        stats = {
            "blocked.org": {
                "pages_crawled": 5,
                "pdfs_found": 0,
                "pdf_extraction_failures": 0,
                "grant_relevant_pages": 2,
                "changed_pages": 1,
                "captcha_blocks": 11,
                "http_errors": {},
                "crawl_status": "complete",
            }
        }
        report = reporter.generate_report(_RUN_DATE, stats)
        matching = [f for f in report["alert_flags"] if "CAPTCHA" in f]
        assert len(matching) == 1
        assert "11" in matching[0]

    def test_grant_relevance_alert(self, tmp_path):
        """'MEDIUM: N domains below grant-relevance' when > 30 domains below threshold."""
        reporter = _make_reporter(tmp_path)
        # 31 domains with 0 grant-relevant pages each
        stats: dict[str, dict] = {}
        for i in range(31):
            stats[f"low{i}.org"] = {
                "pages_crawled": 50,
                "pdfs_found": 0,
                "pdf_extraction_failures": 0,
                "grant_relevant_pages": 0,  # 0 % — below 20 % threshold
                "changed_pages": 5,
                "captcha_blocks": 0,
                "http_errors": {},
                "crawl_status": "complete",
            }
        report = reporter.generate_report(_RUN_DATE, stats)
        matching = [f for f in report["alert_flags"] if f.startswith("MEDIUM")]
        assert len(matching) == 1
        assert "31 domains" in matching[0]

    def test_all_alerts_simultaneously(self, tmp_path):
        """All four alert types fire together when all thresholds are exceeded."""
        reporter = _make_reporter(tmp_path)
        stats: dict[str, dict] = {}
        # 31 domains with 0 grant-relevant pages (triggers MEDIUM)
        for i in range(31):
            stats[f"low{i}.org"] = {
                "pages_crawled": 50,
                "pdfs_found": 10,
                "pdf_extraction_failures": 6,  # 60 % failure → HIGH PDF alert
                "grant_relevant_pages": 0,     # 0 % relevance → MEDIUM alert
                "changed_pages": 5,
                "captcha_blocks": 2,           # contributes to total > 10
                "http_errors": {},
                "crawl_status": "failed",      # all failed → CRITICAL alert
            }
        report = reporter.generate_report(_RUN_DATE, stats)
        flags = report["alert_flags"]
        flag_text = " ".join(flags)
        assert any("HIGH: PDF" in f for f in flags)
        assert any("CRITICAL" in f for f in flags)
        assert any("CAPTCHA" in f for f in flags)
        assert any("MEDIUM" in f for f in flags)


# ---------------------------------------------------------------------------
# Per-domain classification lists
# ---------------------------------------------------------------------------


class TestDomainLists:
    def test_domains_below_grant_relevance_threshold(self, tmp_path):
        reporter = _make_reporter(tmp_path)
        stats = {
            "low.org": {
                "pages_crawled": 100,
                "pdfs_found": 0,
                "pdf_extraction_failures": 0,
                "grant_relevant_pages": 5,  # 5 % — below 20 %
                "changed_pages": 0,
                "captcha_blocks": 0,
                "http_errors": {},
                "crawl_status": "complete",
            },
            "high.org": _healthy_domain_stats("high.org"),
            # 0 pages_crawled must NOT appear in the list
            "zero.org": {
                "pages_crawled": 0,
                "pdfs_found": 0,
                "pdf_extraction_failures": 0,
                "grant_relevant_pages": 0,
                "changed_pages": 0,
                "captcha_blocks": 0,
                "http_errors": {},
                "crawl_status": "failed",
            },
        }
        report = reporter.generate_report(_RUN_DATE, stats)
        below = report["domains_below_grant_relevance_threshold"]
        assert "low.org" in below
        assert "high.org" not in below
        assert "zero.org" not in below   # pages_crawled == 0 excluded

    def test_domains_high_pdf_failure(self, tmp_path):
        reporter = _make_reporter(tmp_path)
        stats = {
            "bad_pdf.org": {
                "pages_crawled": 50,
                "pdfs_found": 10,
                "pdf_extraction_failures": 3,  # 30 % — above 20 % threshold
                "grant_relevant_pages": 20,
                "changed_pages": 5,
                "captcha_blocks": 0,
                "http_errors": {},
                "crawl_status": "complete",
            },
            "good_pdf.org": {
                "pages_crawled": 50,
                "pdfs_found": 10,
                "pdf_extraction_failures": 1,  # 10 % — within threshold
                "grant_relevant_pages": 20,
                "changed_pages": 5,
                "captcha_blocks": 0,
                "http_errors": {},
                "crawl_status": "complete",
            },
        }
        report = reporter.generate_report(_RUN_DATE, stats)
        assert "bad_pdf.org" in report["domains_high_pdf_failure"]
        assert "good_pdf.org" not in report["domains_high_pdf_failure"]

    def test_domains_captcha_blocked(self, tmp_path):
        reporter = _make_reporter(tmp_path)
        stats = {
            "blocked.org": {**_healthy_domain_stats("blocked.org"), "captcha_blocks": 3},
            "clean.org": {**_healthy_domain_stats("clean.org"), "captcha_blocks": 0},
        }
        report = reporter.generate_report(_RUN_DATE, stats)
        assert "blocked.org" in report["domains_captcha_blocked"]
        assert "clean.org" not in report["domains_captcha_blocked"]

    def test_domains_high_change(self, tmp_path):
        reporter = _make_reporter(tmp_path)
        stats = {
            "volatile.org": {
                "pages_crawled": 100,
                "pdfs_found": 0,
                "pdf_extraction_failures": 0,
                "grant_relevant_pages": 25,
                "changed_pages": 40,  # 40 % — above 30 % threshold
                "captcha_blocks": 0,
                "http_errors": {},
                "crawl_status": "complete",
            },
            "stable.org": {
                "pages_crawled": 100,
                "pdfs_found": 0,
                "pdf_extraction_failures": 0,
                "grant_relevant_pages": 25,
                "changed_pages": 20,  # 20 % — within threshold
                "captcha_blocks": 0,
                "http_errors": {},
                "crawl_status": "complete",
            },
        }
        report = reporter.generate_report(_RUN_DATE, stats)
        assert "volatile.org" in report["domains_high_change"]
        assert "stable.org" not in report["domains_high_change"]


# ---------------------------------------------------------------------------
# File output
# ---------------------------------------------------------------------------


class TestFileOutput:
    def test_write_report_creates_json(self, tmp_path):
        reporter = _make_reporter(tmp_path)
        stats = {"a.org": _healthy_domain_stats("a.org")}
        report = reporter.generate_report(_RUN_DATE, stats)
        written = reporter.write_report(report)

        assert written.exists()
        assert written.suffix == ".json"
        assert _RUN_DATE in written.name

        loaded = json.loads(written.read_text(encoding="utf-8"))
        assert loaded["report_date"] == _RUN_DATE
        assert loaded["total_domains"] == 1

    def test_write_report_to_output_dir(self, tmp_path):
        alt_dir = tmp_path / "alt"
        reporter = _make_reporter(tmp_path)
        stats = {"a.org": _healthy_domain_stats()}
        report = reporter.generate_report(_RUN_DATE, stats)
        reporter.write_report(report, output_dir=alt_dir)

        alt_file = alt_dir / f"crawl_report_{_RUN_DATE}.json"
        assert alt_file.exists()
        loaded = json.loads(alt_file.read_text(encoding="utf-8"))
        assert loaded["report_date"] == _RUN_DATE

    def test_write_summary_creates_txt(self, tmp_path):
        reporter = _make_reporter(tmp_path)
        stats = {"a.org": _healthy_domain_stats("a.org")}
        report = reporter.generate_report(_RUN_DATE, stats)
        written = reporter.write_summary(report)

        assert written.exists()
        assert written.suffix == ".txt"
        assert _RUN_DATE in written.name

        content = written.read_text(encoding="utf-8")
        assert len(content) > 0
        assert _RUN_DATE in content
        assert "domains" in content.lower()

    def test_write_summary_includes_alert_flags(self, tmp_path):
        reporter = _make_reporter(tmp_path)
        # Force a critical alert: 3 out of 5 domains failed (60 %)
        stats: dict[str, dict] = {}
        for i in range(2):
            stats[f"ok{i}.org"] = _healthy_domain_stats(f"ok{i}.org")
        for i in range(3):
            stats[f"fail{i}.org"] = {
                "pages_crawled": 0,
                "pdfs_found": 0,
                "pdf_extraction_failures": 0,
                "grant_relevant_pages": 0,
                "changed_pages": 0,
                "captcha_blocks": 0,
                "http_errors": {},
                "crawl_status": "failed",
            }
        report = reporter.generate_report(_RUN_DATE, stats)
        written = reporter.write_summary(report)
        content = written.read_text(encoding="utf-8")
        assert "CRITICAL" in content

    def test_write_report_valid_json_schema(self, tmp_path):
        """All required top-level keys are present and have the right types."""
        reporter = _make_reporter(tmp_path)
        stats = {"a.org": _healthy_domain_stats("a.org")}
        report = reporter.generate_report(_RUN_DATE, stats)
        written = reporter.write_report(report)
        loaded = json.loads(written.read_text())

        required_int_keys = [
            "total_domains",
            "domains_complete",
            "domains_failed",
            "domains_dead_candidate",
            "total_pages_crawled",
            "total_pdfs_found",
            "total_pdf_extraction_failures",
            "total_grant_relevant_pages",
            "total_changed_pages",
            "total_captcha_blocks",
        ]
        for key in required_int_keys:
            assert key in loaded, f"Missing key: {key}"
            assert isinstance(loaded[key], int), f"{key} should be int, got {type(loaded[key])}"

        assert isinstance(loaded["pdf_extraction_failure_rate"], float)
        assert isinstance(loaded["grant_relevance_rate"], float)
        assert isinstance(loaded["alert_flags"], list)
        assert isinstance(loaded["domains_below_grant_relevance_threshold"], list)
        assert isinstance(loaded["domains_high_pdf_failure"], list)
        assert isinstance(loaded["domains_high_change"], list)
        assert isinstance(loaded["domains_captcha_blocked"], list)
