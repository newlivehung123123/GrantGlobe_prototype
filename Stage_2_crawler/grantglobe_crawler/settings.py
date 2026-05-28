"""
GrantGlobe Stage 2 Crawler — Scrapy Settings
============================================
Implements every configuration variable named in the Stage 2 technical
specification (v1.7).  Values that the spec leaves unspecified are marked
with explicit TODO comments rather than invented defaults.

All secrets (encryption key, proxy credentials) are loaded from a .env file
via python-dotenv.  The .env file is listed in .gitignore and must NEVER be
committed to version control.

Quick-start:
    cp .env.example .env   # then fill in real values
    scrapy crawl <spider>
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# 0.  Load secrets from .env
#     The .env file must live in the project root (same directory as scrapy.cfg).
#     Environment variables already set in the shell take precedence.
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=False)

# Secrets — read once here so the rest of settings.py uses plain variables.
# If a secret is absent the crawler will still start; the relevant subsystem
# (cookie store, proxy middleware) will raise a clear error when it first tries
# to use the missing value.

COOKIE_ENCRYPTION_KEY: str | None = os.getenv("COOKIE_ENCRYPTION_KEY")
"""
Fernet symmetric key for encrypting cookie_store/{domain}.enc files.
Generate with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
Store the output as COOKIE_ENCRYPTION_KEY=<value> in .env.
Spec ref: §2.5 Layer 4 — Cookie storage security.
"""

PROXY_HOST: str | None = os.getenv("PROXY_HOST")
PROXY_PORT: str | None = os.getenv("PROXY_PORT")
PROXY_USERNAME: str | None = os.getenv("PROXY_USERNAME")
PROXY_PASSWORD: str | None = os.getenv("PROXY_PASSWORD")
# Set True to activate proxy rotation for Profile D domains.
# Requires PROXY_HOST, PROXY_PORT, PROXY_USERNAME, PROXY_PASSWORD to be
# set in the environment.  Proxy credentials are never written to this file.
PROXY_ENABLED: bool = False
"""
Rotating residential proxy pool credentials (Oxylabs, Bright Data, or equiv.).
Used only for Profile D (bot-protected) domains in the prototype phase and for
all domains in production.  Set in .env — do not hardcode.
Spec ref: §2.5 Layer 6 — Proxy configuration.
"""

ALERT_EMAIL_HOST: str | None = os.getenv("ALERT_EMAIL_HOST")
ALERT_EMAIL_PORT: int = int(os.getenv("ALERT_EMAIL_PORT", "587"))
ALERT_EMAIL_USER: str | None = os.getenv("ALERT_EMAIL_USER")
ALERT_EMAIL_PASSWORD: str | None = os.getenv("ALERT_EMAIL_PASSWORD")
ALERT_EMAIL_TO: str | None = os.getenv("ALERT_EMAIL_TO")
ALERT_WEBHOOK_URL: str | None = os.getenv("ALERT_WEBHOOK_URL")
"""
Alerting channel credentials.  At least one of email or webhook should be
configured before the first production run.
Spec ref: §2.8 Alerting.
"""

# ---------------------------------------------------------------------------
# 1.  Scrapy project identity
# ---------------------------------------------------------------------------

BOT_NAME = "grantglobe_crawler"
SPIDER_MODULES = ["grantglobe_crawler.spiders"]
NEWSPIDER_MODULE = "grantglobe_crawler.spiders"

# ---------------------------------------------------------------------------
# 2.  Concurrency
#     Prototype sequential : CONCURRENT_REQUESTS = 1   (~500 MB RAM, 48–72 h)
#     Optimised prototype  : CONCURRENT_REQUESTS = 8   (~2–4 GB RAM, 8–12 h)  ← default
#     Production           : CONCURRENT_REQUESTS = 32  (~8–12 GB RAM, 2–3 h)
#     Each Playwright browser context consumes ~150–300 MB RAM.
#     Spec ref: §2.8 Hardware requirements table.
# ---------------------------------------------------------------------------

CONCURRENT_REQUESTS: int = 8
"""
Global concurrent request limit.  Match this to the hardware configuration in
use.  Adjust EXPECTED_CRAWL_DURATION_HOURS below whenever this value changes.
"""

CONCURRENT_REQUESTS_PER_DOMAIN: int = 1
"""
Hard cap of one in-flight request per domain at any time.  This is the primary
per-domain politeness control; the inter-request delay (below) adds time-based
spacing on top of the concurrency cap.
Spec ref: §2.5 Layer 3 — Per-domain rate limits.
"""

# ---------------------------------------------------------------------------
# 3.  Inter-request delay
#     The BehaviouralDelayMiddleware (grantglobe_crawler.middlewares.delay)
#     computes the actual delay as:
#         max(rate_limit_floor_seconds, Gaussian(DELAY_MEAN, DELAY_SD))
#     clipped to [rate_limit_floor, rate_limit_floor + 15].
#
#     DOWNLOAD_DELAY is set to DELAY_MEAN so that Scrapy's own accounting
#     reflects the intended cadence.  The middleware overrides the actual
#     sleep, so Scrapy's built-in RANDOMIZE_DOWNLOAD_DELAY is disabled.
#     Spec ref: §2.5 Layer 3 — Behavioural humanisation.
# ---------------------------------------------------------------------------

DOWNLOAD_DELAY: float = 4.0
"""
Mean inter-request delay in seconds (Gaussian mean = 4 s).
This value is also used by BehaviouralDelayMiddleware as DELAY_MEAN.
Spec ref: §2.5 Layer 3 — "mean 4s".
"""

RANDOMIZE_DOWNLOAD_DELAY: bool = False
"""
Disabled because BehaviouralDelayMiddleware applies its own Gaussian
randomisation.  Enabling Scrapy's built-in ±50% jitter on top would
produce a double-randomisation artefact.
"""

DELAY_SD: float = 1.5
"""Standard deviation of the Gaussian inter-request delay (seconds). Spec ref: §2.5 Layer 3 — "SD 1.5s"."""

DELAY_MIN: float = 2.0
"""Lower clip bound for the Gaussian delay (seconds). Spec ref: §2.5 Layer 3 — "clipped to [2, 10]"."""

DELAY_MAX: float = 10.0
"""Upper clip bound for the Gaussian delay (seconds). Spec ref: §2.5 Layer 3 — "clipped to [2, 10]"."""

EXTENDED_PAUSE_PROBABILITY: float = 0.15
"""
Probability of inserting a 15–45 s reading pause after fetching an individual-
opportunity page.  Applied inside BehaviouralDelayMiddleware.
Spec ref: §2.5 Layer 3 — "With 15% probability".
"""

EXTENDED_PAUSE_MIN: float = 15.0
"""Lower bound of extended reading pause (seconds). Spec ref: §2.5 Layer 3."""

EXTENDED_PAUSE_MAX: float = 45.0
"""Upper bound of extended reading pause (seconds). Spec ref: §2.5 Layer 3."""

# ---------------------------------------------------------------------------
# 4.  robots.txt policy
#     ROBOTSTXT_OBEY = True keeps Scrapy's default behaviour.  A custom
#     GrantGlobeRobotsTxtMiddleware subclass (grantglobe_crawler.middlewares
#     .robotstxt) allows per-domain override when the domain is listed in
#     crawl_manifest.json with robots_override: true and a written justification.
#     Spec ref: §2.1 robots.txt policy.
# ---------------------------------------------------------------------------

ROBOTSTXT_OBEY: bool = True

# ---------------------------------------------------------------------------
# 5.  State persistence (JOBDIR)
#     Scrapy persists the visited-URL fingerprint set and the pending request
#     queue to this directory.  If the crawler is interrupted it resumes from
#     where it stopped rather than restarting the full crawl.
#     Spec ref: §2.8 State persistence.
# ---------------------------------------------------------------------------

JOBDIR: str = str(_PROJECT_ROOT / "crawl_state")
"""
Path to Scrapy's job (state) directory.  Listed in .gitignore.  Created
automatically by Scrapy on first run.  The SQLite backend is used implicitly.
"""

# ---------------------------------------------------------------------------
# 6.  User-Agent pool
#     20 real browser UA strings current as of May 2026.
#     Distribution: 9 Chrome (124–136), 6 Firefox (125–138), 5 Safari (17–18).
#     One UA is selected per domain per crawl session and held constant for
#     the entire session — rotating mid-session triggers detection on
#     session-aware sites.
#     MAINTENANCE: refresh quarterly by replacing oldest Chrome/Firefox/Safari
#     version strings with current stable releases.  Flag UAs for browsers
#     past end-of-life; stale UAs are actively flagged by Cloudflare et al.
#     Spec ref: §2.5 Layer 2 — User-Agent pool.
# ---------------------------------------------------------------------------

USERAGENT_POOL: list[str] = [
    # ── Chrome 124–136 ────────────────────────────────────────────────────────
    # Chrome 124 · Windows 10
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.82 Safari/537.36",
    # Chrome 126 · Windows 11 (NT reports 10.0 in UA regardless of Windows 11)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.6478.127 Safari/537.36",
    # Chrome 128 · Windows 10
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.120 Safari/537.36",
    # Chrome 130 · macOS 14 Sonoma
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.6723.91 Safari/537.36",
    # Chrome 132 · macOS 15 Sequoia
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.6834.110 Safari/537.36",
    # Chrome 134 · Ubuntu 22.04 LTS
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.6998.117 Safari/537.36",
    # Chrome 135 · Windows 11
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.7049.100 Safari/537.36",
    # Chrome 136 · macOS 15 Sequoia
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.7103.59 Safari/537.36",
    # Chrome 136 · Ubuntu 24.04 LTS
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.7103.59 Safari/537.36",
    # ── Firefox 125–138 ───────────────────────────────────────────────────────
    # Firefox 125 · Windows 10
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    # Firefox 128 · macOS 14 Sonoma
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.5; rv:128.0) Gecko/20100101 Firefox/128.0",
    # Firefox 130 · Windows 11
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
    # Firefox 133 · macOS 15 Sequoia
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 15.0; rv:133.0) Gecko/20100101 Firefox/133.0",
    # Firefox 135 · Windows 10
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0",
    # Firefox 138 · macOS 15 Sequoia
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 15.3; rv:138.0) Gecko/20100101 Firefox/138.0",
    # ── Safari 17–18 ──────────────────────────────────────────────────────────
    # Safari 17.0 · macOS 14.0 Sonoma
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    # Safari 17.2.1 · macOS 14.2
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2.1 Safari/605.1.15",
    # Safari 17.5 · macOS 14.5
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    # Safari 18.0 · macOS 15.0 Sequoia
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
    # Safari 18.3.2 · macOS 15.3
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_3_2) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3.2 Safari/605.1.15",
]

assert len(USERAGENT_POOL) == 20, "USERAGENT_POOL must contain exactly 20 entries per spec"

# ---------------------------------------------------------------------------
# 7.  Scheduling / timing
#     Spec ref: §2.8 Crawl frequency and Alerting.
# ---------------------------------------------------------------------------

EXPECTED_CRAWL_DURATION_HOURS: float = 12.0
"""
Expected wall-clock duration of one full crawl cycle.  Used to calibrate the
2× threshold that triggers a Critical alert (spec §2.8 Alerting table).

