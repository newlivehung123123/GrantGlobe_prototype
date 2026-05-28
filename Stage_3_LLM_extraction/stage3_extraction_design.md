# GrantGlobe Stage 3 — LLM Extraction Pipeline
## Technical Design Document v1.5

---

## Table of Contents

1. Overview
2. Position in the Pipeline
3. Architecture
4. Database Schema
5. Extraction Pipeline
6. LLM Integration — Gemini 3.5 Flash
7. Normalisation Layer
8. Deduplication
9. Human Review Queue
10. Controlled Vocabularies
11. QA and Monitoring
12. Build Phases for Cursor
13. Dependencies and Configuration

---

## 1. Overview

Stage 3 is a standalone batch processing service that reads structured web content collected by Stage 2, extracts grant opportunity records using Gemini 3.5 Flash, normalises all extracted values against controlled vocabularies, deduplicates records using content hashing, and writes finalised grant records to a PostgreSQL database consumed by Stage 4 (the user-facing filterable interface).

Stage 3 operates entirely independently of the Scrapy crawler. It is triggered after each Stage 2 crawl cycle completes and processes only pages that Stage 2 flagged as new or changed, making each cycle computationally efficient. At the prototype scale of 582 domains it operates well within the Gemini Batch API's cost and latency envelope.

**Key design principles:**

- One page may produce zero, one, or many grant records. The extraction model always returns a list.
- No value is fabricated. When a field cannot be extracted with confidence, a structured sentinel is returned and rendered professionally at the interface layer.
- Every extracted value passes through a normalisation layer before reaching the database. The LLM extracts raw text; the normalisation layer maps it to standards.
- Status is only auto-computed when the deadline is extracted at High confidence. All other cases use a sentinel.
- Records with any core field at Low or Not Found confidence are routed to the human review queue before publication.

---

## 2. Position in the Pipeline

```
Stage 1 (Source Directory)
        ↓
Stage 2 (Web Crawler)
  → raw_cache/{domain}/{date}/pages/{url_hash}.html.gz
  → raw_cache/{domain}/{date}/pages/{url_hash}.meta.json
  → raw_cache/{domain}/{date}/pdfs/{content_sha256}.pdf
  → raw_cache/{domain}/crawl_manifest.json
        ↓
Stage 3 (LLM Extraction)   ← THIS DOCUMENT
  → PostgreSQL grants database
  → stage3_output/review_queue_{date}.csv (human review export)
  → stage3_output/extraction_report_{date}.json (QA metrics)
  → raw_cache/crawl_complete_{date}.json (written by Stage 2 — read by Stage 3)
        ↓
Stage 4 (Filterable Interface)
  → reads from PostgreSQL grants database
```

Stage 3 reads from `raw_cache` and writes to PostgreSQL. It has no runtime dependency on Stage 2 beyond the files Stage 2 produces. Stage 4 has no runtime dependency on Stage 3 beyond the PostgreSQL database Stage 3 populates.

---

## 3. Architecture

Stage 3 is a Python service with four internal components:

**3.1 Batch Processor**
Scans `raw_cache` for pages flagged as changed by Stage 2, batches them for LLM processing, and manages the extraction lifecycle. Checks the `extraction_log` table before processing any page to avoid double-processing.

**3.2 LLM Extractor**
Submits batches to the Gemini 3.5 Flash Batch API. Parses the JSON response list. Handles API errors, rate limits, and retries. Each page submission returns a list of zero or more grant objects in a strict JSON schema.

**3.3 Normalisation Layer**
Receives raw LLM output and applies all standardisation rules: country name to ISO 3166-1 alpha-2, date strings to ISO 8601, currency symbols to ISO 4217, free-text values to controlled vocabulary entries, funder names to canonical authority file entries. Computes the content hash for deduplication. Determines whether a record requires human review.

**3.4 Database Writer**
Attempts an upsert of each normalised grant record into PostgreSQL. On content hash conflict, replaces the existing record only if the incoming record has higher aggregate confidence scores. Updates the `extraction_log` table on completion.

Records with `requires_review = false` are inserted with `review_status = 'approved'` (not the column default `'pending'`). This means Stage 4 can use the unambiguous query `WHERE review_status = 'approved'` to retrieve all publication-ready records. Records with `requires_review = true` are inserted with `review_status = 'pending'` and remain pending until an operator approves or rejects them via the review workflow (§9).

**3.5 Concurrency safety**
The Batch Processor claims work using `SELECT ... FOR UPDATE SKIP LOCKED` when fetching pending rows from `extraction_log`. This ensures that if two Stage 3 workers run simultaneously (e.g. a manual run overlapping a scheduled run), each page is processed by exactly one worker.

Startup crash recovery resets stale `'processing'` rows to `'pending'`, but only those older than 8 hours:

```sql
UPDATE extraction_log
SET status = 'pending', error_message = 'reset from stale processing'
WHERE status = 'processing'
  AND processed_at < NOW() - INTERVAL '8 hours';
```

The 8-hour threshold ensures that a live worker's recently claimed rows are never stolen by a concurrent startup. A legitimate crash survivor will always be older than 8 hours by the time any restart occurs; an actively processed row will be recent.

**Service trigger:**
Stage 3 is triggered by the same APScheduler instance that manages Stage 2. Rather than relying on a fixed time offset (which fails when Stage 2 runs long due to network issues, rate limiting, or new domains), Stage 2 writes a sentinel file `raw_cache/crawl_complete_{YYYY-MM-DD}.json` as its final action after `spider_closed` completes. Stage 3's scheduler polls for this file before beginning processing. If the file is absent at trigger time, Stage 3 waits up to 4 hours in 15-minute polling intervals before aborting with a WARNING-level log. Manual runs bypass the sentinel check via a `--force` flag. Stage 3 can also be triggered manually via command line for ad-hoc processing.

**Technology stack:**
- Python 3.11+
- `google-generativeai` — Gemini 3.5 Flash API
- `psycopg2-binary` — PostgreSQL driver
- `alembic` — database migrations
- `beautifulsoup4` — HTML stripping
- `rapidfuzz` — fuzzy matching in normalisation layer
- `python-dotenv` — environment variable management
- `structlog` — structured logging

---

## 4. Database Schema

### 4.1 Main grants table

