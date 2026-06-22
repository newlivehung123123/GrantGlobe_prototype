#!/usr/bin/env python3
"""
validation.py — automated per-build accuracy validation for GrantGlobe.

Runs on EVERY export, over EVERY record from EVERY connector, and checks all
five user-facing fields (title, funder, deadline, amount, link) for the classes
of contamination that have actually occurred:

  • title    — empty, leftover HTML markup/entities, implausibly short
  • funder   — empty, generic placeholder, identical to the title
  • deadline — already passed, malformed, or a far-future "sentinel" date
  • amount   — non-positive, min > max, missing currency, or so large it is
               almost certainly a total programme pool rather than a per-award max
  • link     — missing or non-https

Two severities:
  ERROR → definitive bad data; the record is DROPPED from the live export.
  WARN  → suspicious but uncertain; the record is KEPT, annotated with
          `_validation_warnings`, and counted in the per-connector report so a
          human can review it. (We never silently show known-bad data, and never
          silently drop merely-suspicious data.)

This is deliberately a NO-NETWORK, deterministic pass so it can run on all
records on every build without being slow or false-dropping records whose
funder sites are bot-protected or JS-rendered. Link *liveness* (HTTP 404
detection) is handled separately in export_grants.py.

Pure-Python, no third-party deps, so it imports cleanly in the GitHub Action.
"""

from __future__ import annotations

import datetime
import re
from collections import Counter, defaultdict

# Per-applicant award maxes above this USD-equivalent are almost certainly a
# total programme pool, not a single-applicant maximum → flagged for review.
# Set generously so genuinely large per-award grants (e.g. NIFA infrastructure
# ceilings ~$30M) are not flagged.
AMOUNT_POOL_CEILING_USD = 75_000_000

# Deadlines further out than this are almost always sentinel/placeholder values
# (or, for funded-project feeds, project end dates) rather than real due dates.
DEADLINE_SENTINEL_DAYS = 4 * 365

_FX_USD: dict[str, float] = {
    "USD": 1.00, "EUR": 1.08, "GBP": 1.27, "CHF": 1.10, "CAD": 0.73, "AUD": 0.66,
    "NZD": 0.61, "JPY": 0.0067, "CNY": 0.14, "HKD": 0.128, "SGD": 0.74,
    "KRW": 0.00073, "INR": 0.012, "SEK": 0.095, "NOK": 0.094, "DKK": 0.145,
    "PLN": 0.25, "CZK": 0.043, "ZAR": 0.054, "BRL": 0.18, "MXN": 0.058,
    "ILS": 0.27, "AED": 0.27, "SAR": 0.27, "TWD": 0.031,
}

_ENTITY_RE = re.compile(r"&[a-zA-Z]+;|&#\d+;")
_TAG_RE = re.compile(r"<[^>]+>")
_GENERIC_FUNDERS = {"", "unknown", "n/a", "na", "tbd", "tba", "various", "see website"}


def _to_usd(amount: float, currency: str | None) -> float:
    return float(amount) * _FX_USD.get((currency or "USD").upper(), 1.0)


