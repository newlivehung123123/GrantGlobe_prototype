# GrantGlobe Stage 2: Crawler — Complete Technical Design

**Version:** 1.7  
**Author:** Jason Hung  
**Date:** May 2026  
**Status:** Implementation-ready  
**Revision note (v1.1):** Incorporates first openclaw review — robots.txt policy, stealth library reassessment, storage sizing, hardware requirements, link filter path-based matching, OCR threshold fix, language detection library upgrade, XHR heuristic broadening, sitemap.xml pre-flight, per-domain rate limits, alerting, incremental scheduling feedback loop, tab navigation config flag.  
**Revision note (v1.2):** Incorporates second openclaw review — stealth library naming consistency (diagram + Phase A), cookie security (encrypted separate store), networkidle hard timeout cap (20s), selective per-page OCR (merge PyMuPDF + OCR output), daily-domain exemption from downgrade logic, charset/encoding handling (charset-normalizer), change detection fallback for failed cycles, robots.txt override legal caveat.  
**Revision note (v1.3):** Incorporates third openclaw review — diagram [2.5] stealth library label corrected, Type 4 networkidle cap added (20s), charset/encoding detection relocated from 2.4 to 2.2, User-Agent pool updated to May 2026 browser releases with quarterly maintenance note, robots.txt Sitemap: directive parsed in pre-flight before fallback probe, SHA-256 specified as URL hash algorithm throughout, cookie consent selector narrowed to DOM-proximity requirement, crawl schedule timezone specified as UTC, new source onboarding process documented, dead domain sunset detection added, cross-domain deduplication added as known limitation.  
**Revision note (v1.4):** Incorporates fourth openclaw review — scrapy-rotating-proxies replaced with custom downloader middleware, pre-flight probe changed from HEAD to GET with Range: bytes=0-0, RSS/Atom feed detection added as pre-flight step, Profile C Playwright requirement changed to optional, downgraded domain re-engagement triggers immediate 1-hour re-crawl, PDF storage changed to content-SHA-256 filename with URL→hash mapping, Sec-Fetch-* headers documented as dynamic by request context, URL path splitting extended to include underscores, password-protected PDFs added to Known Limitations, Critical alert wired into Phase A build sequence, EXPECTED_CRAWL_DURATION_HOURS parameterised in settings.py, large PDF memory risk (pdf2image batch limit) added to Known Limitations.  
**Revision note (v1.5):** Incorporates fifth openclaw review — PDF filename normalised to {content_sha256} throughout (2.4 Step 7 and 2.6 schema tree corrected to match Step 2), RSS change detection replaced lastBuildDate/updated comparison with GUID-set comparison (lastBuildDate is unreliable across WordPress/Drupal), QA coverage metric given crawl_skip_reason: rss_no_change field to distinguish intentional feed-skip from blockage, daily crawl schedule time specified as 02:00 UTC, Phase A description updated to name RSS/feed detection explicitly.  
**Revision note (v1.6):** Incorporates sixth openclaw review — version header corrected from 1.4 to 1.5 in the prior release (v1.5); this release is 1.6. Hardware table blank-row issue confirmed absent in file. text/xml feed confirmation tightened to require <rss> or <feed> root element before acceptance. rss_guid_set clarified as bounded by feed exposure (10–20 items) and wholesale-replaced each cycle with no accumulation.  
**Revision note (v1.7):** Final pre-build additions — JSON-LD/Schema.org structured data extraction added to Sub-stage 2.2 (highest-accuracy signal, extracted before raw HTML processing); URL canonicalisation step added to Sub-stage 2.2 (normalises trailing slashes, scheme, www prefix, and path casing before SHA-256 hashing to prevent duplicate cache entries). Status updated to implementation-ready.

---

## Overview

Stage 2 is the most consequential component of GrantGlobe. Its output — the raw content cache — is the sole input to Stage 3's LLM extraction pipeline. Any funding opportunity that Stage 2 fails to retrieve is permanently invisible to GrantGlobe, regardless of how sophisticated Stage 3 is. Crawler design therefore determines the ceiling on GrantGlobe's recall.

The crawler must address four distinct technical problems simultaneously: intelligent multi-level depth traversal, anti-bot evasion, pagination across five structural patterns, and PDF extraction with OCR fallback. Each problem requires a dedicated solution; no single tool addresses all four.

The design is organised as eight sub-stages (2.1–2.8) that execute in sequence per crawl cycle.

---

## Architecture Diagram

```
Source List (582 seeds)
        │
        ▼
[2.1] Seed Classification & Pre-flight
   ├── robots.txt + sitemap.xml + RSS/Atom feed detection
   └── Domain type classification → crawl manifest per domain
        │
        ▼
[2.2] Adaptive Crawling Engine
   ├── Scrapy (orchestration, queue, deduplication)
   ├── scrapy-playwright (JS rendering)
   ├── [stealth library — TBD pre-Phase A] (fingerprint evasion)
   ├── JSON-LD/Schema.org extractor (structured data, highest accuracy)
   ├── URL canonicalisation (pre-hash normalisation)
   └── Link Intelligence Filter
        │  raw HTML + PDF binaries
        ▼
[2.3] Pagination Handler
   ├── URL-based pagination
   ├── Button/JS "Load more"
   ├── Infinite scroll
   ├── Tab/filter navigation
   └── XHR/API interception
        │
        ▼
[2.4] PDF Extraction Pipeline
   ├── Detection
   ├── PyMuPDF (primary extraction)
   ├── pdfplumber (table-heavy fallback)
   └── pytesseract + pdf2image (OCR fallback)
        │
        ▼
[2.5] Anti-Bot Evasion Stack
   ├── [stealth library — TBD pre-Phase A] (fingerprint patching)
   ├── Header authenticity
   ├── Behavioural humanisation
   ├── Cookie/session management
   ├── CAPTCHA detection & graceful degradation
   └── Retry/backoff logic
        │
        ▼
[2.6] Content Storage
   └── Structured cache: raw HTML, PDFs, extracted text, metadata
        │
        ▼
[2.7] Quality Assurance & Coverage Reporting
        │
        ▼
[2.8] Orchestration & Scheduling
        │
        ▼
Stage 3 Input: raw_cache/ + crawl_report_{date}.json
```

---

## Sub-stage 2.1: Seed Classification and Pre-flight Assessment

Before the main crawl begins, a lightweight pre-flight pass over all 582 `grants_url` entries produces a **crawl manifest** that assigns each domain a crawl strategy. This prevents the main crawler from applying a one-size-fits-all approach to structurally different sites.

### robots.txt policy

Before any crawling begins, the crawler fetches and parses `robots.txt` for every domain. GrantGlobe's explicit policy is:

- **Respect `Disallow` directives for paths unrelated to grants** — the crawler does not override robots.txt globally. Scraping staff directories, admin panels, or user account pages that are disallowed is both unnecessary and legally questionable under the Computer Fraud and Abuse Act and equivalent statutes in other jurisdictions.
- **Override `Disallow` for grant-relevant paths if the funder's public interest mission makes the information intended for public access** — grant announcements are public-facing by design. If a funder disallows `/grants/` in robots.txt (almost certainly a misconfiguration or a generic template), the crawler follows the grant-relevant path only, logs the override, and records a justification note in `crawl_manifest.json`. **Legal note:** The *hiQ Labs v. LinkedIn* precedent (9th Circuit, US) supports scraping of publicly accessible data, but this case is US-specific, is still being litigated at the margins, and does not bind courts in other jurisdictions. The override policy as stated is reasonable for prototype use where crawl volume is low and no commercial harm to the funder is plausible. Before production deployment at scale, the override policy should be reviewed by legal counsel, particularly for domains in the EU (where GDPR and the Database Directive may apply independently of robots.txt), and for any domain that has explicitly communicated objection to automated access.
- **Honour `Crawl-delay` directives** — if robots.txt specifies a crawl delay, it is used as the floor for inter-request delay for that domain, overriding the Gaussian default.