```sql
CREATE TABLE grants (
    -- Identity
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content_hash                CHAR(64) UNIQUE NOT NULL,
    -- content_hash = SHA-256(NFKC(lower(normalised_funder_name)) || '||' || NFKC(lower(normalised_grant_title)))
    -- Deadline is deliberately excluded: deadline extensions must update the existing record, not create a duplicate.

    -- Core descriptive fields
    grant_title                 TEXT NOT NULL,
    funder_name                 TEXT NOT NULL,
    funder_ror_id               TEXT,                        -- Research Organisation Registry ID if resolved
    source_url                  TEXT NOT NULL,               -- canonical URL of the source page
    application_portal_url      TEXT,
    description                 TEXT,                        -- brief plain-text summary extracted from source

    -- Deadlines (ISO 8601 dates or sentinel strings)
    application_deadline        DATE,
    application_deadline_raw    TEXT,                        -- original extracted string before normalisation
    application_deadline_type   TEXT,                        -- 'confirmed' | 'rolling' | 'tbc' | 'not_published' | 'unextracted'
    deadline_notes              TEXT,                        -- free-text deadline clarification (e.g. 'Letters of intent due 1 March')
    eoi_deadline                DATE,
    eoi_deadline_raw            TEXT,
    eoi_deadline_type           TEXT,                        -- same controlled values as application_deadline_type

    -- Grant opening / announcement date (used for Upcoming status computation)
    grant_opening_date          DATE,
    grant_opening_date_raw      TEXT,                        -- original extracted string before normalisation

    -- Funding amount
    funding_amount_min          NUMERIC(15,2),
    funding_amount_max          NUMERIC(15,2),
    currency                    CHAR(3),                     -- ISO 4217
    funding_amount_type         TEXT,                        -- 'confirmed' | 'not_published' | 'unextracted'

    -- Status
    current_status              TEXT,                        -- controlled vocabulary (§10.6)
    status_source               TEXT,                        -- 'extracted' | 'computed' | 'sentinel'

    -- Language
    source_language             CHAR(10),                    -- ISO 639-1 (e.g. 'en', 'fr', 'zh-hans')

    -- AI focus flag (confidence stored in confidence_scores JSONB — no separate column)
    ai_focused                  BOOLEAN,

    -- Eligibility — organisations
    individuals_not_eligible    BOOLEAN NOT NULL DEFAULT false,
    organisation_types          TEXT[],                      -- controlled vocabulary array (§10.3)
    individual_eligibility      TEXT[],                      -- controlled vocabulary array (§10.4)

    -- Geographic scope — applicant base
    applicant_base_regions      TEXT[],                      -- UN M.49 controlled vocabulary (§10.1)
    applicant_base_countries    CHAR(2)[],                   -- ISO 3166-1 alpha-2 (§10.2)

    -- Geographic scope — funded work
    geographic_focus_regions    TEXT[],                      -- UN M.49 controlled vocabulary (§10.1)
    geographic_focus_countries  CHAR(2)[],                   -- ISO 3166-1 alpha-2 (§10.2)

    -- Thematic classification
    thematic_sectors            TEXT[],                      -- controlled vocabulary (§10.5)
    grant_types                 TEXT[],                      -- controlled vocabulary (§10.7)

    -- Confidence scores (per field)
    confidence_scores           JSONB NOT NULL DEFAULT '{}',
    -- Example: {"grant_title": "high", "funder_name": "high", "application_deadline": "medium",
    --           "funding_amount": "low", "geographic_focus": "high", "thematic_sectors": "medium"}
    aggregate_confidence_score  INTEGER NOT NULL DEFAULT 0,
    -- Pre-computed integer sum: high=3, medium=2, low=1, not_found=0. Used in upsert conflict
    -- resolution (§8) to avoid JSONB traversal at write time.

    -- Raw extraction (LLM output before normalisation — for audit and review)
    raw_extraction              JSONB NOT NULL DEFAULT '{}',

    -- Review workflow
    requires_review             BOOLEAN NOT NULL DEFAULT false,
    review_status               TEXT NOT NULL DEFAULT 'pending',
    -- 'pending' | 'approved' | 'rejected'

    -- Provenance
    domain                      TEXT NOT NULL,
    crawl_date                  DATE NOT NULL,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 4.2 Indexes

```sql
-- Deduplication and lookup
CREATE UNIQUE INDEX idx_grants_content_hash ON grants (content_hash);

-- Filtering indexes (GIN for array containment queries)
CREATE INDEX idx_grants_geographic_focus_regions   ON grants USING GIN (geographic_focus_regions);
CREATE INDEX idx_grants_geographic_focus_countries ON grants USING GIN (geographic_focus_countries);
CREATE INDEX idx_grants_applicant_base_regions     ON grants USING GIN (applicant_base_regions);
CREATE INDEX idx_grants_applicant_base_countries   ON grants USING GIN (applicant_base_countries);
CREATE INDEX idx_grants_organisation_types         ON grants USING GIN (organisation_types);
CREATE INDEX idx_grants_individual_eligibility     ON grants USING GIN (individual_eligibility);
CREATE INDEX idx_grants_thematic_sectors           ON grants USING GIN (thematic_sectors);
CREATE INDEX idx_grants_grant_types                ON grants USING GIN (grant_types);

-- Status and date filtering
CREATE INDEX idx_grants_current_status             ON grants (current_status);
CREATE INDEX idx_grants_application_deadline       ON grants (application_deadline);
CREATE INDEX idx_grants_ai_focused                 ON grants (ai_focused);
-- Full index on review_status for Stage 4 reader query (WHERE review_status = 'approved').
-- Most approved records have requires_review = false and would be invisible to the partial
-- index below; without this full index, Stage 4 does a sequential scan on every page load.
CREATE INDEX idx_grants_review_status              ON grants (review_status);
-- Partial index retained for review queue export query (WHERE requires_review = true).
CREATE INDEX idx_grants_review_queue               ON grants (review_status, created_at DESC) WHERE requires_review = true;
-- Composite index covering the likely Stage 4 combined filter pattern.
CREATE INDEX idx_grants_stage4_filter              ON grants (review_status, current_status, application_deadline);
CREATE INDEX idx_grants_domain                     ON grants (domain);
```

### 4.3 Extraction log table

```sql
CREATE TABLE extraction_log (
    id              SERIAL PRIMARY KEY,
    url_hash        CHAR(16) NOT NULL,           -- from Stage 2 .meta.json
    domain          TEXT NOT NULL,
    crawl_date      DATE NOT NULL,
    processed_at    TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'pending',
    -- 'pending' | 'processing' | 'completed' | 'failed' | 'skipped'
    records_extracted   INTEGER DEFAULT 0,
    error_message   TEXT,
    retry_count     INTEGER DEFAULT 0,
    UNIQUE (url_hash, crawl_date)
);

CREATE INDEX idx_extraction_log_status ON extraction_log (status);
CREATE INDEX idx_extraction_log_domain ON extraction_log (domain, crawl_date);
```

---

## 5. Extraction Pipeline

### 5.1 Step-by-step flow

```
0. STARTUP RECOVERY
   On every startup, before scanning:
     UPDATE extraction_log SET status = 'pending', error_message = 'reset from stale processing'
     WHERE status = 'processing'
       AND processed_at < NOW() - INTERVAL '8 hours';
   This corrects rows left in 'processing' state by a previous crashed run. The 8-hour
   threshold prevents a concurrent live worker's rows from being stolen (see §3.5).

