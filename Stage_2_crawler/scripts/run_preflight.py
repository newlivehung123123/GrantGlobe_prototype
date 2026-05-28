#!/usr/bin/env python3
"""
GrantGlobe Stage 2 — standalone pre-flight runner.

Wraps ``grantglobe_crawler.preflight.preflight.run_preflight`` with a
command-line interface for operator use.

Usage
-----
    python scripts/run_preflight.py [--domain DOMAIN] [--csv PATH] [--dry-run]

Arguments
---------
--domain DOMAIN
    Run pre-flight for a single domain only.  DOMAIN must match a value in
    the 'domain' column of the source-list CSV exactly.
--csv PATH
    Path to the source_list CSV file.  Overrides settings.SOURCE_LIST_CSV.
--dry-run
    Print what would be done without writing any crawl_manifest.json files.
--help
    Show this help message and exit.

Output
------
One line per domain::

    [OK]    undp.org — profile=A, rss=yes
    [WARN]  example.org — profile=B, slow=yes
    [ERROR] broken.org — Connection refused

Final summary line::

    Summary: 582 domains checked, 3 warnings, 1 errors

Exit codes
----------
0: all domains completed successfully (OK or WARN)
1: one or more domains failed with an unhandled exception, or scrapy not installed

Requirements
------------
Scrapy must be installed.  Run from the project root so that
``grantglobe_crawler`` is importable, or ensure the project root is on
``sys.path``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Make the project root importable when the script is run directly.
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPTS_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Scrapy import — fail fast with a clear message if not installed.
# ---------------------------------------------------------------------------
try:
    from scrapy.utils.project import get_project_settings as _get_project_settings
except ImportError:
    print(
        "ERROR: scrapy is not installed.\n"
        "Install all dependencies with:\n"
        "    pip install -r requirements.txt",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Preflight imports
# ---------------------------------------------------------------------------
from grantglobe_crawler.preflight.preflight import (
    SeedRow,
    _MAX_WORKERS,
    _PROBE_UA,
    _run_domain_preflight,
    load_source_list,
    run_preflight,
)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="run_preflight.py",
        description="GrantGlobe Stage 2 — pre-flight domain assessment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Usage\n-----")[0].strip(),
    )
    ap.add_argument(
        "--domain",
        metavar="DOMAIN",
        default=None,
        help="Run pre-flight for one domain only (must match 'domain' column exactly).",
    )
    ap.add_argument(
        "--csv",
        metavar="PATH",
        default=None,
        help="Path to source_list CSV (overrides settings.SOURCE_LIST_CSV).",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned actions without writing any manifest files.",
    )
    return ap.parse_args()


def main() -> None:
    args = _parse_args()

    # ── Load Scrapy project settings ──────────────────────────────────────
    settings = _get_project_settings()

    csv_path: str = args.csv or settings.get("SOURCE_LIST_CSV", "")
    raw_cache_dir: str = settings.get("RAW_CACHE_DIR", "raw_cache")
    bot_headers: list[str] = settings.getlist(
        "BOT_PROTECTION_HEADERS", ["cf-ray", "x-sucuri-id"]
    )
    slow_threshold: float = settings.getfloat(
        "PREFLIGHT_SLOW_DOMAIN_THRESHOLD_S", 5.0
    )

    if not csv_path:
        print(
            "ERROR: No CSV path configured.\n"
            "Pass --csv PATH or set SOURCE_LIST_CSV in .env.",
            file=sys.stderr,
        )
        sys.exit(1)

    csv_file = Path(csv_path)
    if not csv_file.exists():
        print(f"ERROR: CSV file not found: {csv_file}", file=sys.stderr)
        sys.exit(1)

    # ── Load and optionally filter the source list ────────────────────────
    all_rows: list[SeedRow] = load_source_list(csv_file)

    if args.domain:
        rows = [r for r in all_rows if r.domain == args.domain]
        if not rows:
            print(
                f"ERROR: Domain '{args.domain}' not found in CSV.\n"
                "Check the value matches the 'domain' column exactly.",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        rows = all_rows

    # ── Dry-run: describe what would happen and exit ──────────────────────
    if args.dry_run:
        print(
            f"DRY RUN — would run pre-flight for {len(rows)} domain(s) "
            f"from {csv_file.name}"
        )
        print(f"  Cache directory: {Path(raw_cache_dir).resolve()}")
        print()
        for row in rows:
            manifest_path = Path(raw_cache_dir) / row.domain / "crawl_manifest.json"
            print(f"  [{row.id:>4}] {row.domain}")
            print(f"         seed_url : {row.grants_url}")
            print(f"         would write: {manifest_path}")
        print()
        print(f"Dry run complete — no manifest files were written.")
        return

    # ── Live run ──────────────────────────────────────────────────────────
    warnings = 0
    errors = 0

    if args.domain:
        # Single-domain mode: call the internal per-domain function directly.
        row = rows[0]
        try:
            manifest = _run_domain_preflight(
                row,
                Path(raw_cache_dir),
                bot_headers,
                slow_threshold,
            )
            status, findings = _classify_manifest(manifest)
            if status == "WARN":
                warnings += 1
            print(f"[{status:5}] {row.domain} — {', '.join(findings)}")
        except Exception as exc:
            errors += 1
            print(f"[ERROR] {row.domain} — {exc}")

    else:
        # All-domains mode: delegate to run_preflight() which handles concurrency.
        try:
            results: list[dict] = run_preflight(
                source_list_csv=csv_file,
                raw_cache_dir=raw_cache_dir,
                max_workers=_MAX_WORKERS,
            )
        except Exception as exc:
            print(f"ERROR: run_preflight raised: {exc}", file=sys.stderr)
            sys.exit(1)

        # Build a lookup of manifests by domain for summary printing.
        manifests_by_domain: dict[str, dict] = {
            m.get("domain", ""): m for m in results
        }

        for row in rows:
            manifest = manifests_by_domain.get(row.domain)
            if manifest is None:
                # Domain was not in the returned results → it failed.
                errors += 1
                print(f"[ERROR] {row.domain} — no manifest returned (pre-flight failed)")
                continue

            status, findings = _classify_manifest(manifest)
            if status == "WARN":
                warnings += 1
            print(f"[{status:5}] {row.domain} — {', '.join(findings)}")

    # ── Final summary ─────────────────────────────────────────────────────
    print()
    print(
        f"Summary: {len(rows)} domain(s) checked, "
        f"{warnings} warning(s), {errors} error(s)"
    )

    if errors:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Manifest classifier — produces the one-line per-domain summary
# ---------------------------------------------------------------------------


def _classify_manifest(manifest: dict) -> tuple[str, list[str]]:
    """
    Classify a completed manifest and return ``(status, findings)`` where:

    - ``status`` is one of ``"OK"``, ``"WARN"``, ``"ERROR"``
    - ``findings`` is a list of short descriptive strings

    Criteria for WARN:
    - Slow domain (response time > PREFLIGHT_SLOW_DOMAIN_THRESHOLD_S)
    - HTTP status is not 200 (but not a hard error)
    - Bot-protection headers detected
    - crawl_profile is "D" (bot-protected; manifest written, but proxy required
      before the first crawl run)

    Criteria for ERROR:
    - probe_error is set (connection failure, timeout, SSL error); in this case
      the manifest may not have been written or may be incomplete.
    """
    findings: list[str] = []
    status = "OK"

    profile = manifest.get("crawl_profile", "?")
    findings.append(f"profile={profile}")

    if profile == "D":
        status = "WARN"
        findings.append("bot-protected")

    if manifest.get("rss_feed_url"):
        findings.append("rss=yes")

    if manifest.get("sitemap_url"):
        findings.append("sitemap=yes")

    if manifest.get("slow_domain"):
        findings.append(
            f"slow={manifest.get('response_time_seconds', 0):.1f}s"
        )
        if status == "OK":
            status = "WARN"

    bot_headers = manifest.get("bot_protection_headers", [])
    if bot_headers:
        findings.append(f"bot_headers={','.join(bot_headers)}")
        if status == "OK":
            status = "WARN"

    http_status = manifest.get("http_status", 200)
    if http_status and http_status not in (200, 206):
        findings.append(f"http={http_status}")
        if status == "OK":
            status = "WARN"

    probe_error = manifest.get("probe_error")
    if probe_error:
        # Truncate long error messages for readability.
        short_error = str(probe_error)[:60]
        findings.append(f"error={short_error}")
        status = "ERROR"

    return status, findings


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    main()
