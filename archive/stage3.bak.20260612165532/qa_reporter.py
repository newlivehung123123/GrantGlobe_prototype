"""
QA Reporter — writes per-cycle extraction metrics to JSON and fires WARNING logs
for conditions that require operator attention.

Output file: {STAGE3_OUTPUT_DIR}/extraction_report_{YYYY-MM-DD}.json
"""

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Default report skeleton (§11)
# ---------------------------------------------------------------------------

_REPORT_DEFAULTS: dict = {
    "report_date": "",
    "pages_processed": 0,
    "pages_skipped_unchanged": 0,
    "pages_skipped_content_too_short": 0,
    "pages_failed": 0,
    "pages_empty_extraction": 0,
    "records_extracted_total": 0,
    "records_inserted_new": 0,
    "records_updated_higher_confidence": 0,
    "records_duplicate_lower_confidence": 0,
    "records_flagged_review": 0,
    "fields_others_frequency": {},
    "domains_zero_extraction": [],
    "average_confidence_by_field": {},
    "extraction_cost_estimate_usd": 0.0,
}

# Alert thresholds (§11)
_FAILURE_RATE_THRESHOLD = 0.05
_OTHERS_FREQUENCY_THRESHOLD = 0.15


# ---------------------------------------------------------------------------
# Alert helpers
# ---------------------------------------------------------------------------


def _check_consecutive_zero_extraction(
    output_dir: Path,
    run_date_str: str,
    domains: list[str],
) -> list[str]:
    """Return domains that appear in domains_zero_extraction for two consecutive
    cycles (current cycle + the most recent prior report found in output_dir)."""
    if not domains:
        return []

    current_name = f"extraction_report_{run_date_str}.json"
    prior_reports = sorted(
        p for p in output_dir.glob("extraction_report_*.json")
        if p.name != current_name
    )
    if not prior_reports:
        return []

    try:
        prev_data = json.loads(prior_reports[-1].read_text(encoding="utf-8"))
        prev_zero = set(prev_data.get("domains_zero_extraction", []))
        return sorted(set(domains) & prev_zero)
    except (json.JSONDecodeError, OSError):
        return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def write_extraction_report(
    stats: dict,
    run_date: str | date,
    output_dir: str | Path | None = None,
) -> Path:
    """Build and write the §11 extraction QA report to disk.

    Args:
        stats: Dict of metric values to include.  Any key absent from *stats*
            falls back to the schema default (0 / [] / {}).  Unknown keys in
            *stats* are preserved verbatim.
        run_date: The extraction run date (ISO-8601 string or ``datetime.date``).
        output_dir: Directory to write the report into.  Reads from the
            ``STAGE3_OUTPUT_DIR`` environment variable when ``None``.

    Returns:
        ``Path`` to the written JSON file.

    Raises:
        ValueError: If ``output_dir`` is ``None`` and ``STAGE3_OUTPUT_DIR`` is
            not set.
    """
    if output_dir is None:
        raw = os.environ.get("STAGE3_OUTPUT_DIR")
        if not raw:
            raise ValueError(
                "output_dir is required: pass it explicitly or set STAGE3_OUTPUT_DIR"
            )
        output_dir = raw

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    date_str = run_date.isoformat() if isinstance(run_date, date) else str(run_date)

    # Merge caller-supplied stats over the schema defaults.
    report: dict = {**_REPORT_DEFAULTS, **stats, "report_date": date_str}

    # ── Write JSON ────────────────────────────────────────────────────────
    report_path = out_path / f"extraction_report_{date_str}.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    log.info(
        "qa_report_written",
        path=str(report_path),
        pages_processed=report.get("pages_processed", 0),
        records_extracted=report.get("records_extracted_total", 0),
    )

    # ── Alert conditions (§11) ────────────────────────────────────────────

    # Alert 1: failure rate > 5 %
    pages_processed: int = report.get("pages_processed", 0)
    pages_failed: int = report.get("pages_failed", 0)
    if pages_processed > 0 and (pages_failed / pages_processed) > _FAILURE_RATE_THRESHOLD:
        log.warning(
            "high_page_failure_rate",
            pages_failed=pages_failed,
            pages_processed=pages_processed,
            rate=round(pages_failed / pages_processed, 3),
        )

    # Alert 2: domains with zero extraction for two consecutive cycles
    zero_domains: list[str] = report.get("domains_zero_extraction", [])
    consecutive = _check_consecutive_zero_extraction(out_path, date_str, zero_domains)
    if consecutive:
        log.warning(
            "domains_consecutive_zero_extraction",
            domains=consecutive,
        )

    # Alert 3: any field's Others frequency exceeds 15 %
    for field, freq in report.get("fields_others_frequency", {}).items():
        if freq > _OTHERS_FREQUENCY_THRESHOLD:
            log.warning(
                "high_others_frequency",
                field=field,
                frequency=round(freq, 3),
            )

    return report_path
