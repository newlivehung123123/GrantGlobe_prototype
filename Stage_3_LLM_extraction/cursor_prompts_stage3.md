# GrantGlobe Stage 3 — Cursor Build Prompts
## Based on Technical Design Document v1.5

Paste each prompt into Cursor in the order shown. Complete and verify the acceptance
criteria for each prompt before moving to the next. Do not skip phases.

The design document for full reference is at:
`Stage_3_LLM_extraction/stage3_extraction_design.md`

---

## PHASE 0 — PROMPT 1: Lookup Data Files

**What this builds**
Five flat JSON lookup files that the normalisation layer (Phase C) depends on at runtime.
Phase 0 has no Python code — it is data preparation only. These files must exist and be
correct before Phase C can be built or tested.

**Deliverables**
Create the following files in `Stage_3_extraction/data/`:

---

### `data/country_lookup.json`

Maps every country and territory name variant (lowercase) to its ISO 3166-1 alpha-2 code.
Include all 249 standard ISO 3166-1 codes plus the following non-standard entries:

```json
{
  "kosovo": "XK",
  "taiwan": "TW",
  "republic of china": "TW",
  "palestine": "PS",
  "state of palestine": "PS",
  "west bank and gaza": "PS",
  "hong kong": "HK",
  "macao": "MO",
  "macau": "MO"
}
```

For every country, include at minimum: the full official name, the common short name,
any widely used alternative names, and the demonym (e.g. "british" → "GB"). All keys
must be lowercase. Values must be exactly two uppercase letters.

Examples of the required breadth:
```json
{
  "united kingdom": "GB",
  "uk": "GB",
  "great britain": "GB",
  "britain": "GB",
  "england": "GB",
  "united states": "US",
  "usa": "US",
  "united states of america": "US",
  "america": "US",
  "south korea": "KR",
  "republic of korea": "KR",
  "korea": "KR",
  "democratic republic of the congo": "CD",
  "drc": "CD",
  "dr congo": "CD",
  "congo-kinshasa": "CD",
  "republic of the congo": "CG",
  "congo-brazzaville": "CG",
  "tanzania": "TZ",
  "united republic of tanzania": "TZ"
}
```

---

### `data/region_lookup.json`

Maps region name variants (lowercase) to the canonical UN M.49 label used in the
controlled vocabulary (§10.1 of the design document). Every canonical label must
appear as a value.

Canonical labels:
`Global`, `Sub-Saharan Africa`, `East Africa`, `West Africa`, `Central Africa`,
`Southern Africa`, `North Africa`, `Middle East and North Africa (MENA)`,
`South Asia`, `East Asia`, `South-East Asia`, `Central Asia`,
`Western Europe`, `Eastern Europe`, `Northern Europe`, `Southern Europe`,
`North America`, `Latin America and the Caribbean`, `Central America`,
`South America`, `Caribbean`, `Oceania / Pacific`, `Others`

```json
{
  "global": "Global",
  "worldwide": "Global",
  "international": "Global",
  "all countries": "Global",
  "sub-saharan africa": "Sub-Saharan Africa",
  "africa south of the sahara": "Sub-Saharan Africa",
  "east africa": "East Africa",
  "eastern africa": "East Africa",
  "west africa": "West Africa",
  "western africa": "West Africa",
  "middle east and north africa": "Middle East and North Africa (MENA)",
  "mena": "Middle East and North Africa (MENA)",
  "south asia": "South Asia",
  "south-east asia": "South-East Asia",
  "southeast asia": "South-East Asia",
  "asean": "South-East Asia",
  "latin america": "Latin America and the Caribbean",
  "latin america and the caribbean": "Latin America and the Caribbean",
  "pacific": "Oceania / Pacific",
  "oceania": "Oceania / Pacific"
}
```

Add at least 5 variants per canonical region.

---

### `data/currency_lookup.json`

Maps currency symbols, names, and abbreviations (lowercase) to ISO 4217 three-letter codes.

```json
{
  "$": "USD",
  "usd": "USD",
  "us dollar": "USD",
  "us dollars": "USD",
  "dollar": "USD",
  "£": "GBP",
  "gbp": "GBP",
  "pound": "GBP",
  "pound sterling": "GBP",
  "sterling": "GBP",
  "€": "EUR",
  "eur": "EUR",
  "euro": "EUR",
  "euros": "EUR",
  "¥": "JPY",
  "jpy": "JPY",
  "yen": "JPY",
  "cny": "CNY",
  "rmb": "CNY",
  "renminbi": "CNY",
  "chinese yuan": "CNY",
  "cad": "CAD",
  "canadian dollar": "CAD",
  "aud": "AUD",
  "australian dollar": "AUD",
  "chf": "CHF",
  "swiss franc": "CHF",
  "inr": "INR",
  "rupee": "INR",
  "indian rupee": "INR",
  "zar": "ZAR",
  "rand": "ZAR",
  "south african rand": "ZAR",
  "ngn": "NGN",
  "naira": "NGN",
  "kes": "KES",
  "kenyan shilling": "KES",
  "sek": "SEK",
  "swedish krona": "SEK",
  "nok": "NOK",
  "norwegian krone": "NOK",
  "dkk": "DKK",
  "danish krone": "DKK",
  "brl": "BRL",
  "real": "BRL",
  "brazilian real": "BRL",
  "mxn": "MXN",
  "mexican peso": "MXN",
  "sgd": "SGD",
  "singapore dollar": "SGD",
  "hkd": "HKD",
  "hong kong dollar": "HKD",
  "nzd": "NZD",
  "new zealand dollar": "NZD",
  "krw": "KRW",
  "won": "KRW",
  "korean won": "KRW"
}
```

---

### `data/supranational_groups.json`

Maps supranational group names to arrays of ISO 3166-1 alpha-2 codes for all constituent
member states. Use the current membership as of 2026.

```json
{
  "EU Member States": ["AT","BE","BG","CY","CZ","DE","DK","EE","ES","FI","FR","GR",
    "HR","HU","IE","IT","LT","LU","LV","MT","NL","PL","PT","RO","SE","SI","SK"],
  "OECD Member States": ["AU","AT","BE","CA","CL","CO","CZ","DK","EE","FI","FR","DE",
    "GR","HU","IS","IE","IL","IT","JP","KR","LV","LT","LU","MX","NL","NZ","NO","PL",
    "PT","SK","SI","ES","SE","CH","TR","GB","US"],
  "Commonwealth Member States": ["AG","AU","BS","BD","BB","BZ","BW","BN","CM","CA",
    "CY","DM","SZ","FJ","GM","GH","GD","GY","IN","JM","KE","KI","LS","MW","MY","MV",
    "MT","MU","MZ","NA","NR","NZ","NG","PK","PG","RW","KN","LC","VC","WS","SL","SG",
    "SB","ZA","LK","TZ","TO","TT","TV","UG","GB","VU","ZM"],
  "African Union Member States": ["DZ","AO","BJ","BW","BF","BI","CM","CV","CF","TD",
    "KM","CD","CG","CI","DJ","EG","GQ","ER","SZ","ET","GA","GM","GH","GN","GW","KE",
    "LS","LR","LY","MG","MW","ML","MR","MU","MA","MZ","NA","NE","NG","RW","ST","SN",
    "SL","SO","ZA","SS","SD","TZ","TG","TN","UG","ZM","ZW"],
  "ASEAN Member States": ["BN","KH","ID","LA","MY","MM","PH","SG","TH","VN"],
  "LMIC": [],
  "LDC": []
}
```

For LMIC and LDC: populate with the current World Bank and UN classifications as of 2026.
These lists are long — use the authoritative source lists.

---

### `data/funder_authority.json`

**Stub file only** at prototype stage. Populate with the 30 highest-frequency funders
from the Stage 1 source directory. This file will be expanded incrementally as the
system is used; an unmatched funder is stored as extracted, not rejected.

Each entry maps a lowercase name variant to a canonical name and ROR ID.

```json
{
  "wellcome trust": {
    "canonical_name": "Wellcome Trust",
    "ror_id": "029chgv08"
  },
  "wellcome": {
    "canonical_name": "Wellcome Trust",
    "ror_id": "029chgv08"
  },
  "bill and melinda gates foundation": {
    "canonical_name": "Bill & Melinda Gates Foundation",
    "ror_id": "0456r8d26"
  },
  "gates foundation": {
    "canonical_name": "Bill & Melinda Gates Foundation",
    "ror_id": "0456r8d26"
  },
  "european research council": {
    "canonical_name": "European Research Council",
    "ror_id": "0472cxd90"
  },
  "erc": {
    "canonical_name": "European Research Council",
    "ror_id": "0472cxd90"
  },
  "uk research and innovation": {
    "canonical_name": "UK Research and Innovation",
    "ror_id": "001aqnf71"
  },
  "ukri": {
    "canonical_name": "UK Research and Innovation",
    "ror_id": "001aqnf71"
  },
  "ford foundation": {
    "canonical_name": "Ford Foundation",
    "ror_id": "021nxhr62"
  },
  "open society foundations": {
    "canonical_name": "Open Society Foundations",
    "ror_id": "04mhx3549"
  },
  "rockefeller foundation": {
    "canonical_name": "Rockefeller Foundation",
    "ror_id": "03gkh6891"
  },
  "national institutes of health": {
    "canonical_name": "National Institutes of Health",
    "ror_id": "01cwqze88"
  },
  "nih": {
    "canonical_name": "National Institutes of Health",
    "ror_id": "01cwqze88"
  },
  "national science foundation": {
    "canonical_name": "National Science Foundation",
    "ror_id": "021nxhr62"
  },
  "nsf": {
    "canonical_name": "National Science Foundation",
    "ror_id": "021nxhr62"
  }
}
```

