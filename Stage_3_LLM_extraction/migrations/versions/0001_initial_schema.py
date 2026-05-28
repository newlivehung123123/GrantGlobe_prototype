"""Initial schema: grants and extraction_log tables with all indexes.

Revision ID: 0001
Revises:
Create Date: 2026-05-23 00:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Extension
    # ------------------------------------------------------------------
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    # ------------------------------------------------------------------
    # grants table
    # ------------------------------------------------------------------
    op.execute("""
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
        )
    """)

    # ------------------------------------------------------------------
    # extraction_log table
    # ------------------------------------------------------------------
    op.execute("""
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
        )
    """)

    # ------------------------------------------------------------------
    # Indexes on grants
    # ------------------------------------------------------------------

    # Deduplication
    op.execute("""
        CREATE UNIQUE INDEX idx_grants_content_hash
            ON grants (content_hash)
    """)

    # GIN indexes for array containment queries
    op.execute("""
        CREATE INDEX idx_grants_geographic_focus_regions
            ON grants USING GIN (geographic_focus_regions)
    """)
    op.execute("""
        CREATE INDEX idx_grants_geographic_focus_countries
            ON grants USING GIN (geographic_focus_countries)
    """)
    op.execute("""
        CREATE INDEX idx_grants_applicant_base_regions
            ON grants USING GIN (applicant_base_regions)
    """)
    op.execute("""
        CREATE INDEX idx_grants_applicant_base_countries
            ON grants USING GIN (applicant_base_countries)
    """)
    op.execute("""
        CREATE INDEX idx_grants_organisation_types
            ON grants USING GIN (organisation_types)
    """)
    op.execute("""
        CREATE INDEX idx_grants_individual_eligibility
            ON grants USING GIN (individual_eligibility)
    """)
    op.execute("""
        CREATE INDEX idx_grants_thematic_sectors
            ON grants USING GIN (thematic_sectors)
    """)
    op.execute("""
        CREATE INDEX idx_grants_grant_types
            ON grants USING GIN (grant_types)
    """)

    # Status and date filtering
    op.execute("""
        CREATE INDEX idx_grants_current_status
            ON grants (current_status)
    """)
    op.execute("""
        CREATE INDEX idx_grants_application_deadline
            ON grants (application_deadline)
    """)
    op.execute("""
        CREATE INDEX idx_grants_ai_focused
            ON grants (ai_focused)
    """)
    op.execute("""
        CREATE INDEX idx_grants_domain
            ON grants (domain)
    """)

    # Review status indexes
    # Full index for Stage 4 reader query (WHERE review_status = 'approved')
    op.execute("""
        CREATE INDEX idx_grants_review_status
            ON grants (review_status)
    """)
    # Partial index for review queue export (WHERE requires_review = true)
    op.execute("""
        CREATE INDEX idx_grants_review_queue
            ON grants (review_status, created_at DESC)
            WHERE requires_review = true
    """)
    # Composite index for Stage 4 combined filter
    op.execute("""
        CREATE INDEX idx_grants_stage4_filter
            ON grants (review_status, current_status, application_deadline)
    """)

    # ------------------------------------------------------------------
    # Indexes on extraction_log
    # ------------------------------------------------------------------
    op.execute("""
        CREATE INDEX idx_extraction_log_status
            ON extraction_log (status)
    """)
    op.execute("""
        CREATE INDEX idx_extraction_log_domain
            ON extraction_log (domain, crawl_date)
    """)


def downgrade() -> None:
    # Drop indexes on extraction_log
    op.execute("DROP INDEX IF EXISTS idx_extraction_log_domain")
    op.execute("DROP INDEX IF EXISTS idx_extraction_log_status")

    # Drop indexes on grants
    op.execute("DROP INDEX IF EXISTS idx_grants_stage4_filter")
    op.execute("DROP INDEX IF EXISTS idx_grants_review_queue")
    op.execute("DROP INDEX IF EXISTS idx_grants_review_status")
    op.execute("DROP INDEX IF EXISTS idx_grants_domain")
    op.execute("DROP INDEX IF EXISTS idx_grants_ai_focused")
    op.execute("DROP INDEX IF EXISTS idx_grants_application_deadline")
    op.execute("DROP INDEX IF EXISTS idx_grants_current_status")
    op.execute("DROP INDEX IF EXISTS idx_grants_grant_types")
    op.execute("DROP INDEX IF EXISTS idx_grants_thematic_sectors")
    op.execute("DROP INDEX IF EXISTS idx_grants_individual_eligibility")
    op.execute("DROP INDEX IF EXISTS idx_grants_organisation_types")
    op.execute("DROP INDEX IF EXISTS idx_grants_applicant_base_countries")
    op.execute("DROP INDEX IF EXISTS idx_grants_applicant_base_regions")
    op.execute("DROP INDEX IF EXISTS idx_grants_geographic_focus_countries")
    op.execute("DROP INDEX IF EXISTS idx_grants_geographic_focus_regions")
    op.execute("DROP INDEX IF EXISTS idx_grants_content_hash")

    # Drop tables
    op.execute("DROP TABLE IF EXISTS extraction_log")
    op.execute("DROP TABLE IF EXISTS grants")
