"""
Pre-flight assessment module — spec §2.1 Pre-flight checks.

Reads all 582 seed URLs from the Stage 1 source list CSV, probes each one,
runs the robots.txt + sitemap check and the RSS feed detection, classifies
each domain into a crawl profile (A / B / C / D), and writes an initial
``crawl_manifest.json`` under ``raw_cache/{domain}/``.

Run as a standalone script before the first crawl:

    python -m grantglobe_crawler.preflight.preflight

or call ``run_preflight()`` programmatically.

Design notes
------------
- All I/O is synchronous per-domain; concurrency uses ``ThreadPoolExecutor``
  so the OS thread pool handles network I/O without blocking other domains.
- Each domain's probe follows this order:
    1. Range:0-0 probe  → HTTP status, Content-Type, headers, redirect chain,
                          response time, bot-protection detection
    2. Full seed-page GET → HTML for RSS autodiscovery + profile-B heuristic
    3. robots.txt + sitemap  (``robotstxt_parser.py``)
    4. RSS / Atom feed detection  (``rss_checker.py``)
    5. Profile classification  (A / B / C / D)
    6. Write ``crawl_manifest.json``
- Manifests are written atomically using a temp-file rename so a partial
  write never corrupts an existing manifest.
- Existing manifests are loaded and merged (not overwritten) so that fields
  set manually (e.g. ``robots_override: true``) survive a re-run.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from requests.exceptions import RequestException

# ---------------------------------------------------------------------------
# Module-level settings (loaded lazily to support standalone use)
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)

_TIMEOUT_S: float = 30.0
_MAX_WORKERS: int = 16          # concurrent domains; safe for most home/office IPs
_PROBE_UA: str = (
    "GrantGlobe-Preflight/1.0 (pre-flight probe; "
    "contact: admin@grantglobe.io)"
)

# Minimum text length (characters) to consider a page JS-rendered (Profile B
# candidate): if the raw HTML body is shorter than this, assume JS rendering
# is required.
_JS_SPARSE_BODY_THRESHOLD: int = 500

# Keywords in Content-Type that identify a PDF seed URL (Profile C).
_PDF_CONTENT_TYPE_KEYWORDS: tuple[str, ...] = ("application/pdf",)

# Path keywords that hint at a PDF-dominant domain even when the seed URL
# itself is HTML (supplementary Profile C signal).
_PDF_PATH_KEYWORDS: frozenset[str] = frozenset(
    ["publications", "documents", "downloads", "docs", "reports"]
)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ProbeResult:
    """Raw outcome of the Range:0-0 pre-flight HTTP probe."""

    seed_url: str
    final_url: str
    redirect_chain: list[str] = field(default_factory=list)
    http_status: int = 0
    content_type: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    response_time_seconds: float = 0.0
    bot_protection_headers: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class SeedRow:
    """One row from the source list CSV."""

    id: str
    org_name: str
    domain: str
    grants_url: str
    category: str
    region: str


# ---------------------------------------------------------------------------
# CSV reader
# ---------------------------------------------------------------------------


def load_source_list(csv_path: str | Path) -> list[SeedRow]:
    """
    Read the Stage 1 source list CSV and return a list of SeedRow objects.

    Expected columns (at minimum): id, org_name, domain, grants_url.
    Extra columns are ignored.
    """
    rows: list[SeedRow] = []
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            try:
                rows.append(
                    SeedRow(
                        id=raw.get("id", "").strip(),
                        org_name=raw.get("org_name", "").strip(),
                        domain=raw.get("domain", "").strip(),
                        grants_url=raw.get("grants_url", "").strip(),
                        category=raw.get("category", "").strip(),
                        region=raw.get("region", "").strip(),
                    )
                )
            except Exception as exc:
                logger.warning("Skipping malformed CSV row: %s — %s", raw, exc)
    logger.info("Loaded %d seed URLs from %s", len(rows), csv_path)
    return rows


# ---------------------------------------------------------------------------
# HTTP probe
# ---------------------------------------------------------------------------


def _range_probe(seed_url: str, bot_protection_headers: list[str]) -> ProbeResult:
    """
    Issue a GET request with ``Range: bytes=0-0`` to *seed_url*.

    Records: HTTP status, Content-Type, redirect chain, response time, and
    the presence of any bot-protection headers listed in
    ``settings.BOT_PROTECTION_HEADERS``.
    Spec ref: §2.1 Pre-flight checks.
    """
    headers = {
        "User-Agent": _PROBE_UA,
        "Range": "bytes=0-0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    t0 = time.monotonic()
    try:
        resp = requests.get(
            seed_url,
            headers=headers,
            allow_redirects=True,
            timeout=_TIMEOUT_S,
            stream=True,  # avoid downloading a large body we don't need
        )
        elapsed = time.monotonic() - t0
        # Only read a small amount of the body; we don't need the full content.
        resp.close()

        redirect_chain = [r.url for r in resp.history]
        resp_headers_lower = {k.lower(): v for k, v in resp.headers.items()}
        detected_bot = [
            h for h in bot_protection_headers if h.lower() in resp_headers_lower
        ]

        return ProbeResult(
            seed_url=seed_url,
            final_url=resp.url,
            redirect_chain=redirect_chain,
            http_status=resp.status_code,
            content_type=resp.headers.get("Content-Type", ""),
            headers=dict(resp.headers),
            response_time_seconds=round(elapsed, 3),
            bot_protection_headers=detected_bot,
        )
    except RequestException as exc:
        elapsed = time.monotonic() - t0
        return ProbeResult(
            seed_url=seed_url,
            final_url=seed_url,
            response_time_seconds=round(elapsed, 3),
            error=str(exc),
        )


def _fetch_seed_html(url: str) -> str | None:
    """
    Fetch the full HTML body of *url* (needed for RSS autodiscovery and
    JS-sparseness heuristic).  Returns None on any error.
    """
    headers = {
        "User-Agent": _PROBE_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=_TIMEOUT_S, allow_redirects=True)
        if resp.status_code == 200:
            return resp.text
    except RequestException as exc:
        logger.debug("Error fetching seed HTML for %s: %s", url, exc)
    return None


# ---------------------------------------------------------------------------
# Profile classification
# ---------------------------------------------------------------------------

# Profile labels match the spec table (§2.1 Domain type classification).
_PROFILE_A = "A"  # Simple HTML
_PROFILE_B = "B"  # JS-heavy
_PROFILE_C = "C"  # PDF-dominant
_PROFILE_D = "D"  # Bot-protected


def _classify_profile(
    probe: ProbeResult,
    seed_html: str | None,
) -> str:
    """
    Assign one of four crawl profiles based on pre-flight evidence.

    Profile D — bot-protection headers detected (highest priority).
    Profile C — seed URL Content-Type is application/pdf, or seed path
                strongly suggests a PDF archive.
    Profile B — seed HTML exists but body is very sparse (< threshold chars),
                suggesting JS-rendered content.
    Profile A — default for all other cases.

    Note: Profile B classification at pre-flight time is a preliminary
    heuristic only.  The definitive B/A distinction is confirmed during the
    first actual crawl run when the rendered page can be compared against
    the raw HTML.  The crawl manifest ``crawl_profile`` field is updated
    by the spider after the first successful fetch.
    Spec ref: §2.1 Domain type classification table.
    """
    # Profile D: any bot-protection header present.
    if probe.bot_protection_headers:
        return _PROFILE_D

    # Profile C: PDF Content-Type.
    ct_lower = probe.content_type.lower()
    if any(k in ct_lower for k in _PDF_CONTENT_TYPE_KEYWORDS):
        return _PROFILE_C

    # Profile C: PDF-archive path heuristic (supplement; not definitive).
    if probe.final_url:
        parsed_path = urlparse(probe.final_url).path.lower()
        path_tokens = set(re.split(r"[/_-]", parsed_path))
        if path_tokens & _PDF_PATH_KEYWORDS:
            return _PROFILE_C

    # Profile B: sparse HTML body suggests JS rendering.
    if seed_html is not None and len(seed_html.strip()) < _JS_SPARSE_BODY_THRESHOLD:
        return _PROFILE_B

    return _PROFILE_A


# ---------------------------------------------------------------------------
# Manifest I/O
# ---------------------------------------------------------------------------


def _manifest_path(raw_cache_dir: Path, domain: str) -> Path:
    # Sanitise domain for use as a directory name (remove port numbers etc.).
    safe_domain = re.sub(r"[^\w.\-]", "_", domain)
    return raw_cache_dir / safe_domain / "crawl_manifest.json"


def _load_existing_manifest(path: Path) -> dict:
    """Load an existing manifest, returning {} if absent or unreadable."""
    if path.exists():
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read existing manifest %s: %s", path, exc)
    return {}


def _write_manifest_atomic(path: Path, data: dict) -> None:
    """
    Write *data* as JSON to *path* atomically via a temp file rename,
    so a partial write never corrupts an existing manifest.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Per-domain pre-flight orchestrator