Add at least 15 more entries drawn from the highest-frequency domains in the Stage 1
source list.

---

**Acceptance criteria**
- All five files exist under `Stage_3_extraction/data/` and parse as valid JSON.
- `country_lookup.json` has at least 600 entries (ISO alpha-2 values only, no nulls).
- `region_lookup.json` has entries for all 23 canonical region labels.
- `currency_lookup.json` covers at minimum all 28 currencies listed in §10.10 of the design doc.
- `supranational_groups.json` has non-empty arrays for all groups except LMIC/LDC.
- `funder_authority.json` parses and contains at least 30 distinct canonical_name entries.
- Run `python -c "import json; [json.load(open(f'data/{f}')) for f in ['country_lookup.json','region_lookup.json','currency_lookup.json','supranational_groups.json','funder_authority.json']]; print('all OK')"` from `Stage_3_extraction/` — must print `all OK`.

---

## PHASE A — PROMPT 1: Project Structure and Database Migration

**What this builds**
The complete directory skeleton for Stage 3 and the Alembic database migration that
creates the `grants` and `extraction_log` tables with every index. No extraction logic yet.

**Read §4 (Database Schema) of stage3_extraction_design.md in full before building.**

**Deliverables**

Create the full directory structure:

```
Stage_3_extraction/
├── stage3/
│   ├── __init__.py
│   ├── __main__.py              # empty for now
│   ├── batch_processor.py       # empty stub
│   ├── extractor.py             # empty stub
│   ├── normaliser.py            # empty stub
│   ├── writer.py                # empty stub
│   ├── qa_reporter.py           # empty stub
│   ├── review_import.py         # empty stub
│   ├── status_refresh.py        # empty stub
│   └── db.py                    # implement now (see below)
├── data/                        # already populated in Phase 0
├── migrations/
│   └── versions/
├── stage3_output/
│   └── .gitkeep
├── tests/
│   ├── fixtures/
│   ├── test_batch_processor.py  # empty stub
│   ├── test_extractor.py        # empty stub
│   ├── test_normaliser.py       # empty stub
│   ├── test_writer.py           # empty stub
│   ├── test_status_refresh.py   # empty stub
│   └── test_end_to_end.py       # empty stub
├── alembic.ini
├── requirements.txt
└── .env.example                 # empty stub
```

---

**`stage3/db.py`**

Implement database connection and session management using `psycopg2-binary`.

```python
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager

def get_connection():
    return psycopg2.connect(os.environ["DATABASE_URL"])

@contextmanager
def get_cursor(conn=None, *, cursor_factory=RealDictCursor):
    """Context manager yielding a cursor; commits on exit, rolls back on error."""
    own_conn = conn is None
    conn = conn or get_connection()
    try:
        with conn.cursor(cursor_factory=cursor_factory) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        if own_conn:
            conn.close()
```

---

**Alembic migration**

Create a single Alembic migration file that produces EXACTLY the following schema.
Every column, constraint, and index must match the design spec precisely.

```sql
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE grants (
    -- Identity
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content_hash                CHAR(64) UNIQUE NOT NULL,
    -- content_hash = SHA-256(NFKC(lower(funder_name)) || '||' || NFKC(lower(grant_title)))

    -- Core descriptive fields
    grant_title                 TEXT NOT NULL,
    funder_name                 TEXT NOT NULL,
    funder_ror_id               TEXT,
    source_url                  TEXT NOT NULL,
    application_portal_url      TEXT,
    description                 TEXT,

    -- Deadlines
    application_deadline        DATE,
    application_deadline_raw    TEXT,
    application_deadline_type   TEXT,
    deadline_notes              TEXT,
    eoi_deadline                DATE,
    eoi_deadline_raw            TEXT,
    eoi_deadline_type           TEXT,

    -- Grant opening date
    grant_opening_date          DATE,
    grant_opening_date_raw      TEXT,

    -- Funding amount
    funding_amount_min          NUMERIC(15,2),
    funding_amount_max          NUMERIC(15,2),
    currency                    CHAR(3),
    funding_amount_type         TEXT,

    -- Status
    current_status              TEXT,
    status_source               TEXT,

    -- Language
    source_language             CHAR(10),

    -- AI focus
    ai_focused                  BOOLEAN,

    -- Eligibility
    individuals_not_eligible    BOOLEAN NOT NULL DEFAULT false,
    organisation_types          TEXT[],
    individual_eligibility      TEXT[],

    -- Geographic scope — applicant base
    applicant_base_regions      TEXT[],
    applicant_base_countries    CHAR(2)[],

    -- Geographic scope — funded work
    geographic_focus_regions    TEXT[],
    geographic_focus_countries  CHAR(2)[],

    -- Thematic classification
    thematic_sectors            TEXT[],
    grant_types                 TEXT[],

    -- Confidence scores
    confidence_scores           JSONB NOT NULL DEFAULT '{}',
    aggregate_confidence_score  INTEGER NOT NULL DEFAULT 0,

    -- Raw extraction (audit)
    raw_extraction              JSONB NOT NULL DEFAULT '{}',

    -- Review workflow
    requires_review             BOOLEAN NOT NULL DEFAULT false,
    review_status               TEXT NOT NULL DEFAULT 'pending',

    -- Provenance
    domain                      TEXT NOT NULL,
    crawl_date                  DATE NOT NULL,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE extraction_log (
    id                  SERIAL PRIMARY KEY,
    url_hash            CHAR(16) NOT NULL,
    domain              TEXT NOT NULL,
    crawl_date          DATE NOT NULL,
    processed_at        TIMESTAMPTZ,
    status              TEXT NOT NULL DEFAULT 'pending',
    records_extracted   INTEGER DEFAULT 0,
    error_message       TEXT,
    retry_count         INTEGER DEFAULT 0,
    UNIQUE (url_hash, crawl_date)
);
```

After the table definitions, create ALL of the following indexes in the same migration:

```sql
-- Deduplication
CREATE UNIQUE INDEX idx_grants_content_hash ON grants (content_hash);

-- GIN indexes for array containment queries
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
CREATE INDEX idx_grants_domain                     ON grants (domain);

-- Review status indexes
-- Full index for Stage 4 reader query (WHERE review_status = 'approved')
CREATE INDEX idx_grants_review_status              ON grants (review_status);
-- Partial index for review queue export (WHERE requires_review = true)
CREATE INDEX idx_grants_review_queue               ON grants (review_status, created_at DESC)
    WHERE requires_review = true;
-- Composite index for Stage 4 combined filter
CREATE INDEX idx_grants_stage4_filter              ON grants (review_status, current_status, application_deadline);

-- Extraction log
CREATE INDEX idx_extraction_log_status ON extraction_log (status);
CREATE INDEX idx_extraction_log_domain ON extraction_log (domain, crawl_date);
```

---

**`requirements.txt`**

```
google-generativeai>=0.8.0
psycopg2-binary>=2.9.9
alembic>=1.13.0
beautifulsoup4>=4.12.0
lxml>=5.0.0
rapidfuzz>=3.6.0
structlog>=24.0.0
python-dotenv>=1.0.0
python-dateutil>=2.9.0
apscheduler>=3.10.0
pytest>=8.0.0
```

---

**Acceptance criteria**
- `alembic upgrade head` runs without error against a clean PostgreSQL database.
- `\d grants` in psql shows all columns, types, and constraints as specified.
- `\di grants*` shows all 15 indexes.
- `\d extraction_log` shows the correct schema including the UNIQUE constraint.
- `python -c "from stage3.db import get_connection; print('db ok')"` prints `db ok`.

---

## PHASE A — PROMPT 2: Batch Processor Core

**What this builds**
The `batch_processor.py` startup recovery, raw_cache scanner, and `extraction_log` manager.
No LLM calls. No content preparation. This prompt covers the orchestration skeleton only.

**Read §3 (Architecture) and §5.1 (Step-by-step flow, steps 0 and 1) of the design doc.**

**Implement in `stage3/batch_processor.py`**

```python
"""
Batch Processor — orchestrates the Stage 3 extraction pipeline.

Startup:
  1. Reset stale 'processing' rows (>8 hours old) to 'pending'.
  2. Check for Stage 2 crawl_complete sentinel file.
  3. Scan raw_cache for changed pages not yet completed.
  4. Claim rows using SELECT FOR UPDATE SKIP LOCKED.
"""
```

