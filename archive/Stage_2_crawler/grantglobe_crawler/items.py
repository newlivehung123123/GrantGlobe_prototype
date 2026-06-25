"""
Scrapy item definitions for GrantGlobe Stage 2 crawler.

GrantItem carries all data yielded by the spider for downstream processing.
Each instance represents one crawled resource — either an HTML page or a
PDF binary.  The item pipeline chain (Phase C) writes the resource to
``raw_cache/`` and emits the accompanying ``.meta.json`` sidecar.

Spec ref: §2.6 Content Storage Schema.
"""

import scrapy


class GrantItem(scrapy.Item):
    # ── URL identity ──────────────────────────────────────────────────────────
    url = scrapy.Field()
    """Original URL as crawled (before canonicalisation)."""

    canonical_url = scrapy.Field()
    """URL after applying all seven canonicalisation rules (spec §2.2)."""

    url_hash = scrapy.Field()
    """
    First 16 hex chars of SHA-256(canonical_url).
    Used as filename stem throughout raw_cache/.
    Spec ref: §2.6 Content deduplication — "truncated to 16 hex characters".
    """

    # ── Domain metadata ───────────────────────────────────────────────────────
    domain = scrapy.Field()
    """Registered domain (e.g. 'undp.org'), without subdomain or port."""

    profile = scrapy.Field()
    """
    Crawl profile: 'A' (simple HTML), 'B' (JS-heavy), 'C' (PDF-dominant),
    or 'D' (bot-protected).
    Spec ref: §2.1 Domain type classification.
    """

    # ── Traversal metadata ────────────────────────────────────────────────────
    depth = scrapy.Field()
    """Crawl depth at which this resource was fetched (0 = seed URL)."""

    source_url = scrapy.Field()
    """URL of the page that linked to this resource (None for seed URLs)."""

    # ── Response payload ──────────────────────────────────────────────────────
    html_content = scrapy.Field()
    """
    Raw response body as bytes.
    For HTML pages: rendered HTML (gzip-compressed by the pipeline).
    For PDFs: raw PDF binary (stored as {content_sha256}.pdf by the pipeline).
    """

    headers = scrapy.Field()
    """HTTP response headers as a plain dict (str → str)."""

    # ── Timing ────────────────────────────────────────────────────────────────
    crawl_timestamp = scrapy.Field()
    """ISO 8601 UTC timestamp of when the response was received."""

    # ── Classification flags ──────────────────────────────────────────────────
    is_pdf = scrapy.Field()
    """True when this item represents a downloaded PDF binary."""

    has_structured_data = scrapy.Field()
    """
    True when one or more valid JSON-LD/Schema.org blocks were found in the
    page and stored as {url_hash}.jsonld alongside the HTML.
    Spec ref: §2.2 JSON-LD and Schema.org structured data extraction.
    """

    # ── Structured data payload ───────────────────────────────────────────────
    jsonld_data = scrapy.Field()
    """
    List of deserialised JSON-LD objects extracted from the page (may be
    empty even when has_structured_data is True if none matched grant types).
    Stored by the spider directly to {raw_cache}/{domain}/{date}/pages/
    {url_hash}.jsonld.  Stage 3 reads this file before falling back to LLM
    extraction.
    Spec ref: §2.2 JSON-LD extraction — step (4).
    """

    # ── Page classification (set by pipeline, not spider) ────────────────────
    page_type = scrapy.Field()
    """
    Classification result: 'grant_listing', 'individual_opportunity',
    'eligibility_application', or 'irrelevant'.
    Set by the ContentStoragePipeline (Phase C); None until then.
    Spec ref: §2.2 Page type classification.
    """

    # ── HTTP response metadata ────────────────────────────────────────────────
    http_status = scrapy.Field()
    """HTTP response status code (int) — e.g. 200, 301, 404."""

    content_type = scrapy.Field()
    """
    Full Content-Type header value from the response, e.g.
    'text/html; charset=utf-8' or 'application/pdf'.
    Recorded in .meta.json; used by Stage 3 to distinguish HTML from PDF.
    """

    # ── Language detection (set by PDFExtractionPipeline) ────────────────────
    language = scrapy.Field()
    """
    ISO 639-1 language code detected from the page / PDF text.
    Set by PDFExtractionPipeline via lingua-language-detector.
    Stage 3 uses this to route non-English content to a translation step.
    Spec ref: §2.4 Step 6 — Language detection.
    """

    # ── Content deduplication (set by ContentStoragePipeline) ────────────────
    content_sha256 = scrapy.Field()
    """
    SHA-256 hex digest of item['html_content'] (the raw response body bytes).
    For PDFs, this becomes the filename stem: {content_sha256}.pdf.
    Set by PDFExtractionPipeline (priority 400) so ContentStoragePipeline
    (priority 500) can use it without recomputing.
    Spec ref: §2.4 Step 2 — content-hash filename; §2.6 Content deduplication.
    """

    # ── Change detection (set by ContentStoragePipeline) ─────────────────────
    changed = scrapy.Field()
    """
    True if the page content hash is absent from the previous cycle's
    seen_hashes.json (i.e. the content is new or changed).
    Set by ContentStoragePipeline when comparing against seen_hashes.json.
    Spec ref: §2.6 Change detection.
    """

    char_count = scrapy.Field()
    """
    Number of characters in the extracted text.
    Set by PDFExtractionPipeline for PDF items.
    For HTML items, set by ContentStoragePipeline in Phase D.
    """