def check_record(g: dict, today: datetime.date) -> list[tuple[str, str, str, str]]:
    """Return a list of (severity, field, code, detail) issues for one record."""
    issues: list[tuple[str, str, str, str]] = []

    # ── Title ────────────────────────────────────────────────────────────
    title = (g.get("grant_title") or "").strip()
    if not title:
        issues.append(("error", "title", "missing", ""))
    else:
        if _TAG_RE.search(title) or _ENTITY_RE.search(title):
            issues.append(("error", "title", "markup", title[:50]))
        if len(title) < 6:
            issues.append(("warn", "title", "too_short", title))

    # ── Funder ───────────────────────────────────────────────────────────
    funder = (g.get("funder_name") or "").strip()
    if funder.lower() in _GENERIC_FUNDERS:
        issues.append(("warn" if funder else "error", "funder", "generic_or_missing", funder))
    if title and funder and title.lower() == funder.lower():
        issues.append(("warn", "funder", "equals_title", funder[:50]))

    # ── Link ─────────────────────────────────────────────────────────────
    url = g.get("application_portal_url") or g.get("source_url") or ""
    if not url:
        issues.append(("error", "link", "missing", ""))
    elif not url.startswith("https://"):
        issues.append(("warn", "link", "not_https", url[:60]))
    # Liveness probe (set in export_grants._verify_grant) returned a 404 for an
    # authoritative-feed URL — likely a closed/removed opportunity, but possibly
    # a transient bot-block, so it's flagged for review rather than dropped.
    if g.get("_liveness_404"):
        issues.append(("warn", "link", "liveness_404", url[:60]))

    # ── Deadline ─────────────────────────────────────────────────────────
    deadline = g.get("application_deadline")
    if deadline:
        try:
            d = datetime.date.fromisoformat(str(deadline)[:10])
            if d < today:
                issues.append(("error", "deadline", "past", str(deadline)))
            elif (d - today).days > DEADLINE_SENTINEL_DAYS:
                issues.append(("warn", "deadline", "sentinel_like", str(deadline)))
        except (ValueError, TypeError):
            issues.append(("error", "deadline", "malformed", str(deadline)))

    # ── Amount ───────────────────────────────────────────────────────────
    fmax = g.get("funding_amount_max")
    fmin = g.get("funding_amount_min")
    if fmax is not None:
        try:
            if float(fmax) <= 0:
                issues.append(("error", "amount", "nonpositive", str(fmax)))
            elif _to_usd(float(fmax), g.get("currency")) > AMOUNT_POOL_CEILING_USD:
                issues.append(("warn", "amount", "possible_pool",
                               f"{g.get('currency') or ''}{int(float(fmax))}"))
        except (ValueError, TypeError):
            issues.append(("error", "amount", "non_numeric_max", str(fmax)))
    if fmax is not None and fmin is not None:
        try:
            if float(fmin) > float(fmax):
                issues.append(("warn", "amount", "min_gt_max", f"{fmin} > {fmax}"))
        except (ValueError, TypeError):
            pass
    if (fmax is not None or fmin is not None) and not g.get("currency"):
        issues.append(("warn", "amount", "no_currency", ""))

    return issues


def validate(
    grants: list[dict],
    today: datetime.date | None = None,
    drop_errors: bool = True,
) -> tuple[list[dict], list[dict], dict]:
    """Validate every record. Returns (kept, dropped, report).

    ERROR records are dropped (when drop_errors); WARN records are kept and
    annotated with `_validation_warnings`. The report summarises issue counts
    by field/code and by connector, with a few examples per issue type.
    """
    today = today or datetime.date.today()
    kept: list[dict] = []
    dropped: list[dict] = []

    by_code: Counter = Counter()
    by_connector: defaultdict = defaultdict(Counter)
    examples: defaultdict = defaultdict(list)
    error_total = warn_total = 0

    for g in grants:
        issues = check_record(g, today)
        errors = [i for i in issues if i[0] == "error"]
        warns = [i for i in issues if i[0] == "warn"]
        domain = g.get("domain") or "unknown"

        for sev, field, code, detail in issues:
            key = f"{sev}:{field}:{code}"
            by_code[key] += 1
            by_connector[domain][key] += 1
            if len(examples[key]) < 3:
                examples[key].append({
                    "domain": domain,
                    "title": (g.get("grant_title") or "")[:70],
                    "detail": detail,
                })

        error_total += len(errors)
        warn_total += len(warns)

        if errors and drop_errors:
            g["_validation_errors"] = [f"{f}:{c}" for _, f, c, _ in errors]
            dropped.append(g)
        else:
            if warns:
                g["_validation_warnings"] = [f"{f}:{c}" for _, f, c, _ in warns]
            kept.append(g)

    report = {
        "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "records_checked": len(grants),
        "records_kept": len(kept),
        "records_dropped": len(dropped),
        "error_count": error_total,
        "warn_count": warn_total,
        "issues_by_code": dict(by_code.most_common()),
        "issues_by_connector": {d: dict(c.most_common()) for d, c in sorted(by_connector.items())},
        "examples": {k: examples[k] for k in by_code},
    }
    return kept, dropped, report


def print_summary(report: dict) -> None:
    """Print a concise per-build validation scorecard to the build log."""
    print(f"  Validation: checked {report['records_checked']} records — "
          f"{report['records_dropped']} dropped (errors), "
          f"{report['warn_count']} warnings flagged.")
    if report["issues_by_code"]:
        print("    Issues by type:")
        for code, n in report["issues_by_code"].items():
            print(f"      {n:5}  {code}")