Implement the following functions/class:

**`reset_stale_processing_rows(conn)`**
```sql
UPDATE extraction_log
SET status = 'pending', error_message = 'reset from stale processing'
WHERE status = 'processing'
  AND processed_at < NOW() - INTERVAL '8 hours';
```
Log how many rows were reset at INFO level.

**`check_crawl_complete_sentinel(raw_cache_dir, run_date, *, force=False)`**
- If `force=True`: return immediately (bypass check).
- Otherwise: look for `{raw_cache_dir}/crawl_complete_{run_date}.json`.
- If found: return.
- If not found: poll every 15 minutes for up to 4 hours.
- If still not found after 4 hours: raise `RuntimeError` and log at WARNING level.

**`scan_for_pending_pages(conn, raw_cache_dir, run_date)`**
- Walk `raw_cache_dir` recursively for all `.meta.json` files where `"changed": true`
  and `"crawl_date"` matches `run_date`.
- For each: INSERT into `extraction_log (url_hash, domain, crawl_date)` with
  `ON CONFLICT (url_hash, crawl_date) DO NOTHING`.
- Return count of rows inserted.

**`claim_pending_rows(conn, batch_size=100)`**
- Use `SELECT FOR UPDATE SKIP LOCKED` to atomically claim up to `batch_size` pending rows:
```sql
SELECT id, url_hash, domain, crawl_date
FROM extraction_log
WHERE status = 'pending'
ORDER BY id
LIMIT %(batch_size)s
FOR UPDATE SKIP LOCKED;
```
- Immediately UPDATE claimed rows to `status = 'processing'`, `processed_at = NOW()`.
- Return the list of claimed row dicts.

**`mark_completed(conn, row_id, records_extracted)`**
**`mark_failed(conn, row_id, error_message)`**
**`mark_skipped(conn, row_id, reason)`**
Simple UPDATE functions setting status and error_message.

---

**Unit tests in `tests/test_batch_processor.py`**

- `test_reset_stale_rows`: inserts a 'processing' row with `processed_at = NOW() - 9 hours`
  and a 'processing' row with `processed_at = NOW() - 1 hour`; after calling the function,
  the old row is 'pending' and the recent row is still 'processing'.
- `test_scan_inserts_changed_pages`: given a mock raw_cache with three .meta.json files
  (two with `changed: true`, one with `changed: false`), scan inserts exactly two rows.
- `test_claim_rows_skip_locked`: two workers calling `claim_pending_rows` concurrently
  should not claim the same row.

**Acceptance criteria**
- All three unit tests pass.
- `python -m pytest tests/test_batch_processor.py -v` exits 0.

---

## PHASE A — PROMPT 3: Content Preparation

**What this builds**
HTML stripping, PDF text reading, token counting, and minimum length checking —
the per-page content preparation step that runs before LLM submission.

**Read §5.1 step 2 and §5.3 of the design doc.**

**Implement in `stage3/batch_processor.py`** (add to existing file)

**`prepare_html_page(meta_json_path, raw_cache_dir, model_name)`**

1. Read `.meta.json` to get `url_hash` and `html_path` (relative path to `.html.gz`).
2. Decompress `{raw_cache_dir}/{html_path}` using `gzip`.
3. Strip HTML tags using `BeautifulSoup(content, "lxml").get_text(separator=" ", strip=True)`.
4. Measure token count using `google.generativeai.GenerativeModel(model_name).count_tokens(text)`.
5. If token count < 50: return `None` with reason `"content_too_short"`.
6. If token count > 6000: truncate to 6000 tokens using `truncate_to_token_budget` (see below).
7. Return the stripped, truncated text string.

**`prepare_pdf_page(meta_json_path)`**

1. Read `.meta.json`. Extract `pdf_text` field. If absent or empty: return `None` with
   reason `"no_pdf_text"`.
2. Truncate to 12,000 tokens using the same counting and truncation approach.
3. Return the text string.

**Token truncation helper `truncate_to_token_budget(text, max_tokens, model_name)`**

Binary-search on word boundaries to find the largest prefix within `max_tokens`.
Must complete in **exactly ≤ 5 iterations**. Implementation pattern:

```python
def truncate_to_token_budget(text: str, max_tokens: int, model_name: str) -> str:
    words = text.split()
    if not words:
        return ""
    lo, hi = 0, len(words)
    for _ in range(5):
        if hi - lo <= 1:
            break
        mid = (lo + hi) // 2
        candidate = " ".join(words[:mid])
        if _count_tokens(candidate, model_name) <= max_tokens:
            lo = mid
        else:
            hi = mid
    # lo is the largest word count confirmed to fit.
    return " ".join(words[:lo]) if lo > 0 else words[0]
```

Invariant: `lo` words are confirmed to fit; `hi` words are confirmed to exceed budget.
**Do NOT use a simple iterative word-removal loop** — that approach is O(n) and
may require thousands of `count_tokens()` API calls for long pages.

---

**Unit tests in `tests/test_batch_processor.py`** (add to existing file)

Use fixture files in `tests/fixtures/`:
- `sample_page.html.gz`: a gzip-compressed HTML file with ~500 words of grant content.
- `short_page.html.gz`: a gzip-compressed HTML file with 30 words (below 50-token threshold).
- `sample_meta_html.json`: a .meta.json pointing at `sample_page.html.gz` with `changed: true`.
- `sample_meta_pdf.json`: a .meta.json with a `pdf_text` field of 200 words.

Tests:
- `test_html_preparation_returns_text`: normal page returns a non-empty string.
- `test_short_page_returns_none`: short page returns `None, "content_too_short"`.
- `test_html_truncation`: a page over 6000 tokens is truncated to ≤ 6000.
- `test_pdf_preparation`: PDF meta returns correct text string.

**Acceptance criteria**
- All Phase A unit tests pass: `python -m pytest tests/test_batch_processor.py -v` exits 0.
- `prepare_html_page` and `prepare_pdf_page` handle missing files with a logged error
  and return `None` rather than raising uncaught exceptions.

---

## PHASE B — PROMPT 1: Gemini Extractor — Client, System Prompt, Response Schema

**What this builds**
The Gemini 3.5 Flash API client, the full 12-rule system prompt, and the strict JSON
response schema that constrains the LLM output.

**Read §6 (LLM Integration) of the design doc in full before building.**

**Implement in `stage3/extractor.py`**

```python
"""
LLM Extractor — Gemini 3.5 Flash Batch API client.

MODEL_NAME is a module-level constant. Verify the exact API string against
Google AI documentation at build time — it may be 'gemini-3.5-flash' or a
versioned alias such as 'gemini-3.5-flash-001'.
"""

MODEL_NAME = "gemini-3.5-flash"  # Verify this string before first API call
```

**System prompt**

Implement the system prompt from §6.2 of the design doc verbatim, including all 12 rules.
Store it as a module-level constant `SYSTEM_PROMPT`. Rules 1–12 must appear in full —
do not summarise or paraphrase them. Rule 12 (non-English documents) must say exactly:

> "Controlled-vocabulary matching is English-only in this prototype. If the source is
> non-English, extract values in the source language — they will be preserved in the
> raw data and flagged for review."

**Response schema**

Implement the response schema from §6.3 as a Python dict `RESPONSE_SCHEMA` that can be
passed to Gemini's `response_schema` parameter. The schema must include every field listed
in §6.3, specifically:

Array of objects where each object has ALL of these properties:
`grant_title`, `funder_name`, `description`, `application_deadline_raw`,
`deadline_notes`, `eoi_deadline_raw`, `grant_opening_date_raw`,
`funding_amount_min`, `funding_amount_max`, `currency_raw`,
`current_status_raw`, `application_portal_url`, `source_language_raw`,
`ai_focused`, `individuals_not_eligible`,
`organisation_types_raw`, `individual_eligibility_raw`, `applicant_base_raw`,
`geographic_focus_raw`, `thematic_sectors_raw`, `grant_types_raw`,
`raw_notes`,
and a nested `confidence_scores` object containing scores for:
`grant_title`, `funder_name`, `application_deadline`, `eoi_deadline`,
`grant_opening_date`, `funding_amount`, `current_status`, `geographic_focus`,
`thematic_sectors`, `individual_eligibility`, `organisation_types`,
`applicant_base`, `ai_focused`
— each constrained to `enum: ["high", "medium", "low", "not_found"]`.

**`build_page_prompt(page_text)`**

Returns the complete prompt string: `SYSTEM_PROMPT + "\n\nPage content:\n" + page_text`.

**Acceptance criteria**
- `from stage3.extractor import MODEL_NAME, SYSTEM_PROMPT, RESPONSE_SCHEMA, build_page_prompt`
  imports without error.
- `len(SYSTEM_PROMPT.split("\\n"))` contains at least 12 numbered rules.
- `RESPONSE_SCHEMA["type"] == "array"` and
  `"grant_opening_date_raw" in RESPONSE_SCHEMA["items"]["properties"]`.