Recommended values (adjust whenever CONCURRENT_REQUESTS changes):
    72.0  — sequential prototype  (CONCURRENT_REQUESTS = 1)
    12.0  — optimised prototype   (CONCURRENT_REQUESTS = 8)   ← default
     3.0  — production            (CONCURRENT_REQUESTS = 32)

IMPORTANT: set this before the first crawl run.  Without a concrete value the
2× multiplier has no meaning and the Critical alert will never fire.
Spec ref: §2.8 Alerting + Phase A build sequence note.
"""

WEEKLY_CRAWL_SCHEDULE_UTC: str = "Sunday 02:00"
"""Full-refresh schedule for all 582 domains. Spec ref: §2.8 Crawl frequency."""

DAILY_CRAWL_SCHEDULE_UTC: str = "02:00"
"""Daily schedule for ~40 high-activity domains. Spec ref: §2.8 Crawl frequency."""

INCREMENTAL_DOWNGRADE_BIWEEKLY_THRESHOLD: int = 3
"""
Downgrade to bi-weekly if a domain has been unchanged for this many consecutive
weekly cycles.  Spec ref: §2.8 Incremental scheduling feedback loop.
"""

INCREMENTAL_DOWNGRADE_MONTHLY_THRESHOLD: int = 6
"""
Downgrade to monthly if a domain has been unchanged for this many consecutive
weekly cycles.  Spec ref: §2.8 Incremental scheduling feedback loop.
"""

DEAD_DOMAIN_FAILED_CYCLE_THRESHOLD: int = 3
"""
Escalate to dead-domain-candidate queue after this many consecutive fully-failed
cycles.  Spec ref: §2.8 Dead domain sunset detection.
"""

# ---------------------------------------------------------------------------
# 8.  Alert thresholds
#     Spec ref: §2.8 Alerting table.
# ---------------------------------------------------------------------------

ALERT_THRESHOLD_SINGLE_DOMAIN_FAILURES: int = 1
"""High: alert when >= this many domains fail in a single cycle.
Set to 0 to alert on any single failure; raise the value if transient
one-off failures on large crawls produce too much noise."""

ALERT_THRESHOLD_DOMAIN_FAILURE_RATE: float = 0.20
"""Critical: fraction of domains where all retries are exhausted."""

ALERT_THRESHOLD_CAPTCHA_BLOCKED_DOMAINS: int = 10
"""High: absolute count of CAPTCHA-blocked domains per cycle."""

ALERT_THRESHOLD_PDF_EXTRACTION_FAILURE_RATE: float = 0.25
"""High: fraction of detected PDFs that fail extraction."""

ALERT_THRESHOLD_ZERO_GRANT_PAGES_DOMAINS: int = 30
"""Medium: absolute count of domains with zero grant-relevant pages."""

# ALERT_THRESHOLD_CRAWL_DURATION_MULTIPLIER is implicitly 2× EXPECTED_CRAWL_DURATION_HOURS.

# ---------------------------------------------------------------------------
# 9.  Playwright configuration
#     scrapy-playwright is wired in as a download handler, not a middleware.
#     TWISTED_REACTOR must be set to the asyncio reactor for scrapy-playwright
#     to function.
#     Spec ref: §2.2 Core framework.
# ---------------------------------------------------------------------------

TWISTED_REACTOR: str = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

DOWNLOAD_HANDLERS: dict[str, str] = {
    "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
}

PLAYWRIGHT_BROWSER_TYPE: str = "chromium"

PLAYWRIGHT_LAUNCH_OPTIONS: dict = {
    "headless": True,
    # TODO: add stealth library launch args here once the pre-Phase A library
    # evaluation is complete (spec §2.5 Layer 1).  For rebrowser-playwright,
    # this may be replaced by a custom executable path; for undetected-playwright
    # or playwright-stealth, additional args or patch calls go here.
}

PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT: int = 20_000
"""
Hard timeout cap for networkidle waits in pagination Types 2, 3, and 4 (ms).
Sites with persistent WebSocket connections can cause networkidle to block
indefinitely; 20 s cap ensures no single page stalls the queue.
Spec ref: §2.3 Types 2, 3, and 4.
"""

PLAYWRIGHT_CONTEXTS: dict = {
    # Per-domain persistent browser contexts are created dynamically by
    # PlaywrightContextMiddleware using USERAGENT_POOL and viewport sizes.
    # The static key here is a fallback default context.
    "default": {
        "viewport": {"width": 1920, "height": 1080},
        # User-Agent is overridden per-domain at context creation time.
    },
}

PLAYWRIGHT_VIEWPORT_POOL: list[dict] = [
    {"width": 1280, "height": 800},
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1920, "height": 1080},
    {"width": 2560, "height": 1440},
]
"""
Common desktop viewport sizes; one is sampled per browser session.
Spec ref: §2.5 Layer 3 — Viewport randomisation.
"""

# ---------------------------------------------------------------------------
# 10.  Downloader middlewares
#      Priority ordering (lower number = higher priority = runs first on
#      request, last on response):
#        100  GrantGlobeRobotsTxtMiddleware — replaces Scrapy default;
#             allows per-domain override when robots_override: true in manifest.
#        300  UserAgentMiddleware           — assigns one UA per domain per
#             session from USERAGENT_POOL; holds it constant for the session.
#        400  BehaviouralDelayMiddleware    — Gaussian inter-request delay,
#             extended reading pauses, per-domain rate_limit_floor enforcement.
#        410  SecFetchHeadersMiddleware     — sets dynamic Sec-Fetch-* headers
#             based on request context (cold nav / link-follow / XHR / PDF).
#             Runs after UA assignment (300) so the correct UA is already set.
#        500  ProxyRotationMiddleware       — residential proxy injection for
#             Profile D domains (production phase); disabled by default.
#        600  RetryMiddleware               — custom exponential-backoff retry
#             logic matching the spec §2.5 Layer 7 table.
#
#      Scrapy's own RobotsTxtMiddleware (priority 100) is disabled here because
#      GrantGlobeRobotsTxtMiddleware takes its place.
#      Spec ref: §2.5 Layers 2–7.
# ---------------------------------------------------------------------------

DOWNLOADER_MIDDLEWARES: dict[str, int | None] = {
    # Disable Scrapy's built-in robots.txt middleware — replaced by custom subclass.
    "scrapy.downloadermiddlewares.robotstxt.RobotsTxtMiddleware": None,
    # Custom robots.txt middleware with per-domain override support.
    "grantglobe_crawler.middlewares.robotstxt.GrantGlobeRobotsTxtMiddleware": 100,
    # Per-session UA assignment from USERAGENT_POOL.
    "grantglobe_crawler.middlewares.user_agent.UserAgentMiddleware": 300,
    # Gaussian inter-request delay + extended reading pauses.
    "grantglobe_crawler.middlewares.delay.BehaviouralDelayMiddleware": 400,
    # Dynamic Sec-Fetch-* headers (cold nav vs link-follow vs XHR vs PDF).
    # Priority 410: after UA assignment (400), before Scrapy built-ins (543).
    # Spec ref: §2.5 Layer 2 — Sec-Fetch-* headers are dynamic by request context.
    "grantglobe_crawler.middlewares.sec_fetch_middleware.SecFetchHeadersMiddleware": 410,
    # Residential proxy rotation for Profile D — DISABLED until production.
    "grantglobe_crawler.middlewares.proxy.ProxyRotationMiddleware": None,
    # Retry middleware with spec-defined backoff schedule.
    # Disable Scrapy's built-in retry to avoid duplicate retry handling.
    "scrapy.downloadermiddlewares.retry.RetryMiddleware": None,
    # Phase A: class stub — full implementation in Phase B.
    # "grantglobe_crawler.middlewares.retry.GrantGlobeRetryMiddleware": 600,
}

# Retry settings consumed by GrantGlobeRetryMiddleware.
# Spec ref: §2.5 Layer 7 — retry / backoff table.
RETRY_HTTP_CODES: list[int] = [429, 403, 503, 500, 502, 504]
RETRY_TIMES: int = 3  # maximum across all status codes; per-code limits enforced in middleware

RETRY_429_BACKOFF_BASE: float = 60.0
"""First backoff interval for HTTP 429 (seconds); doubles on each retry: 60, 120, 240. Spec ref: §2.5 Layer 7."""

RETRY_403_MAX: int = 1
"""Retry 403 once with a different UA + fresh Playwright session. Spec ref: §2.5 Layer 7."""

RETRY_503_INTERVAL: float = 30.0
"""Fixed retry interval for HTTP 503 (seconds). Spec ref: §2.5 Layer 7."""

RETRY_TIMEOUT_INTERVAL: float = 15.0
"""Retry interval for connection timeouts (seconds). Spec ref: §2.5 Layer 7."""

RETRY_TIMEOUT_MAX: int = 2
"""Maximum retries for connection timeouts. Spec ref: §2.5 Layer 7."""

DOWNLOAD_TIMEOUT: float = 30.0
"""Connection timeout threshold (seconds). Spec ref: §2.5 Layer 7 — ">30s"."""

# ---------------------------------------------------------------------------
# 11.  Item pipelines
#      Priority ordering (lower number runs first):
#        100  ChangeDetectionPipeline  — compares content hash against previous
#             cycle; sets item['changed'] flag; implements comparison_basis:none
#             fallback for first-run or failed-previous-cycle domains.
#        300  FilesPipeline            — downloads confirmed PDFs via Scrapy's
#             built-in FilesPipeline to raw_cache/{domain}/{date}/pdfs/.
#             PDF filename is the content SHA-256 hash (not URL hash).
#        500  ContentStoragePipeline   — writes rendered HTML (gzip compressed)
#             to raw_cache/{domain}/{date}/pages/{url_hash}.html.
#        700  MetadataPipeline         — writes .meta.json sidecar files for
#             pages and PDFs; writes manifest.json for the cycle.
#      Spec ref: §2.6 Content Storage Schema.
# ---------------------------------------------------------------------------

ITEM_PIPELINES: dict[str, int] = {
    # ChangeDetectionPipeline — stub in Phase A; full implementation in Phase D.
    "grantglobe_crawler.pipelines.change_detection.ChangeDetectionPipeline": 100,
    #
    # scrapy.pipelines.files.FilesPipeline — replaced by PDFExtractionPipeline.
    # "scrapy.pipelines.files.FilesPipeline": 300,
    #
    # PDFExtractionPipeline — Phase A Step 4.
    # Runs at 400 (before ContentStoragePipeline) so item['content_sha256'],
    # item['char_count'], and item['language'] are populated before writing.
    "grantglobe_crawler.pipelines.pdf_pipeline.PDFExtractionPipeline": 400,
    #
    # ContentStoragePipeline — Phase A Step 4.
    # Writes gzip-compressed HTML, raw PDFs, and .meta.json sidecars.
    "grantglobe_crawler.pipelines.content_storage.ContentStoragePipeline": 500,
    #
    # MetadataPipeline — Phase D (not yet built).
    # "grantglobe_crawler.pipelines.metadata.MetadataPipeline": 700,
}

# ---------------------------------------------------------------------------
# 12.  Storage paths
#      Spec ref: §2.6 Content Storage Schema + retention policy.
# ---------------------------------------------------------------------------

RAW_CACHE_DIR: str = str(_PROJECT_ROOT / "raw_cache")
"""Root of the structured content cache consumed by Stage 3."""

CRAWL_STATE_DIR: str = RAW_CACHE_DIR
"""
Directory where per-domain ``crawl_manifest.json`` files live.  Identical
to RAW_CACHE_DIR because manifests are stored at
``raw_cache/{domain}/crawl_manifest.json``.
Used by the spider to load manifests on start and write final stats on close.
"""

MAX_CRAWL_DEPTH: int = 3
"""
Global depth ceiling across all domains.  Per-domain ``max_depth`` in the
crawl manifest takes effect first; this value prevents any single domain from
exceeding 3 regardless of manifest config.
Spec ref: §2.2 Depth strategy — depth 2 for most foundations, depth 3 for
large multilaterals.
"""

FILES_STORE: str = RAW_CACHE_DIR
"""
Scrapy's FilesPipeline writes downloaded files relative to this path.
PDF filenames are overridden by ContentStoragePipeline to use content SHA-256
hashes rather than URL-derived names.
Spec ref: §2.4 Step 2 — PDF storage with content-hash filenames.
"""

COOKIE_STORE_DIR: str = str(_PROJECT_ROOT / "cookie_store")

SOURCE_LIST_CSV: str = str(
    _PROJECT_ROOT.parent / "Stage_1_directory" / "source_list_v0.6_final.csv"
)
"""
Absolute path to the seed URL CSV produced by Stage 1.
Task spec states the file lives at ../source_list/source_list_v0.6_final.csv
relative to the project root, but the actual file is at
../Stage_1_directory/source_list_v0.6_final.csv.
Override via environment variable SOURCE_LIST_CSV if the path changes.
Expected CSV columns: id, org_name, domain, grants_url, category, region,
                      individual_eligible, notes, confidence, gap_flag