1. SCAN
   Read raw_cache/{domain}/ for all crawl cycle dates.
   For each .meta.json where changed == true:
     - Claim rows using SELECT ... FOR UPDATE SKIP LOCKED (see §3.5).
     - Check extraction_log: if status == 'completed', skip.
     - Add to processing queue.

2. PREPARE
   For each queued page:
     - If is_pdf == false: decompress .html.gz, strip HTML tags via BeautifulSoup.
       Use google-generativeai count_tokens() to measure length; truncate to
       6,000 tokens maximum (preserving full sentences).
     - If is_pdf == true: read extracted text from .meta.json pdf_text field
       (populated by Stage 2 PDFExtractionPipeline); truncate to 12,000 tokens.
     - MINIMUM LENGTH CHECK: if stripped content is fewer than 50 tokens, mark
       extraction_log status as 'skipped' with reason 'content_too_short'. Do not
       submit to the LLM. This prevents wasting API calls on navigation-only pages.
     - Construct the per-page prompt (system prompt + page text).

3. BATCH
   Group pages into Gemini Batch API batches (max 2,000 requests per batch).
   Submit batch. Poll for completion (Gemini Batch API is asynchronous).
   Polling schedule: every 5 minutes for the first hour; every 15 minutes thereafter.
   Maximum polling duration: 6 hours per batch. If a batch has not completed after
   6 hours, mark all affected pages as 'failed' and log a CRITICAL-level alert.

4. PARSE
   For each batch result:
     - Parse the JSON list response.
     - Validate top-level structure (must be a list, even if empty).
     - Pass each grant object to the normalisation layer (§6).

5. NORMALISE
   For each raw grant object:
     - Apply all normalisation rules (§6).
     - Compute content hash (§7).
     - Determine requires_review flag (§5.2).

6. WRITE
   For each normalised grant record:
     - Set review_status = 'approved' if requires_review == false; 'pending' otherwise.
     - Attempt INSERT with ON CONFLICT (content_hash) DO UPDATE
       (update only if incoming aggregate confidence > existing aggregate confidence).
     - On conflict update: preserve existing review_status if it is 'approved' or 'rejected'
       — a higher-confidence re-extraction must not overwrite an operator's decision (§8).
     - Update extraction_log status to 'completed'.

7. EXPORT REVIEW QUEUE
   After all batches complete:
     - SELECT * FROM grants WHERE requires_review = true AND review_status = 'pending'
     - Export to stage3_output/review_queue_{date}.csv.

8. WRITE QA REPORT
   Write stage3_output/extraction_report_{date}.json with metrics (§11).
```

### 5.2 Review flag rules

The `STAGE3_REVIEW_CONFIDENCE_THRESHOLD` environment variable controls which confidence levels trigger the review flag. It has two accepted values:

- `low` (default): a record requires review when a core field is at **Low or Not Found** confidence.
- `medium`: a record requires review when a core field is at **Medium, Low, or Not Found** confidence. This produces a larger review queue and is intended for quality-auditing runs rather than routine processing.

At the `low` threshold (default), a record is flagged `requires_review = true` if ANY of the following apply:

| Rule | Condition |
|---|---|
| R1 | `grant_title` confidence is Low or Not Found |
| R2 | `funder_name` confidence is Low or Not Found |
| R3 | `application_deadline` confidence is Low and `application_deadline_type` is not 'rolling', 'tbc', or 'not_published' |
| R4 | `current_status` is 'Others' |
| R5 | Any array field (thematic_sectors, geographic_focus, individual_eligibility) contains 'Others' |
| R6 | `ai_focused` confidence is Low or Not Found (Medium is a soft flag only — does not trigger review) |
| R7 | `individuals_not_eligible` is null (could not be determined) |

At the `medium` threshold, rules R1, R2, and R3 additionally fire when confidence is Medium (not just Low/Not Found). Rules R4–R7 are unchanged — they are structural conditions, not confidence levels.

### 5.3 Token budget

| Content type | Max input tokens | Rationale |
|---|---|---|
| HTML page (stripped) | 6,000 | Covers most grant pages with headings, body, and eligibility text |
| PDF (extracted text) | 12,000 | Covers multi-page grant call documents |
| System prompt + schema | ~1,200 | Fixed overhead per request |
| Output (JSON list) | ~800 per grant found | Estimated per grant object |

Token counting uses `google-generativeai`'s `count_tokens()` method against the target model. This is preferred over character-based heuristics because it reflects the model's actual tokenisation and avoids both truncating valid content and submitting overlength requests.

At $1.50/M input and $9.00/M output (Gemini 3.5 Flash), the blended cost per page is approximately $0.01 using the Batch API (50% discount applied).

---

## 6. LLM Integration — Gemini 3.5 Flash

### 6.1 Model and API

Model: `gemini-3.5-flash` via Google AI Generative API.
Mode: Batch API for all production processing (50% cost reduction, no real-time latency requirement).
Response format: JSON with a strict response schema enforced via Gemini's `response_mime_type: "application/json"` and `response_schema` parameters.

**Note on model string**: Gemini 3.5 Flash was released at Google I/O on 19 May 2026. The exact API model string (`gemini-3.5-flash` or a versioned alias such as `gemini-3.5-flash-001`) must be confirmed against the Google AI documentation at the time of Phase B build. The `extractor.py` module must expose the model string as a configurable constant so it can be updated without code changes if Google revises the identifier.

### 6.2 System prompt

```
You are a grant opportunity extraction specialist. Your task is to read the text of a web page or document and extract ALL grant, fellowship, scholarship, or funding opportunities described on that page.

CRITICAL RULES — read carefully before extracting:

1. Return a JSON list. If there are no grant opportunities on the page, return an empty list [].
   If there are multiple opportunities on the same page, return one object per opportunity.

2. Never fabricate values. If a field's value is not clearly stated in the source text,
   return null for that field. Do not guess, infer, or construct plausible values.

3. Return exactly what the source text says for all raw text fields.
   The normalisation system will standardise values — your job is accurate extraction only.

4. Assign a confidence score to every field:
   - "high": value is explicitly and unambiguously stated in the source text
   - "medium": value is implied or partially stated — likely correct but not certain
   - "low": value is uncertain, inferred from indirect or ambiguous language
   - "not_found": field is not present or cannot be identified in the source text

5. For individual_eligibility: if the source text says "early career researcher" without
   specifying whether current PhD students are included, assign "Early Career Researcher"
   with confidence "medium" and include a note in the raw_notes field.
   If PhD students are explicitly included, assign BOTH "Student — Postgraduate / PhD"
   AND "Early Career Researcher (includes PhD candidates)".