- `"grant_opening_date" in RESPONSE_SCHEMA["items"]["properties"]["confidence_scores"]["properties"]`.

---

## PHASE B — PROMPT 2: Batch Submission, Polling, and Error Handling

**What this builds**
The Gemini Batch API submission, polling loop, partial-failure handling, and retry logic.

**Read §6.1 and §6.4 of the design doc.**

**Implement in `stage3/extractor.py`** (add to existing file)

**`submit_batch(page_prompts)`**
- `page_prompts`: list of `{"url_hash": str, "prompt": str}` dicts.
- Submit as a Gemini Batch API job using `google.generativeai`.
- Return the job ID.

**`poll_batch_until_complete(job_id)`**
Polling schedule:
- First 60 minutes: poll every 5 minutes.
- After 60 minutes: poll every 15 minutes.
- Hard timeout: 6 hours total. If not complete after 6 hours, raise
  `BatchTimeoutError` and log at CRITICAL level.

**`parse_batch_results(job_id, claimed_rows)`**
- `claimed_rows`: list of row dicts from `extraction_log` (url_hash → row mapping).
- Fetch completed batch output.
- For each request in the output:
  - If succeeded: parse JSON response. Validate it is a list (even if empty). Collect
    raw grant objects.
  - If failed: mark the corresponding `extraction_log` row as 'failed' with the error
    message from the batch output metadata. Collect failed url_hashes for retry.
- Return `(list_of_raw_grant_objects, list_of_failed_url_hashes)`.

**`extract_pages(page_contents, conn)`**
Top-level function that orchestrates one batch cycle:
1. Call `submit_batch`.
2. Call `poll_batch_until_complete`.
3. Call `parse_batch_results`.
4. Return raw grant objects.

Error handling table (from §6.4 — implement all cases):

| Condition | Behaviour |
|---|---|
| API timeout | Retry 3 times with backoff 30s, 60s, 120s |
| Invalid JSON response | Log error, mark row 'failed', skip |
| Empty list `[]` | Valid — mark 'completed', records_extracted=0 |
| Rate limit 429 | Pause 60s, resume |
| Complete batch failure | Re-submit as new batch |
| Partial batch failure | Process successes, mark failures, collect for retry |

**Acceptance criteria**
- `from stage3.extractor import extract_pages` imports without error.
- `BatchTimeoutError` is a defined exception class.
- All error conditions in the table above have corresponding handling paths.

---

## PHASE B — PROMPT 3: Response Parser and Unit Tests

**What this builds**
The JSON response parser that converts raw Gemini output into Python dicts, plus all
unit tests for the extractor module.

**Add to `stage3/extractor.py`**

**`parse_llm_response(raw_json_str)`**
- Parse `raw_json_str` as JSON.
- Validate: must be a list. If not a list, raise `ValueError`.
- For each item in the list: validate it is a dict with at least `grant_title` and
  `confidence_scores` keys. If malformed, log at WARNING and skip the item.
- Return the list of valid grant dicts (may be empty).

---

**Unit tests in `tests/test_extractor.py`**

Use mocked Gemini API responses — do NOT make real API calls in tests.

```python
import pytest
from unittest.mock import patch, MagicMock
from stage3.extractor import parse_llm_response, RESPONSE_SCHEMA, SYSTEM_PROMPT
```

Write tests for:

- `test_empty_list_response`: `parse_llm_response("[]")` returns `[]`.
- `test_single_grant`: valid single-grant JSON returns a list of length 1 with correct fields.
- `test_multiple_grants`: JSON with 3 grant objects returns a list of length 3.
- `test_malformed_json_raises`: `parse_llm_response("not json")` raises `ValueError`.
- `test_non_list_raises`: `parse_llm_response('{"grant_title": "x"}')` raises `ValueError`
  (object not list).
- `test_malformed_item_skipped`: a list where one item is missing `confidence_scores`
  is skipped; valid items are returned.
- `test_response_schema_has_all_fields`: assert `RESPONSE_SCHEMA` contains all 13
  confidence score fields including `grant_opening_date` and `applicant_base`.
- `test_system_prompt_rule_12_no_translation_promise`: assert `"normalisation system"` and
  `"translation"` do not appear together in `SYSTEM_PROMPT` — the prompt must not promise
  that the normaliser translates non-English values.

**Acceptance criteria**
- `python -m pytest tests/test_extractor.py -v` exits 0 (all 8 tests pass).
- No real API calls are made during tests.

---

## PHASE C — PROMPT 1: Core Field Normalisation

**What this builds**
The first half of the normalisation layer: grant title, funder name, all deadline fields,
grant opening date, currency, and source language.

**Read §7.2 of the design doc in full before building.**

**Implement in `stage3/normaliser.py`**

```python
"""
Normalisation layer — maps raw LLM output to standards before database insertion.

All lookup files are loaded once at module import time.
"""
import json
import hashlib
import unicodedata
import re
from datetime import datetime, timezone
from pathlib import Path
from rapidfuzz import fuzz
from dateutil import parser as dateutil_parser  # MUST be a module-level import — never lazy

DATA_DIR = Path(__file__).parent.parent / "data"

# Load all lookup files at import
COUNTRY_LOOKUP    = json.loads((DATA_DIR / "country_lookup.json").read_text())
REGION_LOOKUP     = json.loads((DATA_DIR / "region_lookup.json").read_text())
CURRENCY_LOOKUP   = json.loads((DATA_DIR / "currency_lookup.json").read_text())
FUNDER_AUTHORITY  = json.loads((DATA_DIR / "funder_authority.json").read_text())
SUPRANATIONAL     = json.loads((DATA_DIR / "supranational_groups.json").read_text())
```

---

**`normalise_grant_title(raw)`**
- Strip leading/trailing whitespace.
- Title case.
- Strip terminal punctuation unless the last character is `?` or `!`.
- Return normalised string or `None` if input is None/empty.

**`normalise_funder_name(raw)`**
- Lowercase, strip for lookup.
- Exact match against `FUNDER_AUTHORITY` keys first.
- If no exact match: fuzzy match via `fuzz.ratio()` at threshold ≥ 90 across all keys.
- If matched: return `{"canonical_name": ..., "ror_id": ...}`.
- If unmatched: return `{"canonical_name": raw, "ror_id": None, "unmatched": True}`.
  Log at DEBUG: `"Unmatched funder: {raw}"`.

**`normalise_deadline(raw_str, confidence)`**
Returns `{"date": date_or_None, "type": type_str}`.

Parse `raw_str` using `dateutil_parser.parse()` (imported at module level as shown above).
Handle these `type` values in priority order (check the raw string, not the parsed date):
1. `"rolling"` — if raw contains "rolling", "open continuously", "no deadline", "ongoing"
2. `"tbc"` — if raw contains "tbc", "to be confirmed", "coming soon", "tba"
3. `"not_published"` — if raw is None and confidence == "not_found"
4. `"unextracted"` — if raw is None and confidence in ("low", "medium")
5. `"confirmed"` — if parse succeeds, return ISO 8601 date object and type "confirmed"
6. `"unextracted"` — parse failed

`eoi_deadline` and `grant_opening_date` use the same function.

**`normalise_currency(raw_str)`**
- Lowercase and strip.
- Exact match against `CURRENCY_LOOKUP`.
- If matched: return ISO 4217 code.
- If unmatched: return `"OTH"` and log raw string at DEBUG.

**`normalise_source_language(raw_str)`**
Map language names and codes to ISO 639-1. Include at minimum:
```python
LANG_MAP = {
    "english": "en", "en": "en",
    "french": "fr", "fr": "fr", "français": "fr",
    "spanish": "es", "es": "es", "español": "es",
    "arabic": "ar", "ar": "ar",
    "portuguese": "pt", "pt": "pt",
    "chinese": "zh-hans", "simplified chinese": "zh-hans", "zh-hans": "zh-hans",
    "traditional chinese": "zh-hant", "zh-hant": "zh-hant",
    "japanese": "ja", "ja": "ja",
    "korean": "ko", "ko": "ko",
    "german": "de", "de": "de",
    "dutch": "nl", "nl": "nl",
    "russian": "ru", "ru": "ru",
    "italian": "it", "it": "it",
    "swedish": "sv", "sv": "sv",
    "norwegian": "no", "no": "no",
    "danish": "da", "da": "da",
}
```
Unrecognised: return `"ot"`.

---

**Acceptance criteria**
- `from stage3.normaliser import normalise_grant_title, normalise_funder_name, normalise_deadline, normalise_currency, normalise_source_language` imports without error.
- Manual spot checks (run interactively):
  - `normalise_grant_title("the innovation fund.")` → `"The Innovation Fund"`
  - `normalise_deadline("rolling applications", "high")["type"]` → `"rolling"`
  - `normalise_deadline(None, "not_found")["type"]` → `"not_published"`
  - `normalise_currency("£")` → `"GBP"`
  - `normalise_funder_name("Wellcome Trust")["canonical_name"]` → `"Wellcome Trust"`

