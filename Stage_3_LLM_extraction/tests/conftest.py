"""
Shared pytest fixtures for Stage 3 tests.

Database fixtures create an isolated schema (``stage3_test``) at the start of
the test session and drop it on teardown.  Tests are skipped automatically when
``DATABASE_URL`` is not set in the environment.
"""

import os
import datetime
import pytest
import psycopg2

# ---------------------------------------------------------------------------
# Skip marker — used by any test that needs a live PostgreSQL connection.
# ---------------------------------------------------------------------------

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set — skipping database tests",
)

# ---------------------------------------------------------------------------
# Isolated test schema (session-scoped)
# ---------------------------------------------------------------------------

_TEST_SCHEMA = "stage3_test"

# Minimal CREATE TABLE that matches the migration column list exactly.
# Using TEXT[] instead of CHAR(2)[] for geography arrays to keep the fixture
# portable across PostgreSQL configurations without the pgcrypto extension.
_CREATE_GRANTS_TABLE = f"""
CREATE TABLE IF NOT EXISTS {_TEST_SCHEMA}.grants (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content_hash                CHAR(64) UNIQUE NOT NULL,
    grant_title                 TEXT NOT NULL,
    funder_name                 TEXT NOT NULL,
    funder_ror_id               TEXT,
    source_url                  TEXT NOT NULL,
    application_portal_url      TEXT,
    description                 TEXT,
    application_deadline        DATE,
    application_deadline_raw    TEXT,
    application_deadline_type   TEXT,
    deadline_notes              TEXT,
    eoi_deadline                DATE,
    eoi_deadline_raw            TEXT,
    eoi_deadline_type           TEXT,
    grant_opening_date          DATE,
    grant_opening_date_raw      TEXT,
    funding_amount_min          NUMERIC(15,2),
    funding_amount_max          NUMERIC(15,2),
    currency                    CHAR(3),
    funding_amount_type         TEXT,
    current_status              TEXT,
    status_source               TEXT,
    source_language             CHAR(10),
    ai_focused                  BOOLEAN,
    individuals_not_eligible    BOOLEAN NOT NULL DEFAULT false,
    organisation_types          TEXT[],
    individual_eligibility      TEXT[],
    applicant_base_regions      TEXT[],
    applicant_base_countries    TEXT[],
    geographic_focus_regions    TEXT[],
    geographic_focus_countries  TEXT[],
    thematic_sectors            TEXT[],
    grant_types                 TEXT[],
    confidence_scores           JSONB NOT NULL DEFAULT '{{}}',
    aggregate_confidence_score  INTEGER NOT NULL DEFAULT 0,
    raw_extraction              JSONB NOT NULL DEFAULT '{{}}',
    requires_review             BOOLEAN NOT NULL DEFAULT false,
    review_status               TEXT NOT NULL DEFAULT 'pending',
    domain                      TEXT NOT NULL,
    crawl_date                  DATE NOT NULL,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

_CREATE_EXTRACTION_LOG_TABLE = f"""
CREATE TABLE IF NOT EXISTS {_TEST_SCHEMA}.extraction_log (
    id              SERIAL PRIMARY KEY,
    url_hash        TEXT NOT NULL,
    domain          TEXT NOT NULL,
    crawl_date      DATE NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    records_extracted INTEGER,
    error_message   TEXT,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    processed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (url_hash, crawl_date)
)
"""

# Make gen_random_uuid() available without pgcrypto by falling back to the
# uuid-ossp extension, which ships with most standard PostgreSQL installs.
_ENABLE_UUID = "CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\""
_UUID_DEFAULT_WORKAROUND = f"""
DO $$
BEGIN
    ALTER TABLE {_TEST_SCHEMA}.grants
        ALTER COLUMN id SET DEFAULT uuid_generate_v4();
EXCEPTION WHEN others THEN
    NULL;  -- pgcrypto already provides gen_random_uuid(); ignore the error