6. For ai_focused: assign true only when AI, machine learning, deep learning, large language
   models, generative AI, neural networks, NLP, computer vision, AI governance, AI ethics,
   or AI safety is a substantive focus of the grant — not merely mentioned in passing.

7. For current_status: extract only what the source explicitly states.
   Do NOT compute or infer status from the deadline date — the system handles this separately.

8. For geographic fields: extract country and region names exactly as written.
   Do not convert to codes — the normalisation system handles standardisation.

9. For funding amounts: extract numeric values only. Convert abbreviations:
   "£50k" → 50000, "$2.5 million" → 2500000. If a range is stated, populate both min and max.

10. For description: write a plain-text summary of 2–3 sentences maximum. Capture the core
    purpose of the grant and who it is for. Do not copy the full page text. Return null if
    there is insufficient content to produce a meaningful summary.

11. For grant_opening_date: extract the date when the grant round opens or applications begin
    to be accepted, if explicitly stated. This is distinct from the application deadline.
    Return null if not stated. Return the raw date string exactly as written.

12. For non-English source documents: extract field values in the source language exactly as
    written. Do not translate. Controlled-vocabulary matching is English-only in this
    prototype — non-English values will be preserved in the raw data and flagged for review.
    For free-text fields (grant_title, funder_name, description), preserve the original
    language text. Set source_language_raw to the language you detect.
```

### 6.3 Response schema

The Gemini response schema enforces the following structure:

```json
{
  "type": "array",
  "items": {
    "type": "object",
    "properties": {
      "grant_title":              {"type": ["string", "null"]},
      "funder_name":              {"type": ["string", "null"]},
      "description":              {"type": ["string", "null"]},
      "application_deadline_raw": {"type": ["string", "null"]},
      "deadline_notes":           {"type": ["string", "null"]},
      "eoi_deadline_raw":         {"type": ["string", "null"]},
      "grant_opening_date_raw":   {"type": ["string", "null"]},
      "funding_amount_min":       {"type": ["number", "null"]},
      "funding_amount_max":       {"type": ["number", "null"]},
      "currency_raw":             {"type": ["string", "null"]},
      "current_status_raw":       {"type": ["string", "null"]},
      "application_portal_url":   {"type": ["string", "null"]},
      "source_language_raw":      {"type": ["string", "null"]},
      "ai_focused":               {"type": ["boolean", "null"]},
      "individuals_not_eligible": {"type": ["boolean", "null"]},
      "organisation_types_raw":   {"type": "array", "items": {"type": "string"}},
      "individual_eligibility_raw": {"type": "array", "items": {"type": "string"}},
      "applicant_base_raw":       {"type": "array", "items": {"type": "string"}},
      "geographic_focus_raw":     {"type": "array", "items": {"type": "string"}},
      "thematic_sectors_raw":     {"type": "array", "items": {"type": "string"}},
      "grant_types_raw":          {"type": "array", "items": {"type": "string"}},
      "confidence_scores": {
        "type": "object",
        "properties": {
          "grant_title":              {"type": "string", "enum": ["high","medium","low","not_found"]},
          "funder_name":              {"type": "string", "enum": ["high","medium","low","not_found"]},
          "application_deadline":     {"type": "string", "enum": ["high","medium","low","not_found"]},
          "eoi_deadline":             {"type": "string", "enum": ["high","medium","low","not_found"]},
          "grant_opening_date":       {"type": "string", "enum": ["high","medium","low","not_found"]},
          "funding_amount":           {"type": "string", "enum": ["high","medium","low","not_found"]},
          "current_status":           {"type": "string", "enum": ["high","medium","low","not_found"]},
          "geographic_focus":         {"type": "string", "enum": ["high","medium","low","not_found"]},
          "thematic_sectors":         {"type": "string", "enum": ["high","medium","low","not_found"]},
          "individual_eligibility":   {"type": "string", "enum": ["high","medium","low","not_found"]},
          "organisation_types":       {"type": "string", "enum": ["high","medium","low","not_found"]},
          "applicant_base":           {"type": "string", "enum": ["high","medium","low","not_found"]},
          "ai_focused":               {"type": "string", "enum": ["high","medium","low","not_found"]}
        }
      },
      "raw_notes": {"type": ["string", "null"]}
    }
  }
}
```

### 6.4 Error handling

| Error condition | Behaviour |
|---|---|
| API timeout | Retry up to 3 times with exponential backoff (30s, 60s, 120s) |
| Invalid JSON response | Log error, mark extraction_log status as 'failed', skip record |
| Empty list response | Valid — mark extraction_log as 'completed', records_extracted = 0 |
| Rate limit (429) | Pause batch submission, resume after 60 seconds |
| Batch API job failure (complete) | Re-submit all affected pages as a new batch |
| Batch API partial failure (mixed results) | Parse all successful results normally; identify failed request IDs from the batch output metadata; mark corresponding extraction_log rows as 'failed' with the reported error message; re-submit failed pages as a new batch on the next retry cycle |

---

## 7. Normalisation Layer

The normalisation layer receives raw LLM output and applies all standardisation rules before the record reaches the database. It operates as a pure Python module with no external API calls — all lookups use the JSON files described below.

### 7.1 Lookup files (flat JSON, shipped with codebase)

| File | Purpose |
|---|---|
| `data/country_lookup.json` | Maps country name variants → ISO 3166-1 alpha-2 |
| `data/funder_authority.json` | Maps funder name variants → canonical name + ROR ID |
| `data/currency_lookup.json` | Maps currency symbols/names → ISO 4217 code |
| `data/supranational_groups.json` | Maps group names (EU, OECD, LMIC) → constituent ISO alpha-2 codes |
| `data/region_lookup.json` | Maps region name variants → UN M.49 canonical label |

### 7.2 Normalisation rules per field

**Grant title**: Title case. Strip leading/trailing whitespace. Strip terminal punctuation unless `?` or `!`.

**Funder name**: Look up in `funder_authority.json` using exact match first, then rapidfuzz fuzzy match at similarity threshold ≥ 90. If matched, use canonical name and populate `funder_ror_id`. If unmatched, store as extracted and flag for authority file review.

**Deadlines**: Parse date string to ISO 8601 `YYYY-MM-DD` using a multi-format parser covering all common English date formats. Set `application_deadline_type`:
- `rolling` if source text contains "rolling", "open continuously", "no deadline"
- `tbc` if source text contains "TBC", "to be confirmed", "coming soon"
- `not_published` if field is null and confidence is `not_found`
- `unextracted` if field is null and confidence is `low` or `medium`
- `confirmed` if a date was successfully parsed

`eoi_deadline_type` follows the identical set of controlled values and the same normalisation rules as `application_deadline_type`.

**Grant opening date**: Parse `grant_opening_date_raw` to ISO 8601 `YYYY-MM-DD` using the same multi-format parser as deadlines. Store in `grant_opening_date`. If null or unextracted, leave as null — there is no type column for this field. Used exclusively for Upcoming status auto-computation (rule 3 below) and the daily status refresh job.

**Status auto-computation rules** (applied in strict priority order; all date comparisons use UTC):

1. If status_raw is explicitly stated AND confidence is `high` → map to controlled vocabulary, `status_source = 'extracted'`
2. If `application_deadline_type == 'rolling'` AND status_raw is null → set `current_status = 'Rolling'`, `status_source = 'computed'`
3. If `grant_opening_date` is present AND confidence on `grant_opening_date` is `high` AND `grant_opening_date > today (UTC)` AND status_raw is null → set `current_status = 'Upcoming'`, `status_source = 'computed'`
   — **This rule must precede the Open/Closed check.** A grant that has not yet opened cannot be Open or Closed regardless of its deadline value.
4. If `application_deadline_type == 'confirmed'` AND confidence on `application_deadline` is `high`:
   - AND `application_deadline < today (UTC)` AND status_raw is null → set `current_status = 'Closed'`, `status_source = 'computed'`
   - AND `application_deadline >= today (UTC)` AND status_raw is null → set `current_status = 'Open'`, `status_source = 'computed'`
5. All other cases (deadline type is not `confirmed`, confidence is not `high`, or status is ambiguous) → set `current_status` to sentinel, `status_source = 'sentinel'`

Status computed at insertion time becomes stale as time passes. This is resolved by a daily recalculation job (§11) that re-evaluates these rules for all records where `status_source = 'computed'`.

All comparisons against "today" use UTC — `datetime.now(timezone.utc).date()` in Python (from `datetime import datetime, timezone`). `datetime.utcnow()` is deprecated since Python 3.12 and must not be used. The same UTC convention applies in `status_refresh.py` and in any Stage 4 query-time status computation.

Display sentinel renders as: "Check on the funder's site" with hyperlink to `source_url`.

**Currency**: Look up symbol or name in `currency_lookup.json`. Store ISO 4217 code. If unrecognised, store `OTH` and preserve raw string in `raw_extraction`.

**Countries**: For each raw country/territory string in geographic arrays:
1. Exact match in `country_lookup.json`
2. Fuzzy match via rapidfuzz at threshold ≥ 88
3. If matched: store ISO 3166-1 alpha-2 code
4. If unmatched: store `OT` (Others) and log raw string for lookup table review

**Supranational groups**: If geographic_focus_raw contains a group name (e.g. "EU member states"), expand to constituent country codes using `supranational_groups.json`. Store the group label at the region level and the expanded codes at the country level.

**Regions**: Map raw region strings to UN M.49 canonical labels via `region_lookup.json`. Unmatched → `Others`.

**Controlled vocabulary fields** (organisation_types, individual_eligibility, thematic_sectors, grant_types): For each raw string, attempt exact match against the controlled vocabulary list (case-insensitive). Unmatched → `Others`. Raw string preserved in `raw_extraction`.

**Prototype limitation — non-English controlled vocabulary matching**: The controlled vocabulary lists are English-only. For non-English source documents, the LLM correctly extracts values in the source language (system prompt rule 12), but the normalisation layer cannot match them to controlled vocabulary entries — they will fall through to `Others`. This silently inflates the `Others` bucket for any non-English source. This is an acceptable limitation at prototype scale, where the majority of sources are English-language. A post-prototype fix would add multilingual synonym lists to the controlled vocabulary lookup files (e.g. mapping "organisation non gouvernementale" → "Non-Governmental Organisation (NGO)"). The `fields_others_frequency` QA metric (§11) will surface this pattern when it occurs.

**Source language**: Map raw language name or code to ISO 639-1 two-letter code. `zh-hans` for Simplified Chinese, `zh-hant` for Traditional Chinese where determinable.

### 7.3 Content hash computation

```python
import hashlib
import unicodedata