---

## PHASE C — PROMPT 2: Geographic, Vocabulary, Content Hash, and Review Flag

**What this builds**
Country normalisation, supranational group expansion, region mapping, controlled vocabulary
matching, content hash computation, aggregate confidence score, and review flag logic.

**Read §7.2 (remainder) and §7.3 and §5.2 of the design doc.**

**Add to `stage3/normaliser.py`**

---

**`normalise_country(raw_str)`**
1. Lowercase and strip.
2. Exact match in `COUNTRY_LOOKUP`.
3. If no exact match: fuzzy match with `fuzz.ratio()` at threshold ≥ 88 across keys.
4. If matched: return ISO 3166-1 alpha-2 code.
5. If unmatched: log raw string at DEBUG (`"Unmatched country: {raw}"`), return `"OT"`.

**`expand_supranational_group(raw_str)`**
- Lowercase and strip.
- Check if raw_str matches any key in `SUPRANATIONAL` (case-insensitive).
- If matched: return the list of ISO alpha-2 codes.
- Otherwise: return `None`.

**`normalise_geographic_list(raw_list)`**
Returns `{"regions": [...], "countries": [...]}`.

For each item in `raw_list`:
1. Try `expand_supranational_group` first. If matched: add the group label to regions,
   add all constituent codes to countries.
2. Otherwise: try `normalise_country`. If returns a valid code (not "OT"): add to countries.
   Also try `normalise_region` (see below) — add to regions if matched.
3. "OT" countries: add to countries list as "OT" (Stage 4 can filter these out).

**`normalise_region(raw_str)`**
- Lowercase, strip, match in `REGION_LOOKUP`.
- Unmatched: return `"Others"`.

**`normalise_controlled_vocab(raw_list, vocab_list)`**
For each item in `raw_list`:
- Case-insensitive exact match against `vocab_list`.
- If matched: add the matched vocab item (preserving canonical capitalisation).
- If unmatched: add `"Others"`. Log raw string at DEBUG.
Return list (may contain "Others").

---

**`compute_content_hash(funder_name, grant_title)`**

```python
def compute_content_hash(funder_name: str, grant_title: str) -> str:
    """
    SHA-256 of NFKC-normalised, lowercased funder_name + '||' + grant_title.

    Deadline is excluded: deadline extensions must update the record, not duplicate it.

    Known limitation: two grants from the same funder with identical titles (e.g.
    'Innovation Fund' as both a Research Grant and a Fellowship) will collide. This
    is surfaced as records_duplicate_lower_confidence in the QA report.
    """
    def norm(s: str) -> str:
        return unicodedata.normalize("NFKC", s).lower().strip()
    combined = norm(funder_name) + "||" + norm(grant_title)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()
```

---

**`aggregate_confidence_score(confidence_scores)`**

```python
_CONF_INT = {"high": 3, "medium": 2, "low": 1, "not_found": 0}

def aggregate_confidence_score(confidence_scores: dict) -> int:
    return sum(_CONF_INT.get(v, 0) for v in confidence_scores.values())
```

---

**`determine_review_flag(record, threshold="low")`**

Implement all seven rules from §5.2. The `threshold` parameter is read from
`os.environ.get("STAGE3_REVIEW_CONFIDENCE_THRESHOLD", "low")`.

At threshold `"low"`, review-triggering confidence levels are `{"low", "not_found"}`.
At threshold `"medium"`, review-triggering confidence levels are `{"medium", "low", "not_found"}`.

Rules:
- R1: `grant_title` confidence in trigger set → `True`
- R2: `funder_name` confidence in trigger set → `True`
- R3: `application_deadline` confidence in trigger set AND `application_deadline_type`
  not in `{"rolling", "tbc", "not_published"}` → `True`
- R4: `current_status == "Others"` → `True`
- R5: any field in `_R5_ARRAY_FIELDS = ("thematic_sectors", "geographic_focus_regions", "individual_eligibility")` contains `"Others"` → `True`

  **CRITICAL — `organisation_types` must NEVER be added to `_R5_ARRAY_FIELDS`.**
  `organisation_types` accepts free-text input and `"Others"` is a legitimate value
  that does not warrant a review flag. The constant must contain exactly three fields.
- R6: `ai_focused` confidence in `{"low", "not_found"}` (fixed — threshold does not affect R6) → `True`
- R7: `individuals_not_eligible is None` → `True`

Return `True` if any rule fires, `False` otherwise.

---

**Acceptance criteria**
- `from stage3.normaliser import normalise_country, normalise_geographic_list, normalise_controlled_vocab, compute_content_hash, aggregate_confidence_score, determine_review_flag` imports without error.
- Spot checks:
  - `normalise_country("United Kingdom")` → `"GB"`
  - `normalise_country("Britain")` → `"GB"`
  - `normalise_country("Zxqwerty")` → `"OT"`
  - `compute_content_hash("Wellcome Trust", "Innovation Fund")` is a 64-character hex string.
  - `compute_content_hash("Wellcome Trust", "Innovation Fund")` == `compute_content_hash("WELLCOME TRUST", "innovation fund")` (case-insensitive stability).
  - `aggregate_confidence_score({"grant_title": "high", "funder_name": "high"})` → `6`.

---

## PHASE C — PROMPT 3: Status Auto-Computation and Database Writer

**What this builds**
Status auto-computation (the 5-rule priority logic) and the full database writer with
the upsert CASE guard that preserves operator review decisions.

**Read §7.2 (status rules) and §8 of the design doc. The rule ordering is critical.**

**Add to `stage3/normaliser.py`**

**`compute_status(record)`**

Implements the 5 rules in strict order. All date comparisons use
`datetime.now(timezone.utc).date()`. The `from datetime import datetime, timezone`
import must be at the top of the file.

```
Rule 1: status_raw explicitly stated AND confidence == "high"
        → map to controlled vocabulary, status_source = "extracted"
        Controlled vocabulary: ["Open","Closed","Upcoming","Rolling","Suspended","Others"]
        If status_raw maps to a vocab item (case-insensitive): use it.
        If not: use "Others".

Rule 2: application_deadline_type == "rolling" AND status_raw is None
        → current_status = "Rolling", status_source = "computed"

Rule 3: grant_opening_date is not None
        AND confidence["grant_opening_date"] == "high"
        AND grant_opening_date > today (UTC)
        AND status_raw is None
        → current_status = "Upcoming", status_source = "computed"
        NOTE: This rule must run BEFORE rule 4. A grant not yet opened cannot be Open.

Rule 4: application_deadline_type == "confirmed"
        AND confidence["application_deadline"] == "high"
        AND status_raw is None
        → if application_deadline < today: current_status = "Closed", status_source = "computed"
        → if application_deadline >= today: current_status = "Open", status_source = "computed"

Rule 5 (fallback): current_status = None (sentinel), status_source = "sentinel"
```

Returns `{"current_status": str_or_None, "status_source": str}`.

---

**Implement `stage3/writer.py`**

```python
"""
Database Writer — upserts normalised grant records into PostgreSQL.

Key invariant: operator review decisions (review_status = 'approved' or 'rejected')
are preserved on re-extraction ONLY when the incoming record does not itself raise a
review flag. If requires_review = true on the new extraction, the record reverts to
'pending' so the quality concern is re-evaluated.
"""
```

**`upsert_grant(conn, record)`**

`record` is a fully normalised dict ready for the database.

The upsert SQL must include the CASE guard exactly as follows:

```sql
INSERT INTO grants (
    content_hash, grant_title, funder_name, funder_ror_id,
    source_url, application_portal_url, description,
    application_deadline, application_deadline_raw, application_deadline_type,
    deadline_notes, eoi_deadline, eoi_deadline_raw, eoi_deadline_type,
    grant_opening_date, grant_opening_date_raw,
    funding_amount_min, funding_amount_max, currency, funding_amount_type,
    current_status, status_source,
    source_language, ai_focused,
    individuals_not_eligible, organisation_types, individual_eligibility,
    applicant_base_regions, applicant_base_countries,
    geographic_focus_regions, geographic_focus_countries,
    thematic_sectors, grant_types,
    confidence_scores, aggregate_confidence_score,
    raw_extraction, requires_review, review_status,
    domain, crawl_date
)
VALUES (
    %(content_hash)s, %(grant_title)s, %(funder_name)s, %(funder_ror_id)s,
    ... [all parameters]
)
ON CONFLICT (content_hash) DO UPDATE SET
    grant_title                 = EXCLUDED.grant_title,
    funder_name                 = EXCLUDED.funder_name,
    funder_ror_id               = EXCLUDED.funder_ror_id,
    -- NOTE: source_url is intentionally ABSENT from this SET clause.
    -- source_url is set once on the initial INSERT and must never be overwritten.
    -- Subsequent higher-confidence updates preserve the original discovery URL.
    application_portal_url      = EXCLUDED.application_portal_url,
    description                 = EXCLUDED.description,
    application_deadline        = EXCLUDED.application_deadline,
    application_deadline_raw    = EXCLUDED.application_deadline_raw,
    application_deadline_type   = EXCLUDED.application_deadline_type,
    deadline_notes              = EXCLUDED.deadline_notes,
    eoi_deadline                = EXCLUDED.eoi_deadline,
    eoi_deadline_raw            = EXCLUDED.eoi_deadline_raw,
    eoi_deadline_type           = EXCLUDED.eoi_deadline_type,
    grant_opening_date          = EXCLUDED.grant_opening_date,
    grant_opening_date_raw      = EXCLUDED.grant_opening_date_raw,
    funding_amount_min          = EXCLUDED.funding_amount_min,
    funding_amount_max          = EXCLUDED.funding_amount_max,
    currency                    = EXCLUDED.currency,
    funding_amount_type         = EXCLUDED.funding_amount_type,
    current_status              = EXCLUDED.current_status,
    status_source               = EXCLUDED.status_source,
    source_language             = EXCLUDED.source_language,
    ai_focused                  = EXCLUDED.ai_focused,
    individuals_not_eligible    = EXCLUDED.individuals_not_eligible,
    organisation_types          = EXCLUDED.organisation_types,
    individual_eligibility      = EXCLUDED.individual_eligibility,
    applicant_base_regions      = EXCLUDED.applicant_base_regions,
    applicant_base_countries    = EXCLUDED.applicant_base_countries,
    geographic_focus_regions    = EXCLUDED.geographic_focus_regions,
    geographic_focus_countries  = EXCLUDED.geographic_focus_countries,
    thematic_sectors            = EXCLUDED.thematic_sectors,
    grant_types                 = EXCLUDED.grant_types,
    confidence_scores           = EXCLUDED.confidence_scores,
    aggregate_confidence_score  = EXCLUDED.aggregate_confidence_score,
    raw_extraction              = EXCLUDED.raw_extraction,
    requires_review             = EXCLUDED.requires_review,
    review_status = CASE
        WHEN grants.review_status IN ('approved', 'rejected')
             AND EXCLUDED.requires_review = false
        THEN grants.review_status
        ELSE EXCLUDED.review_status
    END,
    updated_at                  = NOW()
WHERE EXCLUDED.aggregate_confidence_score > grants.aggregate_confidence_score;
```

Return one of: `"inserted"`, `"updated"`, `"skipped"` (lower confidence, no change).

---

**Also add to `stage3/normaliser.py`: `normalise_raw_grant(raw_grant, source)`**

This is the top-level chaining function called by `run_extraction_cycle` for every raw
grant object returned by the LLM. It applies every Phase A–C normaliser in order and
returns a fully-normalised dict ready for `upsert_grant`.

```python
def normalise_raw_grant(raw_grant: dict, source: dict) -> dict:
    """
    Chain all normalisers and return a dict matching the grants table schema.

    Args:
        raw_grant: Raw dict as returned by parse_llm_response.
        source: Dict with keys: source_url (str), domain (str), crawl_date (str|date).
    """
    # -- Title and funder ---------------------------------------------------
    title  = normalise_grant_title(raw_grant.get("grant_title"))
    funder = normalise_funder_name(raw_grant.get("funder_name") or "")

    # -- Content hash -------------------------------------------------------
    content_hash = compute_content_hash(funder["canonical_name"], title or "")

    # -- Deadlines ----------------------------------------------------------
    cs = raw_grant.get("confidence_scores", {})
    app_dl   = normalise_deadline(raw_grant.get("application_deadline_raw"), cs.get("application_deadline", "not_found"))
    eoi_dl   = normalise_deadline(raw_grant.get("eoi_deadline_raw"),         cs.get("eoi_deadline", "not_found"))
    open_dt  = normalise_deadline(raw_grant.get("grant_opening_date_raw"),   cs.get("grant_opening_date", "not_found"))

    # -- Funding amount -----------------------------------------------------
    currency = normalise_currency(raw_grant.get("currency_raw") or "")

    # -- Geographic scope ---------------------------------------------------
    geo_focus  = normalise_geographic_list(raw_grant.get("geographic_focus_raw") or [])
    app_base   = normalise_geographic_list(raw_grant.get("applicant_base_raw") or [])

    # -- Controlled vocabularies --------------------------------------------
    thematic   = normalise_controlled_vocab(raw_grant.get("thematic_sectors_raw") or [], THEMATIC_SECTORS_VOCAB)
    org_types  = normalise_controlled_vocab(raw_grant.get("organisation_types_raw") or [], ORGANISATION_TYPES_VOCAB)
    ind_elig   = normalise_controlled_vocab(raw_grant.get("individual_eligibility_raw") or [], INDIVIDUAL_ELIGIBILITY_VOCAB)
    grant_types= normalise_controlled_vocab(raw_grant.get("grant_types_raw") or [], GRANT_TYPES_VOCAB)

    # -- Source language ----------------------------------------------------
    lang = normalise_source_language(raw_grant.get("source_language_raw") or "")

    # -- Confidence scores and aggregate ------------------------------------
    conf_scores = cs
    agg_score   = aggregate_confidence_score(conf_scores)

    # -- Status auto-computation -------------------------------------------
    record_for_status = {
        "current_status_raw":       raw_grant.get("current_status_raw"),
        "confidence_scores":        conf_scores,
        "application_deadline":     app_dl["date"],
        "application_deadline_type":app_dl["type"],
        "grant_opening_date":       open_dt["date"],
    }
    status_result = compute_status(record_for_status)

    # -- Assemble full record -----------------------------------------------
    record = {
        "content_hash":               content_hash,
        "grant_title":                title,
        "funder_name":                funder["canonical_name"],
        "funder_ror_id":              funder.get("ror_id"),
        "source_url":                 source["source_url"],
        "application_portal_url":     raw_grant.get("application_portal_url"),
        "description":                raw_grant.get("description"),
        "application_deadline":       app_dl["date"],
        "application_deadline_raw":   raw_grant.get("application_deadline_raw"),
        "application_deadline_type":  app_dl["type"],
        "deadline_notes":             raw_grant.get("deadline_notes"),
        "eoi_deadline":               eoi_dl["date"],
        "eoi_deadline_raw":           raw_grant.get("eoi_deadline_raw"),
        "eoi_deadline_type":          eoi_dl["type"],
        "grant_opening_date":         open_dt["date"],
        "grant_opening_date_raw":     raw_grant.get("grant_opening_date_raw"),
        "funding_amount_min":         raw_grant.get("funding_amount_min"),
        "funding_amount_max":         raw_grant.get("funding_amount_max"),
        "currency":                   currency,
        "funding_amount_type":        None,
        "current_status":             status_result["current_status"],
        "status_source":              status_result["status_source"],
        "source_language":            lang,
        "ai_focused":                 raw_grant.get("ai_focused"),
        "individuals_not_eligible":   bool(raw_grant.get("individuals_not_eligible")) if raw_grant.get("individuals_not_eligible") is not None else False,
        "organisation_types":         org_types,
        "individual_eligibility":     ind_elig,
        "applicant_base_regions":     app_base["regions"],
        "applicant_base_countries":   app_base["countries"],
        "geographic_focus_regions":   geo_focus["regions"],
        "geographic_focus_countries": geo_focus["countries"],
        "thematic_sectors":           thematic,
        "grant_types":                grant_types,
        "confidence_scores":          conf_scores,
        "aggregate_confidence_score": agg_score,
        "raw_extraction":             raw_grant,
        "requires_review":            determine_review_flag(record_for_status | {"thematic_sectors": thematic, "geographic_focus_regions": geo_focus["regions"], "individual_eligibility": ind_elig, "individuals_not_eligible": record_for_status.get("individuals_not_eligible")}),
        "review_status":              "pending",
        "domain":                     source["domain"],
        "crawl_date":                 source["crawl_date"],
    }
    return record
```

**Acceptance criteria**
- `from stage3.writer import upsert_grant` imports without error.
- Spot checks against a real test database (use pytest fixtures with a test schema):
  - First insert of a record returns `"inserted"`.
  - Second insert with lower confidence returns `"skipped"`.
  - Second insert with higher confidence returns `"updated"`.
  - If existing record has `review_status = "approved"` and new extraction has
    `requires_review = false`: review_status stays `"approved"` after update.
  - If existing record has `review_status = "approved"` and new extraction has
    `requires_review = true`: review_status resets to `"pending"` after update.

---

## PHASE C — PROMPT 4: Review Queue Exporter and Full Normaliser Tests

**What this builds**
The review queue CSV export function and the comprehensive unit test suite for the
entire normalisation layer and writer.

**Read §9 of the design doc.**

**Add to `stage3/writer.py`**

**`export_review_queue(conn, output_dir, run_date)`**

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

Write results to `{output_dir}/review_queue_{run_date}.csv`.
Create `output_dir` if it does not exist.

---

**Unit tests in `tests/test_normaliser.py`**

