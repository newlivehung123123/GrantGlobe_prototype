"""
QA Reporter — automated quality assurance and coverage reporting.

Implements spec §2.7 Quality Assurance and Coverage Reporting.

``QAReporter`` is a standalone class — not a Scrapy pipeline.  It is called
by the spider's ``spider_closed`` handler and may also be invoked from the
command line for ad-hoc reporting against an existing raw_cache directory.

Output files:
  raw_cache/crawl_report_{date}.json   — machine-readable, consumed by Stage 3
  raw_cache/crawl_summary_{date}.txt   — human-readable for operator review

Report schema and alert thresholds follow spec §2.7 and §2.8 exactly.

Usage::

    from grantglobe_crawler.qa.qa_reporter import QAReporter

    reporter = QAReporter(raw_cache_dir, settings)
    report = reporter.generate_report(run_date, domain_stats)
    reporter.write_report(report)
    reporter.write_summary(report)
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


class QAReporter:
    """
    Generate and write QA reports for one crawl cycle.

    Parameters
    ----------
    raw_cache_dir:
        Root of the structured content cache (``raw_cache/``).
        Report files are written here by default.
    settings:
        Scrapy settings object **or** any dict-like object supporting
        ``.get(key, default)``.  Used to read QA thresholds.
    """

    def __init__(self, raw_cache_dir: str | Path, settings) -> None:
        self._raw_cache_dir = Path(raw_cache_dir)
        self._settings = settings

    # ------------------------------------------------------------------
    # Core report generation
    # ------------------------------------------------------------------

    def generate_report(
        self,
        run_date: str,
        domain_stats: dict[str, dict],
    ) -> dict:
        """
        Generate a QA report for one crawl cycle.

        Parameters
        ----------
        run_date:
            ``YYYY-MM-DD`` string for the cycle being reported.
        domain_stats:
            ``{domain: stats_dict}``.  Each stats dict should contain:

            .. code-block:: python

               {
                 "pages_crawled": int,
                 "pdfs_found": int,
                 "pdf_extraction_failures": int,
                 "grant_relevant_pages": int,
                 "changed_pages": int,
                 "captcha_blocks": int,
                 "http_errors": {str: int},
                 "crawl_status": str,   # "complete"|"failed"|"dead_domain_candidate"
               }

        Returns
        -------
        dict
            Full QA report dict conforming to spec §2.7 schema.
        """
        s = self._settings
        total_domains = len(domain_stats)

        # ── Aggregate counts ──────────────────────────────────────────────
        domains_complete = sum(
            1 for d in domain_stats.values() if d.get("crawl_status") == "complete"
        )
        domains_failed = sum(
            1 for d in domain_stats.values() if d.get("crawl_status") == "failed"
        )
        domains_dead = sum(
            1
            for d in domain_stats.values()
            if d.get("crawl_status") == "dead_domain_candidate"
        )

        total_pages = sum(d.get("pages_crawled", 0) for d in domain_stats.values())
        total_pdfs = sum(d.get("pdfs_found", 0) for d in domain_stats.values())
        total_pdf_failures = sum(
            d.get("pdf_extraction_failures", 0) for d in domain_stats.values()
        )
        total_grant_relevant = sum(
            d.get("grant_relevant_pages", 0) for d in domain_stats.values()
        )
        total_changed = sum(d.get("changed_pages", 0) for d in domain_stats.values())
        total_captcha = sum(d.get("captcha_blocks", 0) for d in domain_stats.values())

        # ── Derived rates (ZeroDivisionError-safe) ────────────────────────
        pdf_failure_rate = (
            total_pdf_failures / total_pdfs if total_pdfs > 0 else 0.0
        )
        grant_relevance_rate = (
            total_grant_relevant / total_pages if total_pages > 0 else 0.0
        )

        # ── Read thresholds from settings ─────────────────────────────────
        grant_min_ratio = float(s.get("QA_GRANT_RELEVANCE_MIN_RATIO", 0.20))
        pdf_success_min = float(s.get("QA_PDF_SUCCESS_MIN_RATE", 0.80))
        high_change_threshold = float(s.get("QA_HIGH_CHANGE_THRESHOLD", 0.30))
        failure_rate_threshold = float(s.get("ALERT_THRESHOLD_DOMAIN_FAILURE_RATE", 0.20))
        captcha_block_threshold = int(s.get("ALERT_THRESHOLD_CAPTCHA_BLOCKED_DOMAINS", 10))
        zero_grant_threshold = int(s.get("ALERT_THRESHOLD_ZERO_GRANT_PAGES_DOMAINS", 30))

        pdf_failure_threshold = 1.0 - pdf_success_min  # fail rate that triggers alert

        # ── Per-domain alert lists ────────────────────────────────────────
        domains_below_relevance: list[str] = [
            domain
            for domain, stats in domain_stats.items()
            if stats.get("pages_crawled", 0) > 0
            and (
                stats.get("grant_relevant_pages", 0) / stats["pages_crawled"]
                < grant_min_ratio
            )
        ]

        domains_high_pdf_failure: list[str] = [
            domain
            for domain, stats in domain_stats.items()
            if stats.get("pdfs_found", 0) > 0
            and (
                stats.get("pdf_extraction_failures", 0) / stats["pdfs_found"]
                > pdf_failure_threshold
            )
        ]

        domains_high_change: list[str] = [
            domain
            for domain, stats in domain_stats.items()
            if stats.get("pages_crawled", 0) > 0
            and (
                stats.get("changed_pages", 0) / stats["pages_crawled"]
                > high_change_threshold
            )
        ]

        domains_captcha_blocked: list[str] = [
            domain
            for domain, stats in domain_stats.items()
            if stats.get("captcha_blocks", 0) > 0
        ]

        # New: domains that failed (zero pages) in THIS cycle — per-cycle list
        # that is separate from the three-cycle dead-domain escalation path.
        domains_failed_this_cycle: list[str] = sorted(
            domain
            for domain, stats in domain_stats.items()
            if stats.get("crawl_status") == "failed"
        )

        # ── Alert flags ───────────────────────────────────────────────────
        alert_flags: list[str] = []

        # High: any domain(s) failed this cycle (first-failure notification)
        # spec §2.8: operator must know TODAY when a domain fails, not only
        # after DEAD_DOMAIN_FAILED_CYCLE_THRESHOLD consecutive failures.
        threshold_single = int(s.get("ALERT_THRESHOLD_SINGLE_DOMAIN_FAILURES", 1))
        if len(domains_failed_this_cycle) >= threshold_single:
            failed_list = ", ".join(domains_failed_this_cycle[:10])
            if len(domains_failed_this_cycle) > 10:
                failed_list += f" … (+{len(domains_failed_this_cycle) - 10} more)"
            alert_flags.append(
                f"HIGH: {len(domains_failed_this_cycle)} domain(s) failed this cycle: {failed_list}"
            )

        # High: PDF extraction failure rate
        if pdf_failure_rate > pdf_failure_threshold:
            alert_flags.append(
                f"HIGH: PDF extraction failure rate {pdf_failure_rate:.1%} exceeds threshold"
            )

        # Critical: domain failure rate
        if total_domains > 0 and domains_failed / total_domains > failure_rate_threshold:
            rate = domains_failed / total_domains
            alert_flags.append(
                f"CRITICAL: {domains_failed} domains failed ({rate:.1%} of total)"
            )

        # High: CAPTCHA-blocked domains
        if total_captcha > captcha_block_threshold:
            alert_flags.append(
                f"HIGH: {total_captcha} CAPTCHA-blocked domains this cycle"
            )

        # Medium: domains below grant-relevance threshold
        if len(domains_below_relevance) > zero_grant_threshold:
            alert_flags.append(
                f"MEDIUM: {len(domains_below_relevance)} domains below grant-relevance threshold"
            )

        return {
            "report_date": run_date,
            "total_domains": total_domains,
            "domains_complete": domains_complete,
            "domains_failed": domains_failed,
            "domains_dead_candidate": domains_dead,
            "total_pages_crawled": total_pages,
            "total_pdfs_found": total_pdfs,
            "total_pdf_extraction_failures": total_pdf_failures,
            "pdf_extraction_failure_rate": round(pdf_failure_rate, 6),
            "total_grant_relevant_pages": total_grant_relevant,
            "grant_relevance_rate": round(grant_relevance_rate, 6),
            "total_changed_pages": total_changed,
            "total_captcha_blocks": total_captcha,
            "domains_below_grant_relevance_threshold": sorted(domains_below_relevance),
            "domains_high_pdf_failure": sorted(domains_high_pdf_failure),
            "domains_high_change": sorted(domains_high_change),
            "domains_captcha_blocked": sorted(domains_captcha_blocked),
            "domains_failed_this_cycle": domains_failed_this_cycle,
            "alert_flags": alert_flags,
        }

    # ------------------------------------------------------------------
    # File output
    # ------------------------------------------------------------------

    def write_report(
        self,
        report: dict,
        output_dir: str | Path | None = None,
    ) -> Path:
        """
        Write *report* as a JSON file.

        Always writes to ``{raw_cache_dir}/crawl_report_{date}.json``.
        If *output_dir* is provided, also writes there.

        Returns the primary path written.

        Spec ref: §2.7 Output files — ``crawl_report_{date}.json``.
        """
        run_date = report.get("report_date", "unknown")
        filename = f"crawl_report_{run_date}.json"
        encoded = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")

        self._raw_cache_dir.mkdir(parents=True, exist_ok=True)
        primary = self._raw_cache_dir / filename
        _write_bytes_atomic(primary, encoded)
        logger.info("QA report written to %s", primary)

        if output_dir is not None:
            alt = Path(output_dir) / filename
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            _write_bytes_atomic(alt, encoded)
            logger.info("QA report also written to %s", alt)

        return primary

    def write_summary(
        self,
        report: dict,
        output_dir: str | Path | None = None,
    ) -> Path:
        """
        Write a human-readable plain-text summary of *report*.

        Writes to ``{raw_cache_dir}/crawl_summary_{run_date}.txt``.

        Includes:
        - Overall totals
        - All alert flags
        - Top 5 domains by pages crawled (from report if present)
        - Domain lists for each alert category

        Spec ref: §2.7 Output files — ``crawl_summary_{date}.txt``.
        """
        run_date = report.get("report_date", "unknown")
        lines: list[str] = [
            f"GrantGlobe Crawl QA Summary — {run_date}",
            "=" * 50,
            "",
            "── Domains ─────────────────────────────────────────",
            f"  Total:          {report['total_domains']}",
            f"  Complete:       {report['domains_complete']}",
            f"  Failed:         {report['domains_failed']}",
            f"  Dead candidate: {report['domains_dead_candidate']}",
            "",
            "── Pages ───────────────────────────────────────────",
            f"  Total crawled:  {report['total_pages_crawled']:,}",
            f"  Grant-relevant: {report['total_grant_relevant_pages']:,}"
            f"  ({report['grant_relevance_rate']:.1%})",
            f"  Changed:        {report['total_changed_pages']:,}",
            "",
            "── PDFs ────────────────────────────────────────────",
            f"  Found:          {report['total_pdfs_found']:,}",
            f"  Failures:       {report['total_pdf_extraction_failures']:,}"
            f"  ({report['pdf_extraction_failure_rate']:.1%})",
            "",
            "── CAPTCHA ─────────────────────────────────────────",
            f"  Blocked domains: {report['total_captcha_blocks']}",
        ]

        # Domains not updated this cycle — always present so operators know
        # it was checked, even when everything succeeded.
        failed_this_cycle = report.get("domains_failed_this_cycle", [])
        if failed_this_cycle:
            lines += [
                "",
                "── Domains not updated this cycle (crawl failed) ─────────────",
            ]
            for d in failed_this_cycle:
                lines.append(f"  {d}  |  reason: zero pages fetched")
        else:
            lines += ["", "── Domains not updated this cycle: none ─────────────────"]

        # Alert flags
        flags = report.get("alert_flags", [])
        if flags:
            lines += ["", "── ALERTS ──────────────────────────────────────────"]
            for flag in flags:
                lines.append(f"  ⚠  {flag}")
        else:
            lines += ["", "── ALERTS: none ─────────────────────────────────────"]

        # Per-category domain lists
        for key, label in [
            ("domains_below_grant_relevance_threshold", "Below grant-relevance threshold"),
            ("domains_high_pdf_failure", "High PDF failure rate"),
            ("domains_high_change", "High content change rate"),
            ("domains_captcha_blocked", "CAPTCHA-blocked"),
        ]:
            domain_list = report.get(key, [])
            if domain_list:
                lines += [
                    "",
                    f"── {label} ({len(domain_list)}) ───────────────────────",
                ]
                for d in domain_list[:20]:
                    lines.append(f"  {d}")
                if len(domain_list) > 20:
                    lines.append(f"  … and {len(domain_list) - 20} more")

        lines += ["", "=" * 50, ""]

        text = "\n".join(lines)
        encoded = text.encode("utf-8")

        self._raw_cache_dir.mkdir(parents=True, exist_ok=True)
        filename = f"crawl_summary_{run_date}.txt"
        primary = self._raw_cache_dir / filename
        _write_bytes_atomic(primary, encoded)
        logger.info("QA summary written to %s", primary)

        if output_dir is not None:
            alt = Path(output_dir) / filename
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            _write_bytes_atomic(alt, encoded)

        # Fire-and-forget alert delivery (email + webhook) when alerts are present.
        # The email subject reflects the highest severity present in alert_flags so
        # operators can triage from their inbox without opening the message body:
        #   CRITICAL  →  "GrantGlobe Crawler Alert — CRITICAL"
        #   HIGH      →  "GrantGlobe Crawler Alert — HIGH"
        #   (other)   →  "GrantGlobe Crawler Alert"
        # Imported lazily to avoid a circular import (alert_sender has no
        # dependency on qa_reporter, but both live in the same package tree).
        if flags:
            if any(f.startswith("CRITICAL") for f in flags):
                severity_label = "CRITICAL"
            elif any(f.startswith("HIGH") for f in flags):
                severity_label = "HIGH"
            else:
                severity_label = None

            email_subject = (
                f"GrantGlobe Crawler Alert — {severity_label}"
                if severity_label
                else "GrantGlobe Crawler Alert"
            )

            try:
                from grantglobe_crawler.alerts.alert_sender import (
                    send_email_alert,
                    send_webhook_alert,
                )
                email_ok = send_email_alert(
                    text, self._settings, subject=email_subject
                )
                webhook_ok = send_webhook_alert(text, self._settings)
                logger.debug(
                    "QA summary alert delivery — email=%s webhook=%s",
                    email_ok,
                    webhook_ok,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("QA summary alert delivery failed: %s", exc)

        return primary


# ===========================================================================
# Module-level helpers
# ===========================================================================


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    """Write *data* bytes to *path* atomically (temp-file + rename)."""
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