END $$
"""


@pytest.fixture(scope="session")
def db_conn():
    """Session-scoped raw psycopg2 connection to the test schema.

    Creates ``stage3_test`` schema and ``grants`` table once per session,
    drops both on teardown.  Skipped when ``DATABASE_URL`` is not set.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")

    conn = psycopg2.connect(url)
    conn.autocommit = True

    with conn.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {_TEST_SCHEMA} CASCADE")
        cur.execute(f"CREATE SCHEMA {_TEST_SCHEMA}")
        # Try to enable uuid-ossp so gen_random_uuid / uuid_generate_v4 works.
        try:
            cur.execute(_ENABLE_UUID)
        except Exception:
            conn.rollback()
        cur.execute(_CREATE_GRANTS_TABLE)
        cur.execute(_CREATE_EXTRACTION_LOG_TABLE)
        # Patch DEFAULT for id if gen_random_uuid isn't available.
        try:
            cur.execute(_UUID_DEFAULT_WORKAROUND)
        except Exception:
            pass

    conn.autocommit = False
    yield conn

    conn.rollback()  # clear any open transaction before changing autocommit
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {_TEST_SCHEMA} CASCADE")
    conn.close()


@pytest.fixture
def grants_conn(db_conn):
    """Function-scoped fixture: truncates ``grants`` before each test and sets
    the search path so the writer targets the test schema transparently.

    The writer's SQL references the bare table name ``grants``; setting
    ``search_path`` redirects it to ``stage3_test.grants``.
    """
    with db_conn.cursor() as cur:
        cur.execute(f"SET search_path TO {_TEST_SCHEMA}, public")
        cur.execute(f"TRUNCATE TABLE {_TEST_SCHEMA}.grants RESTART IDENTITY CASCADE")
        cur.execute(f"TRUNCATE TABLE {_TEST_SCHEMA}.extraction_log RESTART IDENTITY CASCADE")
    db_conn.commit()
    yield db_conn


# ---------------------------------------------------------------------------
# Shared minimal record factory
# ---------------------------------------------------------------------------

def _make_patched_get_connection(schema: str):
    """Return a ``get_connection`` replacement that sets search_path to *schema*."""
    import psycopg2 as _psycopg2

    def _get_connection():
        conn = _psycopg2.connect(os.environ["DATABASE_URL"])
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")
        return conn

    return _get_connection


def make_record(**overrides) -> dict:
    """Return a minimal, fully-valid normalised grant record."""
    base: dict = {
        "content_hash": "a" * 64,
        "grant_title": "Test Innovation Fund",
        "funder_name": "Test Foundation",
        "funder_ror_id": None,
        "source_url": "https://example.com/grant",
        "application_portal_url": None,
        "description": "A test grant.",
        "application_deadline": datetime.date(2027, 6, 30),
        "application_deadline_raw": "30 June 2027",
        "application_deadline_type": "confirmed",
        "deadline_notes": None,
        "eoi_deadline": None,
        "eoi_deadline_raw": None,
        "eoi_deadline_type": None,
        "grant_opening_date": None,
        "grant_opening_date_raw": None,
        "funding_amount_min": None,
        "funding_amount_max": None,
        "currency": None,
        "funding_amount_type": None,
        "current_status": "Open",
        "status_source": "computed",
        "source_language": "en",
        "ai_focused": False,
        "individuals_not_eligible": False,
        "organisation_types": ["NGO"],
        "individual_eligibility": [],
        "applicant_base_regions": [],
        "applicant_base_countries": [],
        "geographic_focus_regions": ["Sub-Saharan Africa"],
        "geographic_focus_countries": ["KE"],
        "thematic_sectors": ["Health and Medical Research"],
        "grant_types": ["Research Grant"],
        "confidence_scores": {
            "grant_title": "high",
            "funder_name": "high",
            "application_deadline": "high",
            "eoi_deadline": "not_found",
            "grant_opening_date": "not_found",
            "funding_amount": "not_found",
            "current_status": "not_found",
            "geographic_focus": "high",
            "thematic_sectors": "medium",
            "individual_eligibility": "not_found",
            "organisation_types": "medium",
            "applicant_base": "high",
            "ai_focused": "high",
        },
        "aggregate_confidence_score": 20,
        "raw_extraction": {},
        "requires_review": False,
        "review_status": "pending",
        "domain": "example.com",
        "crawl_date": datetime.date(2026, 5, 24),
    }
    base.update(overrides)
    return base
