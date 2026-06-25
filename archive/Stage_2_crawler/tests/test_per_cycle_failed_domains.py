"""
Tests for per-cycle failed-domain reporting and single-failure alert rule.

Deliverable 1: domains_failed_this_cycle field + write_summary section.
Deliverable 2: ALERT_THRESHOLD_SINGLE_DOMAIN_FAILURES alert flag rule.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grantglobe_crawler.qa.qa_reporter import QAReporter

_RUN_DATE = "2026-05-23"


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------

def _settings(single_failure_threshold: int = 1) -> dict:
    return {
        "QA_GRANT_RELEVANCE_MIN_RATIO": 0.20,
        "QA_PDF_SUCCESS_MIN_RATE": 0.80,
        "QA_HIGH_CHANGE_THRESHOLD": 0.30,
        "ALERT_THRESHOLD_DOMAIN_FAILURE_RATE": 0.20,
        "ALERT_THRESHOLD_CAPTCHA_BLOCKED_DOMAINS": 10,
        "ALERT_THRESHOLD_ZERO_GRANT_PAGES_DOMAINS": 30,
        "ALERT_THRESHOLD_SINGLE_DOMAIN_FAILURES": single_failure_threshold,
    }


def _make_reporter(tmp_path: Path, *, single_failure_threshold: int = 1) -> QAReporter:
    return QAReporter(raw_cache_dir=tmp_path, settings=_settings(single_failure_threshold))


def _failed_stats() -> dict:
    return {
        "pages_crawled": 0,
        "pdfs_found": 0,
        "pdf_extraction_failures": 0,
        "grant_relevant_pages": 0,
        "changed_pages": 0,
        "captcha_blocks": 0,
        "http_errors": {"502": 3},
        "crawl_status": "failed",
    }


def _complete_stats() -> dict:
    return {
        "pages_crawled": 50,
        "pdfs_found": 5,
        "pdf_extraction_failures": 0,
        "grant_relevant_pages": 15,
        "changed_pages": 10,
        "captcha_blocks": 0,
        "http_errors": {},
        "crawl_status": "complete",
    }


# ---------------------------------------------------------------------------
# Deliverable 1: domains_failed_this_cycle field
# ---------------------------------------------------------------------------


class TestDomainsFailedThisCycleField:
    def test_failed_domains_listed_in_report(self, tmp_path):
        """domains_failed_this_cycle contains exactly the domains with status 'failed'."""
        reporter = _make_reporter(tmp_path)
        stats = {
            "good.org": _complete_stats(),
            "bad1.org": _failed_stats(),
            "bad2.org": _failed_stats(),
        }
        report = reporter.generate_report(_RUN_DATE, stats)

        failed = report["domains_failed_this_cycle"]
        assert isinstance(failed, list)
        assert set(failed) == {"bad1.org", "bad2.org"}
        assert "good.org" not in failed

    def test_failed_list_is_sorted(self, tmp_path):
        """domains_failed_this_cycle is sorted alphabetically."""
        reporter = _make_reporter(tmp_path)
        stats = {
            "z-last.org": _failed_stats(),
            "a-first.org": _failed_stats(),
            "m-middle.org": _failed_stats(),
        }
        report = reporter.generate_report(_RUN_DATE, stats)
        assert report["domains_failed_this_cycle"] == sorted(
            ["z-last.org", "a-first.org", "m-middle.org"]
        )

    def test_empty_when_no_failures(self, tmp_path):
        """domains_failed_this_cycle is an empty list when all domains succeed."""
        reporter = _make_reporter(tmp_path)
        stats = {"ok1.org": _complete_stats(), "ok2.org": _complete_stats()}
        report = reporter.generate_report(_RUN_DATE, stats)
        assert report["domains_failed_this_cycle"] == []


# ---------------------------------------------------------------------------
# Deliverable 2: ALERT_THRESHOLD_SINGLE_DOMAIN_FAILURES alert rule
# ---------------------------------------------------------------------------


class TestSingleDomainFailureAlert:
    def test_alert_fires_when_one_domain_fails_and_threshold_is_one(self, tmp_path):
        """Single failed domain triggers HIGH alert when threshold == 1."""
        reporter = _make_reporter(tmp_path, single_failure_threshold=1)
        stats = {"fail.org": _failed_stats(), "ok.org": _complete_stats()}
        report = reporter.generate_report(_RUN_DATE, stats)

        matching = [f for f in report["alert_flags"] if "domain(s) failed this cycle" in f]
        assert len(matching) == 1
        assert "1 domain(s) failed this cycle" in matching[0]
        assert "fail.org" in matching[0]

    def test_alert_prefixed_high(self, tmp_path):
        """The single-failure alert has the 'HIGH:' severity prefix."""
        reporter = _make_reporter(tmp_path, single_failure_threshold=1)
        stats = {"x.org": _failed_stats()}
        report = reporter.generate_report(_RUN_DATE, stats)

        matching = [f for f in report["alert_flags"] if "domain(s) failed this cycle" in f]
        assert matching[0].startswith("HIGH:")

    def test_no_alert_when_no_failures(self, tmp_path):
        """No single-failure alert when domains_failed_this_cycle is empty."""
        reporter = _make_reporter(tmp_path, single_failure_threshold=1)
        stats = {"ok.org": _complete_stats()}
        report = reporter.generate_report(_RUN_DATE, stats)

        assert not any("failed this cycle" in f for f in report["alert_flags"])

    def test_high_threshold_suppresses_alert(self, tmp_path):
        """With threshold=5, a single failure does NOT trigger the alert."""
        reporter = _make_reporter(tmp_path, single_failure_threshold=5)
        stats = {"fail.org": _failed_stats(), "ok.org": _complete_stats()}
        report = reporter.generate_report(_RUN_DATE, stats)

        assert not any("failed this cycle" in f for f in report["alert_flags"])

    def test_single_failure_alert_appears_before_critical_alert(self, tmp_path):
        """HIGH single-failure alert is ordered before CRITICAL failure-rate alert."""
        reporter = _make_reporter(tmp_path, single_failure_threshold=1)
        # 5 failed out of 10 → 50 % > 20 % threshold → also triggers CRITICAL
        stats = {f"fail{i}.org": _failed_stats() for i in range(5)}
        stats.update({f"ok{i}.org": _complete_stats() for i in range(5)})
        report = reporter.generate_report(_RUN_DATE, stats)

        flags = report["alert_flags"]
        high_idx = next(
            (i for i, f in enumerate(flags) if "failed this cycle" in f), None
        )
        critical_idx = next(
            (i for i, f in enumerate(flags) if f.startswith("CRITICAL")), None
        )
        assert high_idx is not None
        assert critical_idx is not None
        assert high_idx < critical_idx, (
            "Single-failure HIGH alert must appear before CRITICAL failure-rate alert"
        )


# ---------------------------------------------------------------------------
# Deliverable 1: write_summary section for failed domains
# ---------------------------------------------------------------------------


class TestSummaryFailedDomainsSection:
    def _get_summary_text(self, tmp_path: Path, stats: dict, threshold: int = 1) -> str:
        reporter = _make_reporter(tmp_path, single_failure_threshold=threshold)
        report = reporter.generate_report(_RUN_DATE, stats)
        reporter.write_summary(report)
        summary_file = tmp_path / f"crawl_summary_{_RUN_DATE}.txt"
        return summary_file.read_text(encoding="utf-8")

    def test_section_present_when_failures_exist(self, tmp_path):
        """Failed domains section header appears in summary when domains failed."""
        stats = {"fail.org": _failed_stats(), "ok.org": _complete_stats()}
        text = self._get_summary_text(tmp_path, stats)
        assert "Domains not updated this cycle (crawl failed)" in text

    def test_failed_domain_listed_in_section(self, tmp_path):
        """Each failed domain is listed with the 'zero pages fetched' reason."""
        stats = {"fail.org": _failed_stats()}
        text = self._get_summary_text(tmp_path, stats)
        assert "fail.org" in text
        assert "zero pages fetched" in text

    def test_none_message_when_no_failures(self, tmp_path):
        """'Domains not updated this cycle: none' appears when all domains complete."""
        stats = {"ok.org": _complete_stats()}
        text = self._get_summary_text(tmp_path, stats)
        assert "Domains not updated this cycle: none" in text

    def test_section_always_present(self, tmp_path):
        """The section header always appears — even with zero domains — so operators
        know the check was performed."""
        reporter = _make_reporter(tmp_path)
        report = reporter.generate_report(_RUN_DATE, {})
        reporter.write_summary(report)
        text = (tmp_path / f"crawl_summary_{_RUN_DATE}.txt").read_text(encoding="utf-8")
        # Either form of the header must be present.
        assert (
            "Domains not updated this cycle: none" in text
            or "Domains not updated this cycle (crawl failed)" in text
        )

    def test_failed_section_appears_before_alerts_section(self, tmp_path):
        """The failed-domain section is written before the ALERTS section."""
        stats = {"fail.org": _failed_stats()}
        text = self._get_summary_text(tmp_path, stats)
        not_updated_pos = text.find("Domains not updated this cycle")
        alerts_pos = text.find("── ALERTS")
        assert not_updated_pos != -1
        assert alerts_pos != -1
        assert not_updated_pos < alerts_pos, (
            "'Domains not updated this cycle' section must precede the ALERTS section"
        )