def compute_content_hash(funder_name: str, grant_title: str) -> str:
    """
    Compute SHA-256 deduplication hash from normalised funder name and grant title.

    Deadline is deliberately excluded: when a funder extends a deadline, the record
    must be updated in place, not duplicated. Including the deadline would create a
    new hash for every deadline extension, accumulating redundant records.

    NFKC unicode normalisation is applied before lowercasing to ensure that visually
    identical strings using different Unicode representations (e.g. ligatures, full-
    width characters, different spacing characters) produce the same hash.

    Known limitation: if the same funder publishes two distinct grant opportunities
    with identical titles (e.g. "Innovation Fund" as both a Research Grant and a
    Fellowship in the same cycle), they will share a hash and the lower-confidence
    record will be silently discarded. This case is rare in practice. It will surface
    as a `records_duplicate_lower_confidence` increment in the QA report (§11),
    allowing an operator to investigate if the count is unexpectedly high.
    """
    def normalise(s: str) -> str:
        return unicodedata.normalize("NFKC", s).lower().strip()

    combined = normalise(funder_name) + "||" + normalise(grant_title)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()
```

---

## 8. Deduplication

On INSERT, PostgreSQL's `ON CONFLICT (content_hash) DO UPDATE` handles duplicates. The update proceeds only if the incoming record has a higher aggregate confidence score than the existing record.

**Aggregate confidence score** is computed entirely in Python before the SQL is constructed:
- `high` = 3, `medium` = 2, `low` = 1, `not_found` = 0
- Sum across all scored fields in `confidence_scores` (§6.3)
- Maximum possible score increases with the number of scored fields

```python
_CONFIDENCE_INT = {"high": 3, "medium": 2, "low": 1, "not_found": 0}

def aggregate_confidence_score(confidence_scores: dict) -> int:
    """Sum integer values across all confidence score fields."""
    return sum(_CONFIDENCE_INT.get(v, 0) for v in confidence_scores.values())
```

The pre-computed integer is passed as a parameter to the SQL, avoiding any attempt to interpret the string labels `'high'`, `'medium'`, `'low'`, `'not_found'` inside the database query:

```sql
INSERT INTO grants (..., confidence_scores, aggregate_confidence_score, review_status, ...)
VALUES (..., %(confidence_scores)s, %(incoming_score)s, %(review_status)s, ...)
ON CONFLICT (content_hash) DO UPDATE SET
    source_url                  = EXCLUDED.source_url,
    grant_title                 = EXCLUDED.grant_title,
    -- ... all content fields ...
    aggregate_confidence_score  = EXCLUDED.aggregate_confidence_score,
    -- Preserve operator review decisions, but only when the new extraction does not itself
    -- raise a review flag. If the incoming record sets requires_review = true (e.g. a field
    -- has dropped to low confidence in the new extraction), the record is sent back to
    -- 'pending' regardless of its prior operator decision — the quality concern must be
    -- re-evaluated. When requires_review = false on the incoming record, any prior approval
    -- or rejection is preserved intact.
    review_status = CASE
        WHEN grants.review_status IN ('approved', 'rejected')
             AND EXCLUDED.requires_review = false THEN grants.review_status
        ELSE EXCLUDED.review_status
    END,
    updated_at                  = NOW()