# ---------------------------------------------------------------------------


def _run_domain_preflight(
    row: SeedRow,
    raw_cache_dir: Path,
    bot_protection_headers: list[str],
    preflight_slow_threshold: float,
) -> dict:
    """
    Execute the full pre-flight sequence for one domain and write its
    ``crawl_manifest.json``.  Returns the finished manifest dict.
    """
    from grantglobe_crawler.preflight.robotstxt_parser import fetch_robots_and_sitemap
    from grantglobe_crawler.preflight.rss_checker import detect_feed

    seed_url = row.grants_url
    logger.info("[%s] Starting pre-flight for %s", row.id, seed_url)

    # ── Step 1: Range:0-0 probe ─────────────────────────────────────────────
    probe = _range_probe(seed_url, bot_protection_headers)
    if probe.error:
        logger.warning("[%s] Probe error for %s: %s", row.id, seed_url, probe.error)

    # ── Step 2: Full seed-page fetch (for RSS autodiscovery + profile B) ────
    # Only attempt if the probe succeeded with an HTML-like response.
    seed_html: str | None = None
    if not probe.error and probe.http_status in (200, 206):
        ct = probe.content_type.lower()
        if "html" in ct or not ct:  # empty content-type → try anyway
            seed_html = _fetch_seed_html(probe.final_url or seed_url)

    # ── Step 3: robots.txt + sitemap ────────────────────────────────────────
    robots_result = fetch_robots_and_sitemap(probe.final_url or seed_url)

    # ── Step 4: RSS / Atom feed detection ───────────────────────────────────
    feed_result = detect_feed(
        seed_url=probe.final_url or seed_url,
        seed_html=seed_html,
        robots_txt_content=robots_result.raw_robots_content,
    )

    # ── Step 5: profile classification ──────────────────────────────────────
    crawl_profile = _classify_profile(probe, seed_html)

    # ── Step 6: build manifest dict ─────────────────────────────────────────
    # Load any pre-existing manifest so that manually set fields (e.g.
    # robots_override, tab_filter) survive a re-run.
    manifest_file = _manifest_path(raw_cache_dir, row.domain)
    existing = _load_existing_manifest(manifest_file)

    # Rate-limit floor: prefer Crawl-delay from robots.txt; fall back to 4.0 s
    # (DOWNLOAD_DELAY from settings, the Gaussian mean).
    try:
        from grantglobe_crawler import settings as _s
        default_floor = float(_s.DOWNLOAD_DELAY)
        slow_threshold = _s.PREFLIGHT_SLOW_DOMAIN_THRESHOLD_S
    except Exception:
        default_floor = 4.0
        slow_threshold = preflight_slow_threshold

    rate_limit_floor = (
        robots_result.crawl_delay
        if robots_result.crawl_delay is not None
        else default_floor
    )

    # Flag slow domains for extended timeout configuration.
    slow_domain = probe.response_time_seconds > slow_threshold

    new_fields: dict = {
        # ── Pre-flight probe results ───────────────────────────────────────
        "seed_url": seed_url,
        "final_url": probe.final_url,
        "redirect_chain": probe.redirect_chain,
        "http_status": probe.http_status,
        "content_type": probe.content_type,
        "bot_protection_headers": probe.bot_protection_headers,
        "response_time_seconds": probe.response_time_seconds,
        "slow_domain": slow_domain,
        "probe_error": probe.error,
        # ── Domain metadata from CSV ───────────────────────────────────────
        "org_name": row.org_name,
        "domain": row.domain,
        "category": row.category,
        "region": row.region,
        # ── Crawl configuration ────────────────────────────────────────────
        "crawl_profile": crawl_profile,
        "max_depth": 3 if row.category in ("UN Agency", "Multilateral") else 2,
        "rate_limit_floor_seconds": rate_limit_floor,
        "crawl_frequency": "weekly",
        "downgrade_protected": False,
        # ── Initialised counters (never overwrite if already set) ──────────
        "consecutive_unchanged_cycles": existing.get("consecutive_unchanged_cycles", 0),
        "consecutive_failed_cycles": existing.get("consecutive_failed_cycles", 0),
        "dead_domain_candidate": existing.get("dead_domain_candidate", False),
        # ── Override flags (preserve manual edits) ─────────────────────────
        "robots_override": existing.get("robots_override", False),
        "robots_override_justification": existing.get("robots_override_justification", None),
        "tab_filter": existing.get("tab_filter", []),
        # ── robots.txt results ────────────────────────────────────────────
        "robots_txt_fetched": robots_result.robots_txt_fetched,
        "crawl_delay_from_robots": robots_result.crawl_delay,
        "sitemap_url": robots_result.sitemap_url,
        "sitemap_url_source": robots_result.sitemap_url_source,
        "sitemap_grant_urls": robots_result.sitemap_grant_urls,
        # ── RSS / feed detection ─────────────────────────────────────────
        "rss_feed_url": feed_result.feed_url,
        "rss_feed_detected_by": feed_result.detected_by,
        "rss_guid_set": existing.get("rss_guid_set", []),
        # ── Lifecycle fields ──────────────────────────────────────────────
        "proxy_required": crawl_profile == _PROFILE_D,
        "captcha_history": existing.get("captcha_history", []),
        "user_agent_assigned": existing.get("user_agent_assigned", None),
        "pdf_url_map": existing.get("pdf_url_map", {}),
        # ── Timestamps ───────────────────────────────────────────────────
        "preflight_timestamp": datetime.now(timezone.utc).isoformat(),
        "last_crawl_date": existing.get("last_crawl_date", None),
    }

    # Write atomically.
    _write_manifest_atomic(manifest_file, new_fields)
    logger.info(
        "[%s] %s → profile=%s rss=%s sitemap=%s slow=%s",
        row.id,
        row.domain,
        crawl_profile,
        bool(feed_result.feed_url),
        bool(robots_result.sitemap_url),
        slow_domain,
    )
    return new_fields


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_preflight(
    source_list_csv: str | Path | None = None,
    raw_cache_dir: str | Path | None = None,
    max_workers: int = _MAX_WORKERS,
) -> list[dict]:
    """
    Run the full pre-flight pass over all seeds in *source_list_csv*.

    Parameters
    ----------
    source_list_csv:
        Path to ``source_list_v0.6_final.csv``.  Defaults to
        ``settings.SOURCE_LIST_CSV``.
    raw_cache_dir:
        Root of the content cache.  Defaults to ``settings.RAW_CACHE_DIR``.
    max_workers:
        Thread-pool size.  Each worker handles one domain at a time.

    Returns
    -------
    list[dict]
        All completed manifest dicts (one per domain), useful for summary
        reporting.
    """
    try:
        from grantglobe_crawler import settings as _s
        _csv = source_list_csv or _s.SOURCE_LIST_CSV
        _cache = raw_cache_dir or _s.RAW_CACHE_DIR
        _bot_headers = _s.BOT_PROTECTION_HEADERS
        _slow_threshold = _s.PREFLIGHT_SLOW_DOMAIN_THRESHOLD_S
    except Exception:
        _csv = source_list_csv
        _cache = raw_cache_dir or "raw_cache"
        _bot_headers = ["cf-ray", "x-sucuri-id"]
        _slow_threshold = 5.0

    if not _csv:
        raise ValueError(
            "source_list_csv is required (or set SOURCE_LIST_CSV in settings.py / .env)"
        )

    csv_path = Path(_csv)
    cache_path = Path(_cache)

    if not csv_path.exists():
        raise FileNotFoundError(
            f"Source list CSV not found: {csv_path}\n"
            f"Expected location: {csv_path.resolve()}\n"
            "Check settings.SOURCE_LIST_CSV or pass source_list_csv= explicitly."
        )

    rows = load_source_list(csv_path)
    if not rows:
        logger.warning("No rows loaded from %s — nothing to do.", csv_path)
        return []

    logger.info(
        "Starting pre-flight for %d domains with %d workers.", len(rows), max_workers
    )

    results: list[dict] = []
    failed: list[str] = []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                _run_domain_preflight,
                row,
                cache_path,
                _bot_headers,
                _slow_threshold,
            ): row
            for row in rows
        }
        for future in as_completed(futures):
            row = futures[future]
            try:
                manifest = future.result()
                results.append(manifest)
            except Exception as exc:
                logger.error(
                    "Pre-flight failed for %s (%s): %s", row.domain, row.grants_url, exc
                )
                failed.append(row.domain)

    # ── Summary ─────────────────────────────────────────────────────────────
    total = len(rows)
    success = len(results)
    profile_counts: dict[str, int] = {}
    feed_count = 0
    sitemap_count = 0
    slow_count = 0
    for m in results:
        p = m.get("crawl_profile", "?")
        profile_counts[p] = profile_counts.get(p, 0) + 1
        if m.get("rss_feed_url"):
            feed_count += 1
        if m.get("sitemap_url"):
            sitemap_count += 1
        if m.get("slow_domain"):
            slow_count += 1

    logger.info("=" * 60)
    logger.info("PRE-FLIGHT COMPLETE")
    logger.info("  Total seeds    : %d", total)
    logger.info("  Manifests written: %d", success)
    logger.info("  Failures       : %d  %s", len(failed), failed[:10])
    logger.info("  Profiles       : %s", profile_counts)
    logger.info("  Feeds detected : %d", feed_count)
    logger.info("  Sitemaps found : %d", sitemap_count)
    logger.info("  Slow domains (>%.0fs): %d", _slow_threshold, slow_count)
    logger.info("  Cache root     : %s", cache_path.resolve())
    logger.info("=" * 60)

    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _cli_main() -> None:
    import argparse

    ap = argparse.ArgumentParser(
        description="GrantGlobe Stage 2 — pre-flight domain assessment"
    )
    ap.add_argument(
        "--csv",
        metavar="PATH",
        help="Override path to source_list CSV (default: settings.SOURCE_LIST_CSV)",
    )
    ap.add_argument(
        "--cache",
        metavar="DIR",
        help="Override raw_cache root directory (default: settings.RAW_CACHE_DIR)",
    )
    ap.add_argument(
        "--workers",
        type=int,
        default=_MAX_WORKERS,
        metavar="N",
        help=f"Thread-pool size (default: {_MAX_WORKERS})",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Load CSV and print seed count, but do not issue any HTTP requests.",
    )
    args = ap.parse_args()

    if args.dry_run:
        try:
            from grantglobe_crawler import settings as _s
            csv_path = args.csv or _s.SOURCE_LIST_CSV
        except Exception:
            csv_path = args.csv
        rows = load_source_list(csv_path)
        print(f"Dry run: {len(rows)} seeds loaded from {csv_path}")
        sys.exit(0)

    run_preflight(
        source_list_csv=args.csv,
        raw_cache_dir=args.cache,
        max_workers=args.workers,
    )


if __name__ == "__main__":
    _cli_main()