Scrapy's default `ROBOTSTXT_OBEY = True` is therefore kept, but a custom `RobotsTxtMiddleware` subclass is implemented that permits override on a per-domain basis when the domain is explicitly whitelisted in `crawl_manifest.json` with a `robots_override: true` flag and a written justification. This decision is logged and auditable.

### Sitemap.xml check

Before depth-crawling a domain, the pre-flight module determines the sitemap URL through a two-step process. First, the already-parsed `robots.txt` is checked for a `Sitemap:` directive (e.g., `Sitemap: https://example.org/grant-sitemap.xml`). When present, this directive is authoritative — it reflects the funder's own declaration of where their sitemap lives, and is used directly without further guessing. If no `Sitemap:` directive appears in `robots.txt`, the module falls back to probing `{domain}/sitemap.xml` and, for multi-sitemap sites, `{domain}/sitemap_index.xml`.

Once the sitemap URL is resolved by either path, it is fetched and parsed. URLs within the domain that contain grant-signal path segments are extracted directly and added to the crawl queue at depth 1, bypassing the need to discover them via link following. This reduces unnecessary traversal, surfaces deeply nested grant pages that the link filter might miss, and provides an accurate map of the grants section structure before any page is rendered.

If neither the `Sitemap:` directive nor the fallback probe yields a valid sitemap (HTTP 404 on the fallback), depth-crawling proceeds as normal. Sitemap availability and the source of the sitemap URL (directive or fallback) are recorded in `crawl_manifest.json`.

### RSS/Atom feed detection

RSS and Atom feeds are the highest-value-per-byte signal source available to GrantGlobe: they require zero Playwright sessions, zero depth-crawling, and deliver new grant announcements the moment a funder publishes them. Several of the ~40 high-activity daily-schedule domains publish feeds. The pre-flight module checks for feed availability through three methods, in order:

1. **HTML `<link>` autodiscovery** — the seed page's `<head>` is inspected for `<link rel="alternate" type="application/rss+xml">` or `<link rel="alternate" type="application/atom+xml">` elements. This is the standard machine-readable feed declaration and is present on most WordPress, Drupal, and Joomla-based grant sites.
2. **Common path probe** — if no `<link>` declaration is found, the module probes a short list of conventional feed paths: `/feed`, `/rss`, `/rss.xml`, `/atom.xml`, `/feed.xml`, `/news/feed`. A 200 OK response with a `Content-Type` of `application/rss+xml` or `application/atom+xml` is treated as a confirmed feed. Responses with `Content-Type: text/xml` require one additional check: the root element of the parsed XML must be `<rss>` or `<feed>` before the response is accepted as a feed. This prevents misidentification of sitemaps, SOAP responses, or generic XML APIs that happen to share a probe path — `text/xml` is used by all of these and the Content-Type alone is insufficient to distinguish them.
3. **robots.txt and sitemap cross-reference** — some funders declare their feed URL inside their sitemap or robots.txt comments; the already-parsed content from those steps is checked for feed URL patterns as a final fallback.

When a feed is confirmed, it is stored in `crawl_manifest.json` as `rss_feed_url`. During each crawl cycle, the feed is fetched before the main depth-crawl of that domain. Feed items are parsed with **feedparser** (Python). Each item's `link` field is extracted, checked against the domain's URL deduplication set, and — if new — added to the crawl queue at depth 0 with a `source: rss` flag. This means new grant announcements discovered via feed are fetched as full pages (not taken as feed summaries alone, since feed descriptions are frequently truncated). The feed fetch is additionally used for **change detection** via GUID-set comparison, not timestamp comparison. `lastBuildDate` and `updated` are among the most poorly maintained fields in RSS and Atom: many WordPress and Drupal installations never update `lastBuildDate` after initial setup, or set it to the publication date of the oldest post rather than the most recent. Relying on these fields to skip a depth-crawl would cause missed grants on any site where the field is stale. The reliable method is: after parsing the feed, extract the set of item identifiers — the `<guid>` value for each item, or the `<link>` value if no `<guid>` is present. Compare this set against the set stored from the previous cycle in `crawl_manifest.json` as `rss_guid_set`. If the current set contains any GUIDs not present in the stored set, new items exist and the full depth-crawl proceeds. If the sets are identical, the full depth-crawl is skipped for that cycle and `crawl_skip_reason: rss_no_change` is written to `manifest.json` (see Sub-stage 2.7 below). The current GUID set is written back to `crawl_manifest.json` after each cycle, replacing the previous one wholesale — old GUIDs do not accumulate across cycles. The set is bounded by whatever items the feed exposes at fetch time, which for the overwhelming majority of RSS and Atom feeds is 10–20 items. There is no risk of unbounded growth in `crawl_manifest.json`. This is a few extra lines of set comparison but removes any reliance on unreliable timestamp fields.

Feed availability is recorded in `crawl_manifest.json`. Domains with confirmed feeds are eligible for the incremental schedule downgrade logic to be bypassed entirely — feed-based change detection is more granular and responsive than the content-hash comparison used for non-feed domains, making frequency downgrading unnecessary.

### Pre-flight checks (per seed URL)

For each seed, the pre-flight module issues a lightweight GET request with a `Range: bytes=0-0` header and records:

- **HTTP status** — is the domain reachable?
- **Content-Type** — is the grants_url itself a PDF rather than an HTML page?
- **Bot-protection headers** — presence of `cf-ray` (Cloudflare), `x-sucuri-id` (Sucuri), or `server: nginx` with unusual response patterns
- **Redirect chain** — has the grants_url moved? Record the final landing URL
- **Response time** — flag slow domains (>5s) for extended timeout configuration
- **robots.txt status** — fetched and parsed; crawl-delay directive recorded
- **Sitemap availability** — sitemap.xml fetched and grant-relevant URLs extracted if present

### Domain type classification

Based on pre-flight results, each domain is assigned one of four crawl profiles:

| Profile | Characteristics | Playwright required | Stealth required |
|---|---|---|---|
| A — Simple HTML | Static pages, no JS rendering needed | No | No |
| B — JS-heavy | Content requires JavaScript execution | Yes | Optional |
| C — PDF-dominant | Grants published as downloadable PDFs | Optional (enable only if Phase A shows PDF links require JS rendering; most government PDF archives expose `<a href=".pdf">` in raw HTML, which Scrapy's native parser handles without Playwright) | Optional |
| D — Protected | Cloudflare/bot-protection detected | Yes | Yes |

Profile assignment is stored in `crawl_manifest.json` alongside the per-domain maximum depth setting (see Sub-stage 2.2).

---

## Sub-stage 2.2: Adaptive Crawling Engine

### Core framework

**Scrapy** serves as the crawl orchestration layer. It manages the URL queue, deduplication, concurrency, politeness delays, and pipeline routing. It does not render JavaScript natively, which is why scrapy-playwright is integrated at the downloader middleware level.

**scrapy-playwright** intercepts every Scrapy request assigned to a Playwright-required domain and routes it through a managed Playwright browser instance instead of Scrapy's default HTTP client. The rendered HTML is returned to Scrapy's spider as if it were a normal response. This integration is transparent to the spider logic.

### Depth strategy

Crawl depth is configured per-domain in the crawl manifest, not globally. The general rules are:

- **Depth 2** for most philanthropic foundations and smaller research councils, where the structure is: grants index (depth 0) → individual opportunity page (depth 1) → eligibility/application sub-page (depth 2)
- **Depth 3** for large multilateral agencies (World Bank, ADB, UNDP, OAS, JST) and government research councils with complex programme structures, where opportunities may span three levels of sub-pages before reaching full eligibility criteria

Pages at depth 0 (the seed grants_url) have all intra-domain links extracted and scored. Pages at depth 1 and beyond have links filtered by the relevance scoring system described below.

### Link Intelligence Filter

Not all links on a grants page should be followed. A naive "follow everything" approach at depth 2–3 would crawl staff directories, news archives, and annual reports — wasting resources and polluting the Stage 3 input cache.

Every candidate link extracted from a page passes through a two-tier filter before being added to the crawl queue.

**Tier 1 — Hard exclusions (discard immediately):**
- External domain (different root domain from the seed)
- Fragment-only URL (`#section-name`)
- Non-HTTP scheme (`mailto:`, `tel:`, `javascript:`, `ftp:`)
- Already queued or visited (Scrapy's built-in deduplication)
- Non-HTML, non-PDF file extension (`.jpg`, `.png`, `.mp4`, `.zip`, `.doc`, `.xls`, `.ppt`)
- URL depth exceeds domain maximum

**Tier 2 — Relevance scoring:**

Each candidate link that passes Tier 1 receives a relevance score computed from its URL path segments and anchor text. Critically, negative signals are matched against **URL path segments in isolation** rather than against the URL string as a whole. This prevents false negatives such as discarding `/news/call-for-proposals-2026/` because the path contains `news`, or dropping `/events/grant-award-ceremony/` because it contains `event`. The path is split on `/`, `-`, and `_` and each segment is evaluated independently. Splitting on underscores is necessary because government portals — particularly in Asia and Latin America — use underscores as word separators as frequently as hyphens. Without underscore splitting, a URL like `/grant_opportunities/funding_call/` produces a single unsplit token `grant_opportunities` that does not match the positive signals list, causing a false discard.

*Positive signals (+1 per URL path segment keyword, +2 per anchor text keyword):*
`grant`, `call`, `fund`, `award`, `fellow`, `scholar`, `apply`, `application`, `deadline`, `rfp`, `rfa`, `rfq`, `opportunity`, `programme`, `program`, `bursary`, `stipend`, `scholarship`, `prize`, `competition`, `open`, `current`, `active`, `invitation`, `proposals`

*Negative signals (−2 only when the path segment is a standalone navigation-level segment, i.e., it appears as a top-level or second-level directory without grant-positive neighbours):*
`staff`, `team`, `about`, `contact`, `privacy`, `cookie`, `login`, `register`, `career`, `job`, `gallery`, `photo`, `donate`, `volunteer`, `sitemap`, `search`, `404`

`news`, `blog`, `event`, `press`, `media`, `archive`, `tag`, `category` are **not** applied as blanket negative signals. Instead, pages containing these segments are scored based on whether grant-positive signals appear elsewhere in the same URL path or anchor text. A page at `/news/call-for-proposals/2026` scores +1 (grant-positive `call` and `proposals` outweigh `news`). A page at `/news/annual-report-2025` scores −2 and is discarded.

Links scoring ≥ 0 are added to the crawl queue. Links scoring < 0 are discarded. At depth 0 (the seed page itself), the scoring threshold is relaxed to ≥ −1 to ensure broad initial coverage before filtering tightens at greater depth.

### Page type classification

Once a page is fetched and rendered, it is classified before being written to the cache. The classification uses keyword-density analysis on the page's extracted text:

| Page type | Key signals | Action |
|---|---|---|
| Grant listing/index | Multiple opportunity titles, pagination controls, "apply by", "deadline" repeated | Extract links + save to cache |
| Individual opportunity | Single grant title, specific deadline, funding amount, eligibility section | Save to cache, follow eligibility/apply sub-links |
| Eligibility/application | "who can apply", "requirements", "how to apply", "documents needed" | Save to cache, no further link following |
| Irrelevant | Dominated by staff names, news dates, navigation elements | Discard |

The page type classification is stored in each page's `.meta.json` file. Stage 3 uses this to prioritise which pages the LLM processes, avoiding expenditure on irrelevant content.

### JSON-LD and Schema.org structured data extraction

Before processing a fetched page as raw HTML, the crawler checks for embedded machine-readable structured data. Many modern grant websites — particularly well-resourced foundations and international agencies — embed JSON-LD or Schema.org markup directly in their HTML `<head>` or `<body>`, like this:

```html
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Grant",
  "name": "Research Excellence Fellowship 2026",
  "deadline": "2026-09-30",
  "funder": {"@type": "Organization", "name": "Wellcome Trust"},
  "description": "Open to early-career researchers..."
}
</script>
```

This data is already structured, already labelled, and already accurate — the funder placed it there deliberately for machine consumption. Extracting it at crawl time is the highest-accuracy path available: it bypasses the need for Stage 3's LLM to re-derive information from prose, eliminating hallucination risk for the fields it covers.

The extraction procedure: (1) parse all `<script type="application/ld+json">` elements in the fetched page; (2) attempt to deserialise each as JSON; (3) if the result contains a `@type` field matching grant-relevant schema types (`Grant`, `FundingOpportunity`, `EducationalOccupationalProgram`, or `Event` with funding-related properties), extract the structured fields; (4) store the extracted JSON as `{url_hash}.jsonld` in the `pages/` directory alongside the raw HTML; (5) record `has_structured_data: true` in `.meta.json`. Stage 3 checks for this file first: if it exists, the structured fields are used directly and the LLM extraction pass is scoped only to fields not covered by the structured data. If no JSON-LD is present, Stage 3 falls back to full LLM extraction from HTML as normal.

This is a zero-extra-cost signal — the data is already in the page — and it materially improves extraction accuracy for the subset of sources that publish it. Even partial JSON-LD coverage (e.g., only the deadline and funder name structured, with eligibility left as prose) reduces the LLM's extraction burden and the surface area for hallucination.

### URL canonicalisation

Before computing the SHA-256 hash used as a URL identifier throughout the cache, every URL is passed through a canonicalisation step to eliminate variants that point to the same resource but produce different hashes. Without this, the same grant page reachable at `http://example.org/grants/`, `https://www.example.org/grants`, and `HTTPS://Example.Org/Grants/` would be stored as three separate cache entries.

Canonicalisation rules applied in order:
1. Convert scheme to lowercase (`HTTP` → `http`, `HTTPS` → `https`)
2. Upgrade `http` to `https` (all modern grant sites support HTTPS; treating HTTP as a distinct scheme creates spurious duplicates)
3. Strip the `www.` prefix from the hostname (`www.example.org` → `example.org`)
4. Lowercase the entire hostname
5. Normalise the path: collapse double slashes, resolve `.` and `..` segments, lowercase the path, add a trailing slash to bare paths (e.g., `/grants` → `/grants/`)
6. Strip tracking query parameters (`utm_source`, `utm_medium`, `utm_campaign`, `fbclid`, `gclid`, and equivalents) while preserving content-affecting parameters (e.g., `?page=2`, `?lang=en`)
7. Remove the fragment (`#section-name`)

The SHA-256 hash is computed from the normalised URL string after all seven steps. The normalised URL is also stored in `.meta.json` alongside the original URL so that the mapping between the canonical identifier and the original link is always recoverable.

### HTML charset detection and decoding

Before page text is written to the cache, all HTML responses pass through a charset detection and normalisation step. This step applies to HTML pages only; PDFs are handled internally by PyMuPDF.

**charset-normalizer** is used in preference to `chardet` because it is more accurate on Arabic and CJK scripts and is the library used internally by the `requests` library. Non-UTF-8 pages are common across several of GrantGlobe's source regions: Arabic grant sites frequently use Windows-1256, some East Asian government portals use GB2312 or EUC-KR, and some Eastern European sources use ISO-8859-2. Without explicit charset detection, these pages produce garbled text that the Stage 3 LLM cannot parse meaningfully.

The decoding pipeline: (1) check the HTTP `Content-Type` header for a `charset` parameter; (2) if absent or incorrect, check the HTML `<meta charset>` tag; (3) if neither is present or trustworthy, run `charset-normalizer` on the raw bytes to detect the encoding; (4) decode using the detected encoding; (5) record the detected encoding in `.meta.json`. All text written to the cache is stored as UTF-8 regardless of source encoding.

---

## Sub-stage 2.3: Pagination Handler

Grant listing pages frequently spread opportunities across multiple pages. Five structural patterns require distinct solutions.

### Type 1 — URL-based pagination

Pages with explicit URL parameters (`?page=2`, `/page/2/`, `?offset=20`, `?start=10`) or `rel="next"` link elements in the HTML head. Scrapy's `LinkExtractor` with a broad pattern match detects these automatically. Additionally, the spider explicitly checks for `<link rel="next">` in the page head and adds the target URL to the queue.

### Type 2 — Button or link "Load more" / "Next" triggered by JavaScript

The "Load more" button exists in the DOM but its click triggers a JavaScript fetch that appends new content to the page without a URL change. Scrapy's link extractor cannot see this content because it was never in the initial HTML.

**Solution:** Playwright executes a click sequence on the button element (identified by CSS selectors `[class*="load-more"]`, `[class*="pagination"]`, text content matching "Load more", "Show more", "Next") and waits for `networkidle` with a hard timeout cap of **20 seconds**. Sites with persistent WebSocket connections or long-polling mechanisms (increasingly common in modern grant portals) can cause `networkidle` to wait indefinitely, stalling the entire crawl queue. The cap ensures no single page blocks the crawler for more than 20 seconds; if the cap fires before `networkidle`, the page is extracted as-is and the next iteration proceeds. After each click, the full page HTML is re-extracted. The sequence repeats until the button disappears from the DOM or a safety limit of 20 click iterations is reached.

### Type 3 — Infinite scroll

No button exists; new content loads as the user scrolls to the bottom of the page.

**Solution:** Playwright executes `window.scrollTo(0, document.body.scrollHeight)` and waits for `networkidle` with a hard timeout cap of **20 seconds** (same rationale as Type 2 — persistent connections must not stall the queue). The count of grant-relevant elements (identified by CSS selectors for listing cards or table rows) is recorded before and after each scroll. If the count increases, scrolling continues. If the count does not change across two consecutive scrolls, or a safety limit of 30 scroll iterations is reached, the sequence stops and the final rendered HTML is extracted.

### Type 4 — Tab or filter navigation

Some sites segment grants by status (Open / Closed / Upcoming) or by thematic area using clickable tabs or filter buttons. A default page load may show only "Open" grants, hiding all other categories.

**Solution:** Playwright identifies all tab and filter elements matching common selectors (`[role="tab"]`, `[class*="filter"]`, `[class*="tab"]`) and iterates through each, clicking it, waiting for `networkidle` with a hard timeout cap of **20 seconds** (same rationale as Types 2 and 3 — persistent connections must not stall the crawl queue), and extracting the resulting HTML as a separate page entry in the cache. Each tab's content is stored as a distinct cache entry with the tab label recorded in its `.meta.json`.

**Tab scope configuration:** All tabs — including "Closed", "Past", and "Upcoming" — are crawled by default. Closed and past grant pages are valuable to GrantGlobe because they establish a funder's thematic scope, typical funding ranges, and eligibility patterns, which the LLM extraction pipeline can use to enrich context even when no active call is open. A per-domain `tab_filter` field in `crawl_manifest.json` allows specific tab labels to be excluded when a domain's closed-grants archive is excessively large and of low marginal value. This is opt-out, not opt-in: the default is to crawl all tabs.

### Type 5 — XHR/API-based loading

Some modern grant portals load content entirely via background API calls. The visible HTML is a shell; the actual grant data is fetched from a JSON endpoint and injected by JavaScript.

**Solution (primary):** Playwright's `page.on("response", handler)` intercepts all network responses during page load. JSON responses are evaluated by a structural heuristic rather than by specific field name matching — grant portals do not standardise field names, so matching on `deadline`, `title`, or `amount` alone would miss the majority of real-world APIs. The heuristic instead identifies a JSON response as grant-relevant if it satisfies two or more of the following conditions: (1) the response is an array or contains an array-valued key; (2) at least one string value in the first item contains a date-like pattern (ISO 8601, DD/MM/YYYY, or month-name formats); (3) at least one string value contains a currency symbol or a number preceded by a currency code; (4) the URL path of the API endpoint contains a grant-signal keyword; (5) the response contains any key whose value is a non-empty string of length > 50 (likely a description field). Responses meeting this threshold are saved as `.json` to the cache alongside a `.meta.json` recording the API endpoint URL and the matched conditions.

**Solution (fallback):** For domains where JSON interception is not configured or the heuristic does not fire, Playwright's `page.wait_for_load_state("networkidle")` ensures all XHR calls complete before HTML extraction begins, so the rendered HTML contains the injected content. This is the safe default for all domains until explicit API patterns are identified through Phase A output review.

---

## Sub-stage 2.4: PDF Extraction Pipeline

A significant portion of GrantGlobe's gap-flagged sources — particularly government research councils in the Global South, multilateral agencies, and regional development banks — publish grant announcements exclusively as PDF documents. A crawler that does not extract PDF content will systematically miss the most valuable opportunities in the source list.

### Step 1 — Detection

PDF links are identified by three criteria, checked in order:

1. `href` attribute ends in `.pdf` (case-insensitive)
2. HTTP response `Content-Type: application/pdf` after following any redirects
3. Anchor text matches high-signal patterns: "download", "call for proposals", "terms of reference", "application guidelines", "announcement", "concept note", "RFP", "RFA"

URLs matching criterion 3 but not 1 or 2 are fetched and their `Content-Type` is checked before PDF processing begins.

### Step 2 — Download

Scrapy's `FilesPipeline` downloads confirmed PDFs to `raw_cache/{domain}/{date}/pdfs/`. Each PDF is stored with a filename derived from its **content SHA-256 hash** (computed after download), not its URL hash. This distinction matters: if a funder silently overwrites a file at a stable URL — publishing a revised call-for-proposals as `call-2026.pdf` without changing the filename — a URL-hash scheme would silently overwrite the previously stored file with the new content, making the replacement undetectable. A content-hash scheme stores the new version as a distinct file. The URL-to-content-hash mapping is written to `crawl_manifest.json` as a `pdf_url_map` object (`{url: content_sha256}`), so that on the next cycle, a changed content hash at the same URL is detected and both the old and new versions are retained for the duration of the four-cycle PDF retention window. The `.meta.json` records both the original URL and the content SHA-256 hash.

### Step 3 — Primary text extraction

**PyMuPDF** (`fitz`) is run first on every downloaded PDF. It is the fastest available library, handles the majority of modern PDFs reliably, and preserves reading order better than most alternatives. For PDFs with embedded tables — common in eligibility matrices and budget guidelines — **pdfplumber** is run as a secondary pass to extract table content as structured text.

### Step 4 — Extraction quality assessment

After PyMuPDF runs, per-page character counts are computed. The OCR trigger is based on the **proportion of pages falling below the threshold**, not on any single page. A PDF is routed to OCR if **≥ 40% of its pages yield fewer than 100 characters after extraction**. This prevents false triggering on documents that have legitimate low-content pages — title pages, blank separator pages, appendix cover sheets — which are normal in multi-section grant documents and should not cause the entire document to be re-processed via OCR. A PDF with 10 pages where 3 yield < 100 characters (30%) is treated as text-based with sparse pages, not as scanned. A PDF where 6 of 10 pages yield < 100 characters is treated as scanned and routed to OCR.

### Step 5 — Selective OCR fallback

When a PDF crosses the ≥ 40% threshold, OCR is applied **only to the pages that failed extraction** — not to the entire document. Pages that PyMuPDF extracted successfully (≥ 100 characters) retain their PyMuPDF output, which is always higher quality than OCR on pages with embedded text (OCR introduces character-level errors even on clean scans). Pages that failed (< 100 characters) are routed to OCR individually. The final document text is assembled by merging PyMuPDF output for good pages with OCR output for failed pages, in original page order.

Per-page OCR procedure:
1. **pdf2image** converts only the failed pages to high-resolution PNG images (300 DPI)
2. **pytesseract** runs Tesseract OCR on each failed-page image
3. Language packs loaded: English (`eng`), French (`fra`), Spanish (`spa`), Arabic (`ara`) — covering the dominant languages of GrantGlobe's non-Western sources
4. OCR output and PyMuPDF output are merged in page order; the extraction method per page (`pymupdf` or `ocr`) is recorded in `.meta.json` for Stage 3 awareness

### Step 6 — Language detection

**lingua-py** is used for language detection in place of `langdetect`. The `langdetect` library is non-deterministic (it uses random seeding internally and can return different results on the same text across runs) and is unreliable on short texts below approximately 200 words — exactly the length of many grant summary paragraphs. `lingua-py` uses a statistical model trained on longer texts and produces deterministic, reproducible results with substantially higher accuracy on short inputs. For prototype purposes, the detector is configured to distinguish between: English, French, Spanish, Arabic, Portuguese, Chinese, Japanese, Korean — the languages most likely to appear in GrantGlobe's source list. Documents detected as non-English are flagged with their ISO 639-1 language code in `.meta.json`. Stage 3 uses this flag to route documents to a translation step before LLM extraction, or to skip them in the prototype phase.

### Step 7 — Text cleaning and storage

A cleaning pass removes: repeated headers/footers (detected by identical strings appearing at the top or bottom of ≥ 70% of pages), excessive whitespace, page number artefacts, and scanning noise characters. The cleaned text is stored as `{content_sha256}.txt` alongside the raw PDF binary (`{content_sha256}.pdf`), so that every file derived from a given PDF shares the same content-hash stem and the relationship between them is unambiguous.

---

## Sub-stage 2.5: Anti-Bot Evasion Stack

Anti-bot evasion is layered defence in depth. No single technique is sufficient; the stack functions as a combined system.

### Layer 1 — Browser fingerprint patching

Standard Playwright's headless Chrome is detectable by JavaScript running on the target page through several browser API signatures: `navigator.webdriver = true`, absence of the `chrome.runtime` object, missing browser plugin arrays, anomalous canvas rendering, and abnormal WebGL parameters.

**Library selection (resolved pre-build requirement):** The original design specified `playwright-stealth` (Python port). However, the Python port of `playwright-stealth` has had documented maintenance and compatibility gaps with recent Playwright releases, and its patch coverage has lagged behind the Node.js original. Before committing to this library, the following alternatives must be evaluated in order of current community support and patch completeness:

1. **`rebrowser-playwright`** — a fork of Playwright itself with stealth patches applied at the browser binary level rather than via JavaScript injection. This is more robust because patches survive JavaScript sandbox escapes that can expose injection-based approaches. Recommended as first choice if compatible with scrapy-playwright's integration layer.
2. **`undetected-playwright`** — applies patches at the CDP (Chrome DevTools Protocol) level. More compatible with Scrapy integration than `rebrowser-playwright` but patch coverage is narrower.
3. **`playwright-stealth` (Python)** — retained as fallback if neither above integrates cleanly with scrapy-playwright, with the understanding that it may require manual patching for Playwright version compatibility.

The choice between these three is a pre-Phase A technical decision. The evaluation criterion is: which library passes the standard bot-detection test suite (bot.sannysoft.com, creepjs, pixelscan.net) under scrapy-playwright's managed browser context without requiring ejection from Scrapy's middleware chain.

Patches required regardless of library: `navigator.webdriver`, `navigator.plugins`, `navigator.languages`, `navigator.permissions`, `chrome.runtime`, canvas 2D fingerprint, WebGL vendor/renderer strings, audio context fingerprint.

### Layer 2 — HTTP header authenticity

Every request carries a header set constructed to match a real browser session:

```
User-Agent: [rotated from pool — see below]
Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8
Accept-Language: en-US,en;q=0.9
Accept-Encoding: gzip, deflate, br
Connection: keep-alive
Sec-Fetch-Dest: document
Sec-Fetch-Mode: navigate
Sec-Fetch-Site: none
Sec-Fetch-User: ?1
Upgrade-Insecure-Requests: 1
```

The `Sec-Fetch-*` headers are critical, and they are **dynamic by request context** — not a static block applied identically to every request. The header set shown above is correct only for a cold initial navigation (the seed URL on first load). Sending `Sec-Fetch-Site: none` and `Sec-Fetch-User: ?1` on every sub-page request within a crawl session is a detectable bot fingerprint — real browsers only send those values on a cold first navigation, not on link-following. The correct values by request type are:

| Request context | Sec-Fetch-Site | Sec-Fetch-Mode | Sec-Fetch-Dest | Sec-Fetch-User |
|---|---|---|---|---|
| Cold initial navigation (seed URL) | `none` | `navigate` | `document` | `?1` |
| Link-following within same domain | `same-origin` | `navigate` | `document` | *(omit)* |
| Cross-origin resource (CSS/JS) | `same-origin` or `cross-site` | `no-cors` | `script` / `style` | *(omit)* |
| XHR/API call (Type 5 pagination) | `same-origin` | `cors` | `empty` | *(omit)* |

The Scrapy downloader middleware is responsible for setting these headers dynamically. A custom `SecFetchHeadersMiddleware` reads the request's `referer` and `meta['is_first_request']` fields to determine which context applies and constructs the appropriate header set before the request is dispatched. Many modern bot detectors (including Cloudflare's) fingerprint the consistency of these values against the referer chain — a mismatch is treated as an immediate signal of automated traffic.

**User-Agent pool:** 20 signatures drawn from real browser release strings, current as of May 2026: Chrome 124–136 on Windows 10/11, macOS 14/15, and Ubuntu 22/24; Firefox 125–138 on Windows and macOS; Safari 17–18 on macOS. One is selected per domain per crawl session and held constant throughout that session (rotating mid-session triggers bot detection on session-aware sites). **Maintenance requirement:** The UA pool must be refreshed quarterly. Bot-detection systems actively flag User-Agent strings for browsers that have passed their expected end-of-life window — a UA string for Chrome 120 becomes suspicious by mid-2026 as that version is no longer in active deployment. The pool is maintained in `settings.py` under `USERAGENT_POOL` and should be updated each quarter by consulting the current stable release numbers for Chrome, Firefox, and Safari.

### Layer 3 — Behavioural humanisation and per-domain rate limits

**Per-domain rate limit floor:** The Gaussian delay (mean 4s, SD 1.5s, clipped to [2, 10]) is the global default. Each domain in `crawl_manifest.json` carries a `rate_limit_floor_seconds` field that sets the minimum inter-request delay for that domain regardless of the global setting. This is a first-class configuration field, not an override. Sensitive domains — identified during pre-flight from response headers, robots.txt `Crawl-delay`, or prior 429 history — are assigned higher floors (e.g., 10–30 seconds). If robots.txt specifies a `Crawl-delay`, that value is automatically written to `rate_limit_floor_seconds` during pre-flight. The Gaussian noise is always added on top of the floor, never below it.

- **Inter-request delay:** Per-domain: `max(rate_limit_floor_seconds, Gaussian(4, 1.5))`, clipped to [floor, floor+15]. Predictable fixed delays are detectable; the Gaussian component ensures timing variability.
- **Extended reading pauses:** With 15% probability, a delay of 15–45 seconds is inserted after fetching a page classified as an individual opportunity (simulating a user reading the page).
- **Mouse movement:** Before clicking any pagination button or tab, Playwright executes a randomised mouse trajectory from the current position to the target element rather than a direct teleport.
- **Viewport randomisation:** Each browser session opens with a viewport sampled from common desktop sizes: 1280×800, 1366×768, 1440×900, 1920×1080, 2560×1440.
- **Scroll behaviour:** On long pages, Playwright scrolls gradually from top to bottom before extracting content, rather than jumping to full scroll height immediately.

### Layer 4 — Cookie and session management

Playwright's persistent browser context maintains cookies across all requests to a given domain within a crawl session. On the first request to a domain, cookie consent banners are detected and the accept button is clicked before content extraction begins. Detection requires two conditions to both be satisfied: (1) a button or link element whose visible text matches "accept", "agree", "I consent", "allow all", or equivalent; and (2) DOM proximity to an ancestor or sibling element that contains the words "cookie", "privacy", or "tracking" (checked via `closest()` or `querySelector` traversal within a three-level ancestor radius). Requiring DOM proximity prevents false-positive clicks on unrelated accept or agree buttons — such as terms-of-service modals or newsletter subscription prompts — that happen to use the same surface text but are structurally unrelated to cookie consent.

**Cookie storage security:** Session cookies are not stored in `crawl_manifest.json`. Cookies are live authentication-equivalent tokens — storing them in a general-purpose manifest file creates risk of accidental exposure through version control commits, log aggregation, or file sharing. Instead, cookies are persisted in a dedicated, permission-restricted file: `cookie_store/{domain}.enc`, encrypted at rest using Python's `cryptography` library (Fernet symmetric encryption with a key stored in an environment variable, never on disk alongside the encrypted data). `crawl_manifest.json` stores only a boolean `has_stored_cookies: true` and the cookie expiry timestamp — no credential material. The cookie store directory is explicitly listed in `.gitignore`. On subsequent crawl cycles, valid stored cookies are decrypted and injected into the new Playwright browser context before the first request, avoiding repeated session initialisation that can itself trigger bot detection.

### Layer 5 — CAPTCHA detection and graceful degradation

CAPTCHA presence is detected by checking page content for known strings: "I am not a robot", "verify you are human", "hCaptcha", "reCAPTCHA", "Please complete the security check". On detection, the domain is immediately flagged in the crawl report as `status: captcha_blocked`, the URL is skipped, and no further crawl attempts are made during the current cycle. No CAPTCHA-solving is attempted in the prototype phase. Domains flagged across two consecutive crawl cycles are promoted to a manual review queue.

### Layer 6 — Proxy configuration (production phase only)

During prototype development, crawling from a residential IP address (home or office network) is substantially less likely to trigger bot detection than crawling from a cloud datacenter IP. Cloudflare and similar systems maintain datacenter IP blacklists; residential IPs are not on these lists by default.

In production, a rotating residential proxy pool (Oxylabs, Bright Data, or equivalent) is integrated at the Scrapy downloader middleware level. Proxy rotation occurs per domain per session, not per request (per-request rotation triggers fingerprint inconsistency detection). Domains classified as Profile D (protected) always use residential proxies; Profiles A–C use the direct connection in the prototype.

### Layer 7 — Retry and backoff logic

| HTTP status | Response | Max retries |
|---|---|---|
| 429 Too Many Requests | Exponential backoff starting at 60 seconds (60, 120, 240) | 3 |
| 403 Forbidden | Retry once with different User-Agent + fresh Playwright session | 1 |
| 503 Service Unavailable | Retry with 30-second fixed interval | 3 |
| Connection timeout (>30s) | Retry after 15 seconds | 2 |
| All retries exhausted | Log as `status: failed`, skip domain | — |

---

## Sub-stage 2.6: Content Storage Schema

All crawled content is written to a structured local cache directory. The schema is designed so that Stage 3 can be run independently of Stage 2 — re-running extraction against existing cache requires no re-crawling.

```
raw_cache/
│
├── {domain}/                          e.g., cartafrica.org/
│   ├── crawl_manifest.json            Domain-level config: profile, max_depth,
│   │                                  last_crawl_date, seed_url, proxy_required,
│   │                                  captcha_history, user_agent_assigned,
│   │                                  rate_limit_floor_seconds, robots_override,
│   │                                  tab_filter, crawl_frequency, sitemap_url,
│   │                                  consecutive_unchanged_cycles,
│   │                                  consecutive_failed_cycles,
│   │                                  dead_domain_candidate,
│   │                                  rss_feed_url, rss_guid_set,
│   │                                  pdf_url_map
│   │
│   └── {YYYY-MM-DD}/                  e.g., 2026-05-25/
│       ├── manifest.json              All pages fetched this cycle:
│       │                              [{url, url_hash, depth, http_status,
│       │                                content_type, page_type, char_count,
│       │                                crawl_timestamp, pdf_extracted}]
│       │                              Top-level fields: comparison_basis,
│       │                              crawl_skip_reason (e.g. rss_no_change)
│       │
│       ├── pages/
│       │   ├── {url_hash}.html        Raw rendered HTML (gzip compressed)
│       │   └── {url_hash}.meta.json   {url, depth, crawl_timestamp, http_status,
│       │                               content_type, page_type_classification,
│       │                               char_count, links_extracted, language}
│       │
│       └── pdfs/
│           ├── {content_sha256}.pdf         Raw PDF binary (filename = content SHA-256 hash)
│           ├── {content_sha256}.txt         Extracted/OCR text (cleaned)
│           └── {content_sha256}.meta.json   {url, content_sha256, source_page_url,
│                                             download_timestamp, file_size_bytes,
│                                             page_count, char_count,
│                                             extraction_method: pymupdf|pdfplumber|ocr|encrypted,
│                                             ocr_language, language_detected}
```

**Content deduplication:** The URL hash is computed as a **SHA-256** digest of the normalised URL (scheme + domain + path, query parameters stripped unless they affect page content), truncated to 16 hex characters for use as a filename. SHA-256 is chosen for its negligible collision probability at the scale of GrantGlobe's cache (< 10⁶ URLs), its availability in Python's standard library (`hashlib.sha256`), and its deterministic output across all platforms and Python versions. This prevents storing duplicate content when the same page is reachable via multiple URL variants.

**Change detection:** On subsequent crawl cycles, each newly fetched page's content hash is compared to the previous cycle's stored content hash. Pages with changed content are flagged in `manifest.json` as `changed: true`. Stage 3 processes changed pages on priority, avoiding re-extraction of unchanged content.

**Fallback for failed or missing previous cycles:** If a domain's previous crawl cycle failed entirely (no pages successfully stored), or if a domain is being crawled for the first time, there is no prior content hash to compare against. In this case, all pages fetched in the current cycle are treated as `changed: true` — the safe default that ensures Stage 3 processes the full content rather than silently skipping it. This is preferable to erroring (which would block Stage 3 for that domain) or to treating pages as `changed: false` (which would cause Stage 3 to skip genuinely new content). The `manifest.json` records a `comparison_basis: none` field when the fallback is applied, so Stage 3 can distinguish first-run processing from routine changed-page prioritisation.

### Storage retention policy and disk space estimates

**Retention:** The crawler retains the two most recent crawl cycles per domain (the current cycle and the previous cycle, used for change detection comparison). Older cycles are deleted automatically after each crawl completes. Raw PDFs are retained for four cycles given their higher extraction cost. This means at any time the cache holds at most two HTML snapshots and four PDF snapshots per domain.

**Disk space estimates** (per full crawl cycle, 582 domains, depth 2–3):

| Content type | Estimate per domain | Total (582 domains) |
|---|---|---|
| Rendered HTML pages (gzip compressed) | 0.5–2 MB | 300 MB – 1.2 GB |
| PDF binaries | 1–5 MB | 600 MB – 3 GB |
| Extracted text (.txt files) | 0.1–0.5 MB | 60–300 MB |
| Metadata (.meta.json files) | negligible | ~50 MB |
| **Total per cycle** | | **~1–4.5 GB** |

With the two-cycle HTML retention and four-cycle PDF retention policy, the steady-state cache size is approximately **3–10 GB**. This is manageable on a standard development machine (512 GB SSD) without additional storage provisioning. In production, an external drive or cloud object storage (S3, Backblaze B2) is recommended. Storage costs at Backblaze B2 rates (~$0.006/GB/month) for 10 GB are approximately $0.06/month — negligible.

---

## Sub-stage 2.7: Quality Assurance and Coverage Reporting

After all domains complete their crawl, an automated QA pass produces a machine-readable `crawl_report_{date}.json` and a human-readable summary log. This report is the formal handoff document from Stage 2 to Stage 3.

### Coverage metrics (per domain)

| Metric | Flag threshold | Interpretation |
|---|---|---|
| Pages fetched | = 1 (seed only) AND `crawl_skip_reason` absent | Likely blocked at depth 0; manual review |
| Pages fetched | = 1 (seed only) AND `crawl_skip_reason: rss_no_change` | Intentional skip — feed GUID set unchanged; not a failure |
| Grant-relevant pages / total pages | < 20% | Crawl drifted off-target; refine link filter |
| PDF extraction success rate | < 80% of detected PDFs | OCR or download failure; inspect logs |
| Depth distribution | All pages at depth 0 | No sub-pages found; site may be JS-only |
| Changed pages vs. previous crawl | > 30% | High activity; prioritise for Stage 3 |

### Content quality checks

- Pages with fewer than 300 characters of extracted text are flagged as `low_content` and deprioritised in Stage 3
- Pages where keyword density for grant-relevant terms is zero are flagged as `off_target`
- Domains with zero grant-relevant pages across all fetched content are escalated to `manual_review_required`

### Error summary

The report records per-domain counts of: 200 OK, 301/302 redirects, 403 Forbidden, 404 Not Found, 429 Rate Limited, 503 Unavailable, connection timeouts, CAPTCHA blocks, and PDF extraction failures.

### Output files

- `crawl_report_{date}.json` — machine-readable, consumed by Stage 3
- `crawl_summary_{date}.txt` — human-readable summary: domains completed, pages fetched, PDFs extracted, domains blocked, domains requiring manual review
- `manual_review_{date}.txt` — list of domains requiring human inspection with reason codes

---

## Sub-stage 2.8: Orchestration and Scheduling

### Crawl frequency

| Schedule | Domains | Rationale |
|---|---|---|
| Weekly (Sunday 02:00 UTC) | All 582 | Full refresh of entire source list |
| Daily (02:00 UTC) | ~40 high-activity domains | Sources with rolling deadlines or frequent new calls (AERC, OAS, ACSS, AI Singapore, JST, Volkswagen Foundation, Rosa Luxemburg, CARTA, HEC Pakistan, IITP, Zindi) |
| Triggered (on-demand) | Single domain | When a new source is added to source_list, or a manual review domain is re-attempted |

### Hardware requirements

Playwright browser instances are memory-intensive. Each concurrent browser context consumes approximately 150–300 MB of RAM depending on page complexity.

| Phase | CONCURRENT_REQUESTS | Browser instances | RAM required | Estimated full-crawl duration |
|---|---|---|---|---|
| Prototype (sequential) | 1 | 1 | ~500 MB | ~48–72 hours |
| Optimised prototype | 8 | 8 | ~2–4 GB | ~8–12 hours |
| Production | 32 | 32 | ~8–12 GB | ~2–3 hours |

**Prototype minimum spec:** Any modern development machine with ≥ 8 GB RAM (leaving 4–6 GB for the OS and other processes) runs the optimised prototype configuration comfortably. The sequential prototype runs on any machine with ≥ 4 GB RAM.

**Production spec:** 32 concurrent Playwright instances require a dedicated machine or VM with ≥ 16 GB RAM and ≥ 4 CPU cores. A cloud VM such as AWS `t3.2xlarge` (8 vCPU, 32 GB RAM, ~$0.33/hour) or equivalent is appropriate for production deployment. Running 32 Playwright instances on a machine with less than 16 GB RAM will cause OOM kills and crawl instability.

Concurrency is set conservatively in the prototype to minimise both bot detection risk and memory pressure. Per-domain request rate is always limited regardless of global concurrency setting.

### Alerting

The crawler emits alerts when crawl health degrades beyond defined thresholds. In the prototype, alerts are written to a dedicated `alerts_{date}.log` file and optionally sent via email (Python `smtplib`) or a webhook (Slack, Discord) configured in `settings.py`. Alert triggers:

| Condition | Threshold | Severity |
|---|---|---|
| Domains failed (all retries exhausted) | > 20% of domains in a cycle | Critical |
| Domains CAPTCHA-blocked | > 10 domains in a cycle | High |
| PDF extraction failure rate | > 25% of detected PDFs | High |
| Crawl cycle duration | > 2× `EXPECTED_CRAWL_DURATION_HOURS` (set in `settings.py`) | Medium |
| Domains with zero grant-relevant pages | > 30 domains | Medium |

A Critical alert indicates a systemic issue (IP block, proxy failure, library incompatibility) that warrants immediate investigation before Stage 3 is run on the resulting cache. Alerts at High or Medium severity are reviewed before the next scheduled cycle.

`EXPECTED_CRAWL_DURATION_HOURS` must be set in `settings.py` before the first crawl run. Recommended values: 72 (sequential prototype), 12 (optimised prototype at 8 concurrent), 3 (production at 32 concurrent). Without a concrete anchor, the 2× multiplier has no meaning — in the sequential prototype, 2× of an unset value would never fire at a useful threshold.

### Incremental scheduling feedback loop

The `consecutive_unchanged_cycles` field in `crawl_manifest.json` tracks how many successive crawl cycles a domain has produced no content changes (based on the change detection hash comparison in Sub-stage 2.6). Domains that have been unchanged for three or more consecutive weekly cycles are automatically downgraded to bi-weekly crawl frequency. Domains unchanged for six or more consecutive weekly cycles are downgraded to monthly. When a domain that has been downgraded produces a content change, two actions are taken simultaneously: (1) its crawl frequency is immediately restored to the default weekly schedule; and (2) a one-off triggered re-crawl of that domain is scheduled to execute within one hour of change detection. The frequency restoration alone would leave a gap of up to a week before the next crawl captures the full updated content — the immediate re-crawl closes this window. The triggered re-crawl is a full single-domain crawl (equivalent to the on-demand mode used in new source onboarding) and its output is written to the current cycle's date directory as a supplementary entry.

**Daily-schedule domains are explicitly excluded from the downgrade logic.** The ~40 high-activity domains assigned to daily crawling (AERC, OAS, ACSS, AI Singapore, JST, Zindi, and others) are designated daily because they are known to operate rolling deadlines or post new calls frequently. A quiet month on one of these sources does not mean it has become low-activity — it may simply be between cycles. Auto-downgrading AERC after three quiet weeks and then missing a new call announcement is precisely the failure mode the daily schedule is designed to prevent. The `crawl_frequency` field in `crawl_manifest.json` carries a `downgrade_protected: true` flag for all daily-scheduled domains; the downgrade logic reads this flag before applying any frequency change and skips the domain if it is set. Downgrade protection can be manually removed from any domain if sustained evidence (six or more months of confirmed inactivity) justifies it.

### New source onboarding

When a new domain is added to `source_list.csv`, it is not inserted into the weekly batch directly. Instead, the `triggered` schedule in the table above is used: the pre-flight module runs immediately against the new seed URL, assigns a crawl profile (A–D) and a default depth setting, writes an initial `crawl_manifest.json` for the domain, and executes a single on-demand crawl cycle. The resulting cache and QA report are reviewed before the domain is enrolled into the standard weekly schedule. This one-time pre-flight pass ensures that misconfigured seeds, bot-protected domains, or PDF-only sources are identified and handled before they silently fail inside a batch run. The `crawl_frequency` field in the new domain's manifest is initially set to `triggered` and updated to `weekly` (or `daily` for designated high-activity sources) only after the first successful on-demand cycle produces a non-empty grant-relevant page set.

### Dead domain sunset detection

The `consecutive_failed_cycles` field in `crawl_manifest.json` records how many successive crawl cycles a domain has returned only failure statuses (all retries exhausted, HTTP 4xx/5xx across all seed URLs, zero pages successfully fetched). Domains that accumulate three or more consecutive failed cycles are automatically escalated to a **dead domain candidate** queue: they are removed from the active crawl schedule, a `dead_domain_candidate: true` flag is written to their manifest, and an entry is added to `manual_review_{date}.txt` with the failure history. A human reviewer then determines whether the domain has permanently moved (warranting a `grants_url` update in `source_list.csv`), is temporarily offline (warranting a manual re-attempt after an interval), or has shut down entirely (warranting removal from the source list). The crawler does not make this determination autonomously, as the distinction between a temporarily unreachable server and a permanently dead domain requires judgement that automated metrics cannot reliably supply. The three-cycle threshold is chosen to avoid premature escalation from transient outages while ensuring that systematically dead domains do not continue consuming crawl resources.

### State persistence

Scrapy's `JOBDIR` setting persists crawl state (visited URL fingerprints, pending queue) across interrupted runs. If the crawler is stopped mid-run — due to power loss, network failure, or manual interruption — it resumes from where it stopped on next execution rather than restarting the entire crawl.

### Tooling summary

| Function | Tool | Notes |
|---|---|---|
| Crawl orchestration | Scrapy 2.11+ | |
| JavaScript rendering | scrapy-playwright (Playwright 1.44+) | |
| Fingerprint evasion | rebrowser-playwright **or** undetected-playwright **or** playwright-stealth | **Pre-build decision required** — evaluate against bot-detection test suite before Phase A |
| PDF text extraction (primary) | PyMuPDF (fitz) | |
| PDF text extraction (tables) | pdfplumber | Secondary pass for table-structured content |
| OCR | pytesseract + pdf2image (Tesseract 5.x) | Triggered when ≥ 40% of pages yield < 100 chars |
| Language detection | lingua-py | Replaces langdetect — deterministic, reliable on short texts |
| Scheduling | APScheduler 3.x | |
| State persistence | Scrapy JOBDIR (SQLite backend) | |
| RSS/Atom feed parsing | feedparser | Pre-flight feed detection and per-cycle feed fetch |
| Proxy integration (production) | Custom downloader middleware (~40 lines) | Replaces scrapy-rotating-proxies — unmaintained since 2022, incompatible with Scrapy 2.11+ |
| Charset detection | charset-normalizer | Applied to all HTML before text extraction; decodes non-UTF-8 pages |
| Cookie encryption | cryptography (Fernet) | Cookies stored encrypted; key via environment variable |
| Alerting (prototype) | Python smtplib / webhook | Email or Slack/Discord notification |
| Structured data extraction | Python standard library (json) | Extracts JSON-LD/Schema.org from HTML before LLM processing |
| URL canonicalisation | Python standard library (urllib.parse) | Normalises URLs before SHA-256 hashing |

---

## Prototype Build Sequencing

Stage 2 does not need to be fully built before it can produce value. The recommended build sequence is:

**Phase A (weeks 1–2):** Full pre-flight (robots.txt parsing, sitemap discovery, RSS/Atom feed detection) + Scrapy + scrapy-playwright + chosen stealth library (evaluated and selected pre-Phase A per the criteria in Sub-stage 2.5 Layer 1) + link intelligence filter + depth 2 for all domains. **Include the Critical-severity alert** (> 20% domain failures) from the outset — this is a 10-line addition to the spider's `spider_closed` handler and is an operational necessity from the very first run. Phase A will crawl 582 domains with an untested stealth library and new depth configuration; without the Critical alert, a 20%+ failure rate from an IP block or library incompatibility will be invisible until the crawl completes. Set `EXPECTED_CRAWL_DURATION_HOURS` in `settings.py` before the first run. This phase delivers crawl coverage for ~70% of the source list immediately.

**Phase B (week 3):** Pagination handler (Types 1 and 2 first, then 3 and 4). This captures opportunities hidden behind "Load more" buttons and standard next-page links, which account for the majority of pagination patterns. Add High and Medium severity alerts alongside pagination.

**Phase C (week 4):** PDF extraction pipeline (PyMuPDF + pytesseract). This unlocks the Global South government sources that publish grants as PDFs — the highest-value gap-flagged entries in the source list.

**Phase D (ongoing):** Full QA reporting, change detection, incremental scheduling, dead domain sunset logic. Refine link filter rules based on actual crawl output. Add proxy rotation when domains with persistent 403s are identified.

---

## Known Limitations and Accepted Tradeoffs

**CAPTCHA-protected domains** will not be crawled automatically. These are logged and flagged for manual review. In the prototype, this is an accepted limitation. Post-funding, CAPTCHA-solving services (2captcha, Anti-Captcha) can be integrated.

**Login-gated content** — opportunities that require registration to view — is not accessible to the crawler. These represent a small fraction of GrantGlobe's source list.

**Non-English PDF content** — PDFs in Arabic, Chinese, Portuguese, or other languages — will be detected and flagged, but not translated or extracted in the prototype phase. This is a known gap that limits coverage of some non-Western sources.

**Dynamic single-page applications (SPAs)** with hash-based routing (e.g., `/#/grants/current`) may not be fully navigable by Scrapy's link extractor even with Playwright rendering. These require per-domain custom spider logic and are handled as they are identified during Phase A crawl output review.

**Password-protected PDFs** — PyMuPDF raises an exception when it encounters an encrypted PDF. Government and multilateral sources occasionally publish password-protected documents (usually the result of old template defaults rather than intentional restriction). These are not silently swallowed: the exception is caught, the PDF is logged as an extraction failure with `extraction_method: encrypted` in its `.meta.json`, and the failure is counted in the QA report's PDF extraction success rate metric.

**Large PDF memory consumption** — pdf2image at 300 DPI on a large document (50+ pages, and some multilateral agency publications run to 200+ pages) can consume several gigabytes of RAM when all pages are converted simultaneously. In the OCR fallback step (Sub-stage 2.4, Step 5), pdf2image must be called with a page batch limit — processing at most 10 pages per batch — to prevent OOM conditions during Phase C, particularly on the optimised prototype (8 GB RAM). The batch loop is: convert pages 1–10, run Tesseract, write output, free memory, convert pages 11–20, and so on.

**Cross-domain deduplication** is outside Stage 2's scope and is an explicit known gap in the Stage 2 → Stage 3 handoff. The same funding opportunity is frequently announced on multiple domains simultaneously — for example, a call for proposals published on a regional agency's own website, mirrored on a partner foundation's grants page, and listed on an aggregator. Stage 2 operates per-domain and has no mechanism to detect that `{url_hash_A}.html` from cartafrica.org and `{url_hash_B}.html` from wellcome.org describe the same grant. Deduplication at the opportunity level requires semantic comparison across extracted records and is the responsibility of Stage 3 (or a post-extraction deduplication step between Stages 3 and 4). Stage 3 should be designed with this requirement in mind from the outset, as retrofitting cross-domain deduplication after Stage 4 is built is substantially more costly.