WHERE EXCLUDED.aggregate_confidence_score > grants.aggregate_confidence_score;
```

`aggregate_confidence_score INTEGER NOT NULL DEFAULT 0` is added as a column on the `grants` table so PostgreSQL can compare the two integers directly in the `WHERE` clause without any JSONB traversal at upsert time.

---

## 9. Human Review Queue

After each extraction cycle, records flagged `requires_review = true` and `review_status = 'pending'` are exported to a CSV file.

**Export query:**
```sql
SELECT
    id, content_hash, grant_title, funder_name, source_url,
    application_deadline, application_deadline_type,
    current_status, status_source,
    geographic_focus_regions, geographic_focus_countries,
    thematic_sectors, individual_eligibility,
    ai_focused,
    confidence_scores, raw_extraction,
    created_at
FROM grants
WHERE requires_review = true
  AND review_status = 'pending'
ORDER BY created_at DESC;
```

**Export file**: `stage3_output/review_queue_{YYYY-MM-DD}.csv`

Stage 3 output files are written to `stage3_output/` rather than `raw_cache/` to keep Stage 2 crawler inputs and Stage 3 artefacts in separate directories. This prevents any future Stage 2 re-scan logic from treating review CSVs or extraction reports as crawl cache content.

**Operator workflow**:
1. Open CSV in spreadsheet application
2. Review each record against the source URL (linked in the `source_url` column)
3. Set `review_status` column to `approved` or `rejected`
4. Run the import script: `python -m stage3.review_import review_queue_{date}.csv`
5. Import script updates `review_status` in PostgreSQL and sets `updated_at`

Rejected records are retained in the database with `review_status = 'rejected'` and excluded from Stage 4 queries. They are never deleted — this preserves an audit trail and allows re-review if the extraction prompt is later improved.

---

## 10. Controlled Vocabularies

### 10.1 Geographic Regions (UN M.49 based)

Global, Sub-Saharan Africa, East Africa, West Africa, Central Africa, Southern Africa, North Africa, Middle East and North Africa (MENA), South Asia, East Asia, South-East Asia, Central Asia, Western Europe, Eastern Europe, Northern Europe, Southern Europe, North America, Latin America and the Caribbean, Central America, South America, Caribbean, Oceania / Pacific, Others

### 10.2 Countries / Territories

ISO 3166-1 alpha-2 codes. Supplemented by: XK (Kosovo), plus all standard assigned codes including TW (Taiwan), PS (Palestine), HK (Hong Kong), MO (Macao). Full lookup table in `data/country_lookup.json`.

Supranational classifications stored as region-level labels and expanded to ISO codes at query time: Global (no restriction), LMIC, LDC, OECD Member States, Commonwealth Member States, EU Member States, African Union Member States, ASEAN Member States, Others.

### 10.3 Organisation Types (multi-value array)

University / Higher Education Institution, Research Institution / Think Tank, Non-Governmental Organisation (NGO), Civil Society Organisation (CSO), Community Organisation / Grassroots Group, Government / Public Authority, Intergovernmental Organisation, Private Sector / For-Profit Company, Social Enterprise, Foundation / Philanthropic Organisation, Hospital / Healthcare Institution, Media Organisation, Faith-Based Organisation, Consortium / Partnership, Others

### 10.4 Individual Eligibility (multi-value array)

Student — Undergraduate, Student — Postgraduate / PhD, Early Career Researcher, Early Career Researcher (includes PhD candidates), Mid-Career Professional / Researcher, Senior / Established Researcher or Professional, Professional / Practitioner, Entrepreneur, Developer / Programmer, Independent Scholar, Artist / Creative, Journalist, Activist / Community Leader, Any Individual (no career stage or profession restriction), Others

Separate boolean field: `individuals_not_eligible` — true when organisations only, false otherwise. When true, individual_eligibility array is null.

### 10.5 Thematic Sectors (multi-value array)

Agriculture and Food Security, Arts, Culture and Heritage, Biodiversity and Conservation, Climate Change and Environment, Democracy, Governance and Accountability, Digital Technology and Innovation, Disaster Risk Reduction and Humanitarian Response, Economic Development and Livelihoods, Education and Training, Energy and Clean Technology, Gender Equality and Women's Empowerment, Health and Medical Research, Human Rights and Social Justice, Infrastructure and Urban Development, Media and Journalism, Mental Health and Wellbeing, Migration, Displacement and Refugees, Peace and Security, Poverty Reduction and Social Protection, Science, Technology, Engineering and Mathematics (STEM), Water, Sanitation and Hygiene (WASH), Youth and Children, Others

### 10.6 Current Status (single value)

Open, Closed, Upcoming, Rolling, Suspended, Others

Sentinel display value (rendered at interface layer, not stored): "Check on the funder's site"

### 10.7 Grant Types (multi-value array)

Project Grant, Research Grant, Fellowship, Scholarship, Seed / Pilot Grant, Capacity Building Grant, Travel / Conference Grant, Emergency / Rapid Response Grant, Prize / Award, Core / Institutional Support, Technical Assistance, In-Kind Support, Loan / Repayable Finance, Others

### 10.8 AI-Focused (boolean field, separate from thematic sectors)

True, False, null (unextracted — sentinel displayed at interface)

### 10.9 Confidence Scores (per field)

high, medium, low, not_found

Sentinel display mappings at interface layer:
- `not_found` + funder says nothing about the field → "Not publicly specified"
- `not_found` + extraction could not identify the field → "Check on the funder's site"
- `low` → "Details not confirmed — verify on funder's site"

### 10.10 Currency

ISO 4217 three-letter codes. Primary values: USD, EUR, GBP, CAD, AUD, CHF, SEK, NOK, DKK, JPY, CNY, KRW, SGD, HKD, NZD, ZAR, INR, BRL, MXN, NGN, KES, GHS, TZS, UGX, ETB, XOF, XAF. Unrecognised currencies: `OTH` with raw string preserved.

### 10.11 Source Language

ISO 639-1 two-letter codes: en, fr, es, ar, pt, zh-hans, zh-hant, ja, ko, de, nl, ru, it, sv, no, da. Unrecognised: `ot` with detected language name preserved.

---

## 11. QA and Monitoring

After each extraction cycle, Stage 3 writes `stage3_output/extraction_report_{YYYY-MM-DD}.json` containing:

```json
{
  "report_date": "YYYY-MM-DD",
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
  "extraction_cost_estimate_usd": 0.0
}
```

**Alert conditions** (logged at WARNING level):
- `pages_failed` > 5% of `pages_processed`
- Any domain in `domains_zero_extraction` for two consecutive cycles
- `fields_others_frequency` for any field exceeds 15% — indicates a new value type appearing frequently enough to be promoted into the controlled vocabulary

**Daily status recalculation job**: A separate lightweight job (`status_refresh.py`) runs daily and re-evaluates two transitions for all records where `status_source = 'computed'`. Both `application_deadline` and `grant_opening_date` are `DATE` columns, which are timezone-independent in PostgreSQL; comparisons use plain `CURRENT_DATE` (which the server computes correctly regardless of its local timezone when the job is triggered from a UTC-configured scheduler). The UTC constraint is enforced at the Python layer via `datetime.now(timezone.utc).date()` when constructing the query parameter in Python code.

The transitions must run in the following order within each job execution:

1. **Upcoming → Open** (runs first): set `current_status = 'Open'` where `grant_opening_date <= CURRENT_DATE` AND `current_status = 'Upcoming'`.
2. **Open → Closed** (runs second): set `current_status = 'Closed'` where `application_deadline < CURRENT_DATE` AND `current_status = 'Open'`.

This ordering is critical. If a grant's opening date and deadline have both passed by the time the job runs (e.g. the site was not crawled while the grant was live), running Upcoming→Open first followed by Open→Closed will correctly set the final status to `'Closed'` in a single job execution. Reversing the order would leave such a record permanently `'Open'`.

Both transitions update `updated_at`. Records where `status_source = 'extracted'` or `'sentinel'` are not touched by this job. The job is added to APScheduler in Phase D.

---

## 12. Build Phases for Cursor

Stage 3 is built in five sequential phases. Each phase produces working, tested code before the next phase begins.

### Phase 0 — Lookup Data File Preparation

This phase has no code deliverables. It must be completed before Phase A begins, because Phase C depends on these files being populated.

Deliverables:
- `data/country_lookup.json`: comprehensive mapping of country name variants (including historical names, local-language names, and common misspellings) to ISO 3166-1 alpha-2 codes. Include XK (Kosovo), TW (Taiwan), PS (Palestine), HK (Hong Kong), MO (Macao).
- `data/region_lookup.json`: mapping of region name variants to UN M.49 canonical labels (§10.1).
- `data/currency_lookup.json`: mapping of currency symbols and names to ISO 4217 codes (§10.10).
- `data/supranational_groups.json`: mapping of group names (EU, OECD, LMIC, LDC, Commonwealth, African Union, ASEAN) to lists of constituent ISO alpha-2 codes.
- `data/funder_authority.json`: **stub file only at prototype stage** — a small manually populated list of the highest-frequency funders from the Stage 1 source directory (e.g. Wellcome Trust, Bill and Melinda Gates Foundation, European Research Council, UKRI). This file will be expanded incrementally as the system is used; an unmatched funder is stored as extracted and logged for review, not rejected.

Scoping note: populating `funder_authority.json` comprehensively for all 582 domains is out of scope for the prototype. The stub file prevents failures; full population is a post-prototype operational task.

Acceptance criteria: all five JSON files are present and parseable. `country_lookup.json` and `region_lookup.json` cover at least 90% of country and region names likely to appear in grant documents from the Stage 1 source set.

### Phase A — Database and Batch Processor Scaffold

Deliverables:
- Alembic migration creating `grants` and `extraction_log` tables with all indexes
- `raw_cache` reader that scans for `.meta.json` files where `changed: true`
- `extraction_log` manager: check processed, mark processing, mark completed/failed
- HTML stripper using BeautifulSoup (decompress `.html.gz`, strip tags, truncate to token budget)
- PDF text reader from `.meta.json` `pdf_text` field
- Project structure: `stage3/batch_processor.py`, `stage3/db.py`, `stage3/models.py`
- Unit tests for the raw_cache reader and HTML stripper

Acceptance criteria: Running the batch processor against a sample `raw_cache` directory correctly identifies changed pages, strips their content, and logs them as `pending` in `extraction_log`. No LLM calls yet.

### Phase B — LLM Extractor

Deliverables:
- `stage3/extractor.py`: Gemini 3.5 Flash Batch API client
- System prompt as defined in §6.2
- Response schema as defined in §6.3
- Batch submission and polling logic
- JSON response parser (validates list structure, handles empty lists)
- Retry logic per §6.4
- Unit tests using mocked Gemini responses covering: empty list, single grant, multiple grants, malformed JSON

Acceptance criteria: Extractor correctly submits batches, parses responses returning lists of raw grant objects, and handles all error conditions without crashing.

### Phase C — Normalisation Layer and Database Writer

Deliverables:
- `stage3/normaliser.py`: all normalisation rules from §7.2
- All five JSON lookup files in `data/`
- Content hash computation (§7.3)
- Review flag determination (§5.2)
- `stage3/writer.py`: upsert logic with confidence-based conflict resolution (§8)
- Review queue CSV exporter
- Unit tests for every normalisation rule, covering: country name variants, date format variants, supranational group expansion, controlled vocabulary matching, content hash stability

Acceptance criteria: A raw LLM response object passes through the normalisation layer and emerges as a correctly structured, fully normalised grant record. Content hash is stable across equivalent inputs. Upsert correctly replaces lower-confidence duplicates.

### Phase D — QA Reporting, Scheduler Integration, and End-to-End Test

Deliverables:
- `stage3/qa_reporter.py`: extraction report writer (§11)
- `stage3/status_refresh.py`: daily status recalculation job (§11) — re-evaluates computed statuses and closes expired records
- Review import script: `stage3/review_import.py`
- APScheduler integration: Stage 3 trigger and daily status refresh job added to existing `crawl_scheduler.py`
- Command-line entry point:
  - `python -m stage3 --date YYYY-MM-DD` — manual extraction run for a specific cycle date
  - `python -m stage3 --dry-run` — scans and prepares pages, calls `count_tokens()` to estimate cost (note: count_tokens() itself makes lightweight API calls; the estimated cost of the estimation pass is logged in the dry-run summary output), submits no LLM calls, writes nothing to the database
  - `python -m stage3 --force` — bypass the Stage 2 sentinel file check (for manual reruns)
- Unit tests for `status_refresh.py`: Open→Closed transition, Upcoming→Open transition, same-day deadline edge case, records with `status_source = 'extracted'` must not be modified
- End-to-end integration test using a fixture `raw_cache` directory with 10 real-format pages
- `.env.example` updated with all required variables (§13.1)

Acceptance criteria: Running the full Stage 3 pipeline against the fixture raw_cache produces correct grant records in PostgreSQL, a review queue CSV in `stage3_output/`, and an extraction report JSON. `--dry-run` outputs a cost estimate without touching the database. `status_refresh.py` correctly closes expired Open records and promotes past-opening-date Upcoming records. All phases' tests pass together.

---

## 13. Dependencies and Configuration

### 13.1 Required environment variables

```
GEMINI_API_KEY=                  # Google AI API key for Gemini 3.5 Flash
DATABASE_URL=                    # PostgreSQL connection string
                                 # e.g. postgresql://user:password@localhost:5432/grantglobe