```python
import pytest
from stage3.normaliser import (
    normalise_grant_title, normalise_funder_name, normalise_deadline,
    normalise_country, normalise_geographic_list, normalise_controlled_vocab,
    compute_content_hash, aggregate_confidence_score,
    determine_review_flag, compute_status
)
```

Required tests (write at least one test per rule/function):

**Grant title normalisation**
- Title case applied correctly.
- Terminal period stripped; terminal `?` preserved.
- Whitespace stripped.

**Deadline normalisation**
- "Rolling applications" → type `"rolling"`.
- "TBC" → type `"tbc"`.
- `None` + confidence `"not_found"` → type `"not_published"`.
- `None` + confidence `"low"` → type `"unextracted"`.
- `"15 March 2027"` → type `"confirmed"`, date `2027-03-15`.
- `"March 15, 2027"` → type `"confirmed"`, date `2027-03-15`.
- `"15/03/2027"` → type `"confirmed"`, date `2027-03-15`.

**Country normalisation**
- `"United Kingdom"` → `"GB"`.
- `"uk"` → `"GB"`.
- `"Britain"` → `"GB"`.
- `"Democratic Republic of the Congo"` → `"CD"`.
- `"DRC"` → `"CD"`.
- Unrecognised string → `"OT"`.

**Content hash stability**
- `compute_content_hash("Wellcome Trust", "Grant A")` is stable across calls.
- `compute_content_hash("WELLCOME TRUST", "grant a")` == `compute_content_hash("Wellcome Trust", "Grant A")`.
- Different funder/title → different hash.
- `compute_content_hash("Funder", "Title 1")` != `compute_content_hash("Funder", "Title 2")`.

**Status auto-computation**
- Rule 1: explicit `"Open"` with high confidence → status `"Open"`, source `"extracted"`.
- Rule 2: `application_deadline_type = "rolling"` → status `"Rolling"`, source `"computed"`.
- Rule 3: future `grant_opening_date` with high confidence → status `"Upcoming"`.
- Rule 3 confidence gate: future `grant_opening_date` with LOW confidence → falls through to rule 4 (does NOT set Upcoming).
- Rule 4a: past confirmed deadline with high confidence → status `"Closed"`.
- Rule 4b: future confirmed deadline with high confidence → status `"Open"`.
- Rule 4 blocked by rule 3: future opening date + future deadline → `"Upcoming"` (not `"Open"`).
- Rule 5 fallback: no confirmed deadline → sentinel.

**Review flag**
- R1 fires: `grant_title` confidence `"not_found"` → `requires_review = True`.
- R6 fixed threshold: `ai_focused` confidence `"medium"` at `threshold="low"` → `requires_review = False`.
- R6 fires: `ai_focused` confidence `"low"` → `requires_review = True`.
- No rules fire: all high confidence, no Others → `requires_review = False`.

**Acceptance criteria**
- `python -m pytest tests/test_normaliser.py -v` exits 0.
- All 25+ tests in `test_normaliser.py` pass.
- `python -m pytest tests/test_writer.py -v` exits 0 (writer CASE guard tests pass).

---

## PHASE D — PROMPT 1: QA Reporter and Status Refresh Job

**What this builds**
The extraction QA report writer and the daily status recalculation job.

**Read §11 of the design doc.**

**Implement `stage3/qa_reporter.py`**

Write `extraction_report_{run_date}.json` to `STAGE3_OUTPUT_DIR` (from env).

The JSON schema must include ALL of these fields (§11):

```python
{
    "report_date": run_date,
    "pages_processed": 0,
    "pages_skipped_unchanged": 0,
    "pages_skipped_content_too_short": 0,   # count of pages below 50 tokens
    "pages_failed": 0,
    "pages_empty_extraction": 0,
    "records_extracted_total": 0,
    "records_inserted_new": 0,
    "records_updated_higher_confidence": 0,
    "records_duplicate_lower_confidence": 0,
    "records_flagged_review": 0,
    "fields_others_frequency": {},          # {"thematic_sectors": 0.12, ...}
    "domains_zero_extraction": [],
    "average_confidence_by_field": {},
    "extraction_cost_estimate_usd": 0.0
}
```

**`records_flagged_review` counter — critical gating rule**

In `run_extraction_cycle`, this counter must be incremented **only** when `upsert_grant`
returns `"inserted"` or `"updated"` — never when it returns `"skipped"`. A lower-confidence
duplicate that is skipped by the upsert WHERE clause is not written to the database and
must not inflate the flagged count:

```python
result = upsert_grant(conn, normalised)
if result == "inserted":
    records_inserted += 1
elif result == "updated":
    records_updated += 1
else:
    records_skipped_dup += 1

# Gate on result — do NOT increment for skipped records
if normalised.get("requires_review") and result != "skipped":
    records_flagged += 1
```

---

Log at WARNING level if:
- `pages_failed / pages_processed > 0.05`
- Any domain appears in `domains_zero_extraction` for two consecutive cycles
- Any field in `fields_others_frequency` exceeds `0.15`

---

**Implement `stage3/status_refresh.py`**

```python
"""
Daily status recalculation job.

Transitions run in strict order within each execution:
  1. Upcoming → Open   (grant_opening_date has passed)
  2. Open    → Closed  (application_deadline has passed)

This ordering is critical: a grant whose opening date AND deadline have both passed
must end up as Closed in a single run. Reversing the order would leave it Open.

Only records with status_source = 'computed' are touched.
All date comparisons use CURRENT_DATE (DATE columns are timezone-independent in
PostgreSQL; UTC is enforced at the Python layer via datetime.now(timezone.utc).date()).
"""
```

**`run_status_refresh(conn)`**

Step 1 — Upcoming → Open:
```sql
UPDATE grants
SET current_status = 'Open',
    updated_at     = NOW()
WHERE status_source = 'computed'
  AND current_status = 'Upcoming'
  AND grant_opening_date <= CURRENT_DATE;
```

Step 2 — Open → Closed:
```sql
UPDATE grants
SET current_status = 'Closed',
    updated_at     = NOW()
WHERE status_source = 'computed'
  AND current_status = 'Open'
  AND application_deadline < CURRENT_DATE;
```

Log counts of affected rows for each step at INFO level.

---

**Unit tests in `tests/test_status_refresh.py`**

Tests must use a real PostgreSQL test database (pytest fixture with test schema).

- `test_open_to_closed`: insert an Open record with `application_deadline = yesterday`.
  After `run_status_refresh`, status is `"Closed"`.
- `test_upcoming_to_open`: insert an Upcoming record with `grant_opening_date = yesterday`.
  After refresh, status is `"Open"`.
- `test_both_passed_lands_closed`: insert an Upcoming record where both
  `grant_opening_date = 10 days ago` and `application_deadline = 5 days ago`.
  After a single `run_status_refresh` call, status is `"Closed"` (not `"Open"`).
  This validates the transition order.
- `test_future_not_touched`: Open record with future deadline — status unchanged.
- `test_extracted_status_not_touched`: record with `status_source = "extracted"` —
  status unchanged regardless of deadline.
- `test_same_day_deadline`: record with `application_deadline = today (UTC)` —
  should remain `"Open"` (deadline is `<`, not `<=`).

**Acceptance criteria**
- `python -m pytest tests/test_status_refresh.py -v` exits 0 (all 6 tests pass).
- The `test_both_passed_lands_closed` test specifically validates the transition order.

---

## PHASE D — PROMPT 2: Review Import, APScheduler Integration, Stage 2 Sentinel

**What this builds**
The CSV review import script, APScheduler integration, and the Stage 2 completion
sentinel polling logic.

**Read §3 (Service trigger), §9 (operator workflow), and §12 Phase D of the design doc.**

**Implement `stage3/review_import.py`**

```python
"""
Review Import — updates review_status in PostgreSQL from an operator-annotated CSV.

Usage: python -m stage3.review_import review_queue_2026-05-23.csv
"""
```

**`import_review_decisions(csv_path, conn)`**

1. Read the CSV produced by `export_review_queue`.
2. For each row where the `review_status` column is `"approved"` or `"rejected"`:
   - `UPDATE grants SET review_status = %s, updated_at = NOW() WHERE id = %s`.
3. Skip rows where `review_status` is blank or unchanged from `"pending"`.
4. Log a summary: `"Imported N decisions (A approved, R rejected)"`.

---

**APScheduler integration**

Add to the existing `crawl_scheduler.py` in Stage 2 (or create a standalone
`stage3/scheduler.py` if Stage 2 does not have an accessible scheduler):

**CRITICAL — psycopg2 connection pattern for all Stage 3 functions.**
`with conn:` in psycopg2 is NOT a connection context manager — it only commits/rolls back.
It does NOT close the connection. Every function that opens a connection must follow
the `try/finally conn.close()` pattern:

```python
# Correct pattern — used throughout Stage 3
conn = get_connection()
try:
    do_work(conn)
    conn.commit()
finally:
    conn.close()

# WRONG — this leaks the connection
with get_connection() as conn:   # ← do NOT use this pattern
    do_work(conn)
```