"""
SOURCE_LIST_CSV = os.getenv("SOURCE_LIST_CSV", SOURCE_LIST_CSV)
"""
Per-domain encrypted cookie files: cookie_store/{domain}.enc
Listed in .gitignore.  Encryption key loaded from COOKIE_ENCRYPTION_KEY env var.
Spec ref: §2.5 Layer 4 — Cookie storage security.
"""

# Retention policy constants (used by the scheduler / cleanup job).
HTML_RETENTION_CYCLES: int = 2
"""Retain the two most recent crawl cycles of HTML snapshots per domain. Spec ref: §2.6."""

PDF_RETENTION_CYCLES: int = 4
"""Retain the four most recent crawl cycles of raw PDFs per domain. Spec ref: §2.6."""

# ---------------------------------------------------------------------------
# 13.  PDF extraction parameters
#      Spec ref: §2.4 PDF Extraction Pipeline.
# ---------------------------------------------------------------------------

PDF_OCR_THRESHOLD: float = 0.40
"""
Route a PDF to OCR if ≥ 40% of its pages yield fewer than OCR_MIN_CHARS
characters after PyMuPDF extraction.
Spec ref: §2.4 Step 4 — "≥ 40% of its pages".
"""

PDF_OCR_MIN_CHARS_PER_PAGE: int = 100
"""
Per-page character count below which a page is considered extraction-failed
and counted toward the OCR trigger threshold.
Spec ref: §2.4 Step 4 — "fewer than 100 characters".
"""

PDF_OCR_DPI: int = 300
"""DPI for pdf2image PNG conversion on OCR-fallback pages. Spec ref: §2.4 Step 5."""

PDF_OCR_PAGE_BATCH_SIZE: int = 10
"""
Maximum pages converted to PNG per pdf2image call.  Prevents OOM on large
documents (50+ pages at 300 DPI can consume several GB when converted all
at once).  Process in batches of 10: pages 1–10, then 11–20, etc.
Spec ref: §Known Limitations — "large PDF memory consumption".
"""

PDF_OCR_LANGUAGES: list[str] = ["eng", "fra", "spa", "ara"]
"""
Tesseract language packs loaded for OCR fallback.
Covers English, French, Spanish, Arabic — the dominant non-Western languages
in GrantGlobe's source list.
Spec ref: §2.4 Step 5.
"""

PDF_FOOTER_REPEAT_THRESHOLD: float = 0.70
"""
Repeated header/footer strings appearing on ≥ 70% of pages are stripped during
text cleaning.
Spec ref: §2.4 Step 7.
"""

# ---------------------------------------------------------------------------
# 14.  Language detection
#      lingua-language-detector configured to distinguish the eight languages
#      most likely to appear in GrantGlobe's source list.
#      Spec ref: §2.4 Step 6.
# ---------------------------------------------------------------------------

LINGUA_LANGUAGES: list[str] = [
    "ENGLISH",
    "FRENCH",
    "SPANISH",
    "ARABIC",
    "PORTUGUESE",
    "CHINESE",
    "JAPANESE",
    "KOREAN",
]
"""
ISO-639 language names as recognised by lingua-language-detector's Language enum.
Documents detected as non-English are flagged with their ISO 639-1 code in
.meta.json; Stage 3 routes them to translation before LLM extraction.
"""

# ---------------------------------------------------------------------------
# 15.  Link Intelligence Filter
#      Positive and negative signal keyword sets used by the Tier 2 relevance
#      scorer in LinkIntelligenceFilter (grantglobe_crawler.utils.link_filter).
#      Path segments are split on '/', '-', and '_' before matching.
#      Spec ref: §2.2 Link Intelligence Filter.
# ---------------------------------------------------------------------------

LINK_FILTER_POSITIVE_SIGNALS: list[str] = [
    "grant", "call", "fund", "award", "fellow", "scholar", "apply",
    "application", "deadline", "rfp", "rfa", "rfq", "opportunity",
    "programme", "program", "bursary", "stipend", "scholarship",
    "prize", "competition", "open", "current", "active", "invitation",
    "proposals",
]

LINK_FILTER_NEGATIVE_SIGNALS: list[str] = [
    "staff", "team", "about", "contact", "privacy", "cookie",
    "login", "register", "career", "job", "gallery", "photo",
    "donate", "volunteer", "sitemap", "search", "404",
]
"""
Applied only when the segment is a standalone navigation-level token without
grant-positive neighbours.  Blanket negative signals expressly NOT listed here:
news, blog, event, press, media, archive, tag, category.
Spec ref: §2.2 — path segment isolation rule.
"""

LINK_FILTER_POSITIVE_URL_WEIGHT: int = 1
"""Score per matching URL path segment keyword."""

LINK_FILTER_POSITIVE_ANCHOR_WEIGHT: int = 2
"""Score per matching anchor text keyword."""

LINK_FILTER_NEGATIVE_WEIGHT: int = -2
"""Score applied per matching standalone navigation-level negative segment."""

LINK_FILTER_MIN_SCORE: int = 0
"""Links scoring below this are discarded (depth ≥ 1). Spec ref: §2.2."""

LINK_FILTER_SEED_MIN_SCORE: int = -1
"""Relaxed threshold for depth 0 seed pages to ensure broad initial coverage. Spec ref: §2.2."""

# ---------------------------------------------------------------------------
# 16.  Pagination handler parameters
#      Spec ref: §2.3 Pagination Handler.
# ---------------------------------------------------------------------------

PAGINATION_LOAD_MORE_MAX_CLICKS: int = 20
"""Safety limit on 'Load more' click iterations (Type 2). Spec ref: §2.3 Type 2."""

PAGINATION_INFINITE_SCROLL_MAX_ITERATIONS: int = 30
"""Safety limit on infinite-scroll iterations (Type 3). Spec ref: §2.3 Type 3."""

PAGINATION_NETWORKIDLE_TIMEOUT_MS: int = 20_000
"""
Hard timeout cap on networkidle waits for Types 2, 3, and 4.
Mirrors PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT.
Spec ref: §2.3 Types 2–4 — "hard timeout cap of 20 seconds".
"""

# ---------------------------------------------------------------------------
# 17.  URL canonicalisation
#      Applied before SHA-256 hashing in utils.url_canon.canonicalise().
#      Spec ref: §2.2 URL canonicalisation.
# ---------------------------------------------------------------------------

URL_TRACKING_PARAMS: list[str] = [
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "msclkid", "twclid", "igshid",
]
"""
Query parameters stripped during canonicalisation (tracking-only; do not affect
page content).  Content-affecting params (e.g., ?page=2, ?lang=en) are preserved.
"""

# ---------------------------------------------------------------------------
# 18.  Content deduplication / change detection
#      Spec ref: §2.6 Content deduplication + Change detection.
# ---------------------------------------------------------------------------

URL_HASH_LENGTH: int = 16
"""
SHA-256 hex digest truncated to this many characters for use as a filename
stem.  Collision probability is negligible at < 10⁶ URLs.
Spec ref: §2.6 — "truncated to 16 hex characters".
"""

# ---------------------------------------------------------------------------
# 19.  QA / coverage thresholds
#      Spec ref: §2.7 Quality Assurance and Coverage Reporting.
# ---------------------------------------------------------------------------

QA_LOW_CONTENT_CHAR_THRESHOLD: int = 300
"""Pages with fewer than this many extracted characters are flagged 'low_content'. Spec ref: §2.7."""

QA_GRANT_RELEVANCE_MIN_RATIO: float = 0.20
"""
Flag a domain if grant-relevant pages / total pages < 20%.
Spec ref: §2.7 Coverage metrics table.
"""

QA_PDF_SUCCESS_MIN_RATE: float = 0.80
"""Flag a domain if PDF extraction success rate < 80%. Spec ref: §2.7."""

QA_HIGH_CHANGE_THRESHOLD: float = 0.30
"""Flag a domain for Stage 3 priority if > 30% of pages changed. Spec ref: §2.7."""

CAPTCHA_DETECTION_STRINGS: list[str] = [
    "I am not a robot",
    "verify you are human",
    "hCaptcha",
    "reCAPTCHA",
    "Please complete the security check",
]
"""Strings whose presence in page content triggers CAPTCHA detection. Spec ref: §2.5 Layer 5."""

CAPTCHA_CONSECUTIVE_BLOCK_THRESHOLD: int = 2
"""
Promote a domain to manual review queue after being CAPTCHA-blocked across
this many consecutive crawl cycles.
Spec ref: §2.5 Layer 5.
"""

# ---------------------------------------------------------------------------
# 20.  HTTP header defaults (non-Sec-Fetch)
#      Sec-Fetch-* headers are set dynamically by SecFetchHeadersMiddleware.
#      Spec ref: §2.5 Layer 2 — HTTP header authenticity.
# ---------------------------------------------------------------------------

DEFAULT_REQUEST_HEADERS: dict[str, str] = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    # Sec-Fetch-* headers intentionally omitted here — set dynamically by
    # SecFetchHeadersMiddleware based on request context.
    # User-Agent intentionally omitted here — set per-domain by
    # UserAgentMiddleware from USERAGENT_POOL.
}

# ---------------------------------------------------------------------------
# 21.  Feed (RSS/Atom) detection paths
#      Probed in order when no <link rel="alternate"> autodiscovery element
#      is found in the seed page's <head>.
#      Spec ref: §2.1 RSS/Atom feed detection — common path probe.
# ---------------------------------------------------------------------------

FEED_PROBE_PATHS: list[str] = [
    "/feed",
    "/rss",
    "/rss.xml",
    "/atom.xml",
    "/feed.xml",
    "/news/feed",
]

FEED_CONTENT_TYPES: list[str] = [
    "application/rss+xml",
    "application/atom+xml",
]
"""
Content-Type values that unambiguously identify a feed.
text/xml responses require an additional root-element check (<rss> or <feed>).
Spec ref: §2.1 RSS/Atom feed detection — common path probe.
"""

# ---------------------------------------------------------------------------
# 22.  Sitemap grant-signal path segments
#      URLs in a domain's sitemap that contain any of these segments are
#      extracted and added to the crawl queue at depth 1.
#      Spec ref: §2.1 Sitemap.xml check.
# ---------------------------------------------------------------------------

SITEMAP_GRANT_SIGNALS: list[str] = [
    "grant", "call", "fund", "award", "fellow", "scholarship",
    "opportunity", "programme", "program", "bursary", "rfp", "rfa",
]

# ---------------------------------------------------------------------------
# 23.  Pre-flight probe
#      Spec ref: §2.1 Pre-flight checks.
# ---------------------------------------------------------------------------

PREFLIGHT_SLOW_DOMAIN_THRESHOLD_S: float = 5.0
"""Flag domains whose pre-flight response time exceeds this value (seconds). Spec ref: §2.1."""

BOT_PROTECTION_HEADERS: list[str] = ["cf-ray", "x-sucuri-id"]
"""Response headers whose presence signals bot-protection middleware. Spec ref: §2.1."""

# ---------------------------------------------------------------------------
# 24.  Miscellaneous Scrapy settings
# ---------------------------------------------------------------------------

AUTOTHROTTLE_ENABLED: bool = False
"""
Disabled — BehaviouralDelayMiddleware provides Gaussian-distributed delays
that are more representative of human behaviour than AutoThrottle's
latency-based algorithm.  Enabling AutoThrottle on top would interfere.
"""

COOKIES_ENABLED: bool = True
"""
Scrapy-level cookie jar is enabled.  The CookieConsentMiddleware clicks
consent banners on first visit.  Long-lived session cookies are managed
separately in COOKIE_STORE_DIR via the Playwright persistent context.
"""

HTTPCACHE_ENABLED: bool = False
"""
Disabled for crawl production runs — caching would mask content changes
that Stage 2's change detection is designed to surface.  May be enabled
during development for rapid spider iteration.
"""

LOG_LEVEL: str = "INFO"

FEEDS: dict = {}
"""No Scrapy feed export — output is managed entirely by the item pipeline chain."""

# TODO: configure EXTENSIONS if/when a custom Scrapy extension is needed for
# alert emission (e.g., a spider_closed handler that checks domain failure rate
# and fires Critical alert).  The Critical alert wired into Phase A is currently
# implemented inside the spider's spider_closed handler directly.
# Spec ref: Phase A build sequence — "include the Critical-severity alert".