RAW_CACHE_DIR=                   # Path to Stage 2 raw_cache directory
STAGE3_OUTPUT_DIR=stage3_output  # Directory for review CSVs and extraction reports
                                 # Created automatically if it does not exist
STAGE3_BATCH_SIZE=2000           # Max pages per Gemini batch (default: 2000)
STAGE3_MAX_RETRIES=3             # Max retries per failed page (default: 3)
STAGE3_REVIEW_CONFIDENCE_THRESHOLD=low   # Minimum confidence level to trigger human review flag
                                         # accepted values: low | medium (default: low)
STAGE3_MAX_COST=                 # Optional hard cost ceiling in USD. If set, the pipeline
                                 # estimates total cost before submitting any batches and aborts
                                 # with a CRITICAL-level log if the estimate exceeds this value.
                                 # Intended as a safeguard against accidental large runs.
                                 # Leave unset to disable the ceiling check.
```

### 13.2 Python dependencies (additions to existing requirements.txt)

```
google-generativeai>=0.8.0
psycopg2-binary>=2.9.9
alembic>=1.13.0
beautifulsoup4>=4.12.0
lxml>=5.0.0
rapidfuzz>=3.6.0
structlog>=24.0.0
```

### 13.3 Directory structure

```
Stage_3_extraction/
├── stage3/
│   ├── __init__.py
│   ├── __main__.py              # CLI entry point
│   ├── batch_processor.py       # Orchestrates the full pipeline
│   ├── extractor.py             # Gemini API client
│   ├── normaliser.py            # All normalisation rules
│   ├── writer.py                # PostgreSQL upsert logic
│   ├── qa_reporter.py           # Extraction report writer
│   ├── review_import.py         # Review queue CSV importer
│   ├── status_refresh.py        # Daily status recalculation job
│   └── db.py                    # Database connection and session management
├── data/
│   ├── country_lookup.json
│   ├── funder_authority.json
│   ├── currency_lookup.json
│   ├── supranational_groups.json
│   └── region_lookup.json
├── migrations/                  # Alembic migration files
├── stage3_output/               # Stage 3 artefacts (review CSVs, extraction reports)
│   └── .gitkeep                 # Keep directory in version control; contents are gitignored
├── tests/
│   ├── fixtures/                # Sample raw_cache pages and expected outputs
│   ├── test_batch_processor.py
│   ├── test_extractor.py
│   ├── test_normaliser.py
│   ├── test_writer.py
│   ├── test_status_refresh.py   # Open→Closed and Upcoming→Open transitions; edge cases
│   └── test_end_to_end.py
├── alembic.ini
├── requirements.txt
└── .env.example
```

---

*Document version: 1.4 — May 2026*
*v1.1 incorporates all valid findings from the first openclaw review: content hash corrected (deadline excluded, NFKC normalisation added); deduplication SQL replaced with Python-computed aggregate score; status auto-computation rules corrected with High confidence gate, rolling and upcoming rules, and staleness resolution; ai_focused_confidence column removed; description and deadline_notes fields added; GIN index for applicant_base_regions added; organisation_types and applicant_base confidence scores added; Phase 0 added; SELECT FOR UPDATE SKIP LOCKED and startup crash recovery documented; multilingual extraction rule added; count_tokens() specified; STAGE3_MAX_COST and --dry-run added.*
*v1.2 incorporates all valid findings from the second openclaw review: grant_opening_date field added throughout (DB schema, response schema, system prompt, normalisation rule); startup recovery corrected to use 8-hour staleness threshold; daily status refresh extended to cover Upcoming→Open transition; pages_skipped_content_too_short counter added; Stage 2 crawl_complete sentinel file mechanism added; STAGE3_REVIEW_CONFIDENCE_THRESHOLD behaviour documented precisely; non-English controlled vocabulary limitation noted; batch partial-failure handling specified; output directory changed to stage3_output/; test_status_refresh.py added; content hash collision limitation noted; --force flag added.*
*v1.3 incorporates all valid findings from the third openclaw review: status rules 3 and 4 swapped so Upcoming detection precedes Open/Closed check — a grant that has not yet opened cannot be Open regardless of its deadline; confidence gate added to Upcoming rule (grant_opening_date must be high confidence); review_status set to 'approved' at insert for requires_review=false records, making Stage 4 query unambiguous; status_refresh.py transition order specified (Upcoming→Open first, then Open→Closed) with explanation of why order matters; UTC specified for all date comparisons in normalisation layer, status refresh job, and Stage 4; description length guidance added to system prompt; system prompt rule 12 corrected — no longer promises that the normalisation system translates controlled vocabulary fields; batch polling interval specified (5 min for first hour, 15 min thereafter); STAGE3_OUTPUT_DIR env var added.*
*v1.4 incorporates all valid findings from the fourth openclaw review: upsert SET clause now preserves review_status when the existing value is 'approved' or 'rejected' — a higher-confidence re-extraction cannot overwrite an operator's decision; review_status index replaced with full index (was partial WHERE requires_review=true, which excluded the majority of approved records from the Stage 4 query); partial index retained as idx_grants_review_queue for the review workflow; composite index idx_grants_stage4_filter added; datetime.utcnow() replaced with datetime.now(timezone.utc).date() throughout (utcnow() deprecated in Python 3.12); CURRENT_DATE AT TIME ZONE 'UTC' corrected to plain CURRENT_DATE in SQL (DATE columns are timezone-independent in PostgreSQL; UTC is enforced at the Python layer).*
*v1.5 incorporates all valid findings from the fifth openclaw review: upsert CASE guard extended with AND EXCLUDED.requires_review = false — a re-extraction that raises a new review flag now correctly resets review_status to pending even if the record was previously approved, while routine higher-confidence updates that do not raise flags continue to preserve operator decisions; cross-reference corrected in §7.2 grant opening date paragraph (rule 4 → rule 3); cross-reference corrected in §7.2 prototype limitation paragraph (system prompt rule 11 → rule 12).*
*All architectural decisions confirmed prior to authoring. Do not modify controlled vocabularies (§10) without updating the normalisation layer lookup files and the Gemini system prompt simultaneously.*