```python
from apscheduler.schedulers.blocking import BlockingScheduler
from stage3.batch_processor import run_extraction_cycle
from stage3.status_refresh import run_status_refresh
from stage3.db import get_connection

scheduler = BlockingScheduler(timezone="UTC")

# Stage 3 extraction: runs weekly, checks for Stage 2 crawl_complete sentinel
@scheduler.scheduled_job("cron", day_of_week="sun", hour=4)
def stage3_weekly():
    run_extraction_cycle(force=False)

# Daily status refresh
@scheduler.scheduled_job("cron", hour=1)
def daily_status_refresh():
    conn = get_connection()
    try:
        run_status_refresh(conn)
        conn.commit()
    finally:
        conn.close()
```

---

**`check_crawl_complete_sentinel(raw_cache_dir, run_date, *, force=False)`** (if not already implemented in Phase A Prompt 2)

Ensure this function:
- Looks for `{raw_cache_dir}/crawl_complete_{run_date}.json`.
- Polls every 15 minutes for up to 4 hours if not found.
- Logs at WARNING and raises `RuntimeError` if still absent after 4 hours.
- Returns immediately if `force=True`.

**Acceptance criteria**
- `python -m stage3.review_import --help` prints usage without error.
- `from stage3.review_import import import_review_decisions` imports without error.
- Scheduler jobs are defined without import errors.

---

## PHASE D — PROMPT 3: CLI Entry Point and `.env.example`

**What this builds**
The `stage3/__main__.py` command-line interface and the fully populated `.env.example`.

**Read §12 Phase D and §13.1 of the design doc.**

**Implement `stage3/__main__.py`**

```
python -m stage3 --date 2026-05-23        # extract a specific crawl cycle
python -m stage3 --date 2026-05-23 --force  # bypass Stage 2 sentinel check
python -m stage3 --dry-run                # estimate cost without API calls
python -m stage3 --status-refresh        # run the daily status refresh manually
```

**`--dry-run` implementation**:
1. Scan raw_cache for pending pages (same as normal run).
2. For each page, call `prepare_html_page` / `prepare_pdf_page` to get content.
3. Call `count_tokens(content)` for each page.
4. Compute estimated cost: `(total_input_tokens / 1_000_000) * 1.50 * 0.5` (Batch API discount)
   plus an estimated output cost of `total_input_tokens * 0.15 * (9.0 / 1_000_000)`.
5. Check against `STAGE3_MAX_COST` env var if set — log WARNING if estimate exceeds limit.
6. Log the following summary to stdout (no database writes, no LLM calls):

```
DRY RUN SUMMARY
  Pages found:          123
  Pages below minimum:  4
  Estimated tokens:     456,789 input
  Estimation API cost:  $0.0003  ← cost of count_tokens() calls themselves
  Estimated batch cost: $0.34
  Max cost ceiling:     $5.00 (STAGE3_MAX_COST)
  Status:               WITHIN LIMIT
```

---

**`.env.example`** (populate fully)

```
# Google AI API key for Gemini 3.5 Flash
GEMINI_API_KEY=

# PostgreSQL connection string
DATABASE_URL=postgresql://user:password@localhost:5432/grantglobe

# Path to Stage 2 raw_cache directory
RAW_CACHE_DIR=../Stage_2_crawler/raw_cache

# Directory for Stage 3 output files (review CSVs, extraction reports)
# Created automatically if it does not exist
STAGE3_OUTPUT_DIR=stage3_output

# Max pages per Gemini batch (default: 2000)
STAGE3_BATCH_SIZE=2000

# Max retries per failed page (default: 3)
STAGE3_MAX_RETRIES=3

# Confidence threshold for human review flag: 'low' or 'medium' (default: low)
# low:    triggers review when confidence is Low or Not Found
# medium: also triggers review when confidence is Medium (larger queue, for audits)
STAGE3_REVIEW_CONFIDENCE_THRESHOLD=low

# Optional hard cost ceiling in USD. Pipeline aborts before batch submission if
# estimated cost exceeds this value. Leave unset to disable.
STAGE3_MAX_COST=
```

---

**Acceptance criteria**
- `python -m stage3 --help` prints usage for all four flags.
- `python -m stage3 --dry-run` runs without error against a real `raw_cache` dir
  (even an empty one) and outputs the summary block.
- `.env.example` has entries for all 8 environment variables.

---

## PHASE D — PROMPT 4: End-to-End Integration Test

**What this builds**
The fixture `raw_cache` directory and the complete end-to-end integration test that
validates the full pipeline from raw_cache to PostgreSQL to output files.

**Read §12 Phase D acceptance criteria in the design doc.**

**Create test fixtures in `tests/fixtures/`**

Create a `raw_cache/` fixture structure with exactly 10 pages:

| File | Type | Content | Expected outcome |
|---|---|---|---|
| `grant_a_meta.json` | HTML | Single clear grant, all fields high confidence | 1 record inserted, review_status='approved' |
| `grant_b_meta.json` | HTML | Two grants on one page | 2 records inserted |
| `grant_c_meta.json` | PDF | Grant with low-confidence deadline | 1 record inserted, requires_review=true |
| `grant_d_meta.json` | HTML | No grant content (navigation page) | 0 records, extraction_log='completed' |
| `grant_e_meta.json` | HTML | Content below 50 tokens | 0 records, extraction_log='skipped' |
| `grant_f_meta.json` | HTML | Duplicate of grant_a (same funder+title) with lower confidence | 0 net new records (skipped by upsert) |
| `grant_g_meta.json` | HTML | Duplicate of grant_a with higher confidence | grant_a updated, not duplicated |
| `grant_h_meta.json` | HTML | Grant with rolling deadline | 1 record, current_status='Rolling' |
| `grant_i_meta.json` | HTML | Grant with past confirmed deadline | 1 record, current_status='Closed' |
| `grant_j_meta.json` | HTML | Grant with future confirmed deadline | 1 record, current_status='Open' |

Each `.meta.json` must have `"changed": true` and `"crawl_date": "2026-05-23"`.

Corresponding `.html.gz` or `pdf_text` in `.meta.json` must contain realistic grant
page text that the LLM would extract correctly.

Also create `raw_cache/crawl_complete_2026-05-23.json` to satisfy the sentinel check.

---

**`tests/conftest.py` — psycopg2 connection management rules**

Two psycopg2 behaviours that must be followed precisely throughout all test fixtures:

1. **`with conn:` does NOT close connections.** psycopg2's context manager commits
   on clean exit and rolls back on exception — it does not call `conn.close()`.
   All fixtures that open a connection must close it explicitly with `try/finally`.

2. **Teardown `autocommit` change requires a clean transaction state.**
   The session-scoped `db_conn` fixture teardown must call `conn.rollback()` before
   setting `conn.autocommit = True`, otherwise psycopg2 raises
   `ProgrammingError: set_session cannot be used inside a transaction`:

```python
# Correct teardown pattern in db_conn fixture:
yield conn

conn.rollback()      # clear any open transaction first
conn.autocommit = True
with conn.cursor() as cur:
    cur.execute(f"DROP SCHEMA IF EXISTS {_TEST_SCHEMA} CASCADE")
conn.close()
```

---

**`tests/test_end_to_end.py`**

```python
"""
End-to-end integration test for Stage 3.
Runs the full pipeline against the fixture raw_cache.
Requires a real PostgreSQL test database (use TEST_DATABASE_URL env var).
Uses MOCKED Gemini API responses matching the fixture pages.
"""
```

The test must:
1. Mock the Gemini Batch API to return pre-written JSON responses matching each fixture page.
2. Run the full `run_extraction_cycle` against the fixture `raw_cache`.
3. Assert:
   - `grants` table contains exactly 7 unique records (grant_a through grant_j minus the
     duplicates and empty pages).
   - Grant_a has `review_status = 'approved'` (requires_review=false).
   - Grant_c has `requires_review = true` and `review_status = 'pending'`.
   - Grant_h has `current_status = 'Rolling'`.
   - Grant_i has `current_status = 'Closed'`.
   - Grant_j has `current_status = 'Open'`.
   - Grant_f did not create a duplicate of grant_a (content_hash collision resolved correctly).
   - Grant_g updated grant_a's record (higher confidence replaces lower).
   - `extraction_log` has 10 rows: 8 'completed', 1 'skipped' (grant_e), 0 'failed'.
4. Assert `stage3_output/review_queue_2026-05-23.csv` exists and contains grant_c.
5. Assert `stage3_output/extraction_report_2026-05-23.json` exists and
   `pages_skipped_content_too_short == 1`.

---

**Acceptance criteria**
- `python -m pytest tests/test_end_to_end.py -v` exits 0.
- `python -m pytest tests/ -v` exits 0 — all phases' tests pass together.
- The test suite contains at least 50 distinct test functions across all test files.

---

*These prompts are based on stage3_extraction_design.md v1.5.*
*Paste each prompt in order. Complete acceptance criteria before proceeding to the next.*
*Phase 0 must be completed before Phase A. Phase A before Phase B. And so on.*
