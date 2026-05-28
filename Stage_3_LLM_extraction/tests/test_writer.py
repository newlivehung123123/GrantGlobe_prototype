"""
Tests for stage3/writer.py — upsert_grant acceptance criteria (Phase C Prompt 3).

All tests in this module require a live PostgreSQL connection.  They are
automatically skipped when ``DATABASE_URL`` is not set.
"""

import pytest

from tests.conftest import needs_db, make_record
from stage3.writer import upsert_grant


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _fetch_one(conn, content_hash: str) -> dict | None:
    """Fetch a single grants row by content_hash, or None if absent."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM grants WHERE content_hash = %s", (content_hash,)
        )
        row = cur.fetchone()
    if row is None:
        return None
    col_names = [desc[0] for desc in cur.description] if cur.description else []
    # cursor.description is available after execute; re-query for column names.
    with conn.cursor() as cur2:
        cur2.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'grants' ORDER BY ordinal_position"
        )
        col_names = [r[0] for r in cur2.fetchall()]
    # Re-fetch as dict using psycopg2 RealDictCursor for clarity.
    from psycopg2.extras import RealDictCursor
    with conn.cursor(cursor_factory=RealDictCursor) as cur3:
        cur3.execute(
            "SELECT * FROM grants WHERE content_hash = %s", (content_hash,)
        )
        return dict(cur3.fetchone())


# ---------------------------------------------------------------------------
# Acceptance criterion 1 — first insert returns "inserted"
# ---------------------------------------------------------------------------

@needs_db
def test_first_insert_returns_inserted(grants_conn):
    """First upsert of a record must return 'inserted'."""
    record = make_record()
    result = upsert_grant(grants_conn, record)
    assert result == "inserted", f"Expected 'inserted', got {result!r}"


# ---------------------------------------------------------------------------
# Acceptance criterion 2 — lower confidence returns "skipped"
# ---------------------------------------------------------------------------

@needs_db
def test_lower_confidence_returns_skipped(grants_conn):
    """Re-insertion with lower aggregate_confidence_score must return 'skipped'."""
    high_record = make_record(aggregate_confidence_score=20)
    assert upsert_grant(grants_conn, high_record) == "inserted"

    low_record = make_record(
        grant_title="Different Title",  # content would change but hash is same
        aggregate_confidence_score=10,  # lower → WHERE clause fails
    )
    result = upsert_grant(grants_conn, low_record)
    assert result == "skipped", f"Expected 'skipped', got {result!r}"


# ---------------------------------------------------------------------------
# Acceptance criterion 3 — higher confidence returns "updated"
# ---------------------------------------------------------------------------

@needs_db
def test_higher_confidence_returns_updated(grants_conn):
    """Re-insertion with higher aggregate_confidence_score must return 'updated'."""
    low_record = make_record(aggregate_confidence_score=10)
    assert upsert_grant(grants_conn, low_record) == "inserted"

    high_record = make_record(
        grant_title="Updated Title",
        aggregate_confidence_score=30,  # higher → WHERE clause passes
    )
    result = upsert_grant(grants_conn, high_record)
    assert result == "updated", f"Expected 'updated', got {result!r}"

    # Confirm the title was actually updated in the database.
    stored = _fetch_one(grants_conn, "a" * 64)
    assert stored is not None
    assert stored["grant_title"] == "Updated Title"


# ---------------------------------------------------------------------------
# Acceptance criterion 4 — approved review_status preserved when requires_review=false
# ---------------------------------------------------------------------------

@needs_db
def test_review_status_preserved_when_no_new_flag(grants_conn):
    """When an existing record is 'approved' and the new extraction does not
    raise a review flag (requires_review=false), review_status must stay
    'approved' after the update."""
    # Insert initial record and manually set review_status to 'approved'.
    initial = make_record(aggregate_confidence_score=10, review_status="pending")
    assert upsert_grant(grants_conn, initial) == "inserted"

    with grants_conn.cursor() as cur:
        cur.execute(
            "UPDATE grants SET review_status = 'approved' WHERE content_hash = %s",
            ("a" * 64,),
        )
    grants_conn.commit()

    # Re-extract with higher confidence and requires_review=false.
    update = make_record(
        aggregate_confidence_score=25,
        requires_review=False,
        review_status="pending",  # new extraction sets pending, but CASE guard should override
    )
    result = upsert_grant(grants_conn, update)
    assert result == "updated"

    stored = _fetch_one(grants_conn, "a" * 64)
    assert stored is not None
    assert stored["review_status"] == "approved", (
        f"review_status should stay 'approved' but got {stored['review_status']!r}"
    )


# ---------------------------------------------------------------------------
# Acceptance criterion 5 — approved review_status reset when new extraction flags
# ---------------------------------------------------------------------------

@needs_db
def test_review_status_reset_when_new_flag_raised(grants_conn):
    """When an existing record is 'approved' but the new extraction raises a
    review flag (requires_review=true), review_status must revert to 'pending'."""
    # Insert initial record and manually set review_status to 'approved'.
    initial = make_record(aggregate_confidence_score=10, review_status="pending")
    assert upsert_grant(grants_conn, initial) == "inserted"

    with grants_conn.cursor() as cur:
        cur.execute(
            "UPDATE grants SET review_status = 'approved' WHERE content_hash = %s",
            ("a" * 64,),
        )
    grants_conn.commit()

    # Re-extract with higher confidence AND requires_review=true.
    update = make_record(
        aggregate_confidence_score=25,
        requires_review=True,
        review_status="pending",
    )
    result = upsert_grant(grants_conn, update)
    assert result == "updated"

    stored = _fetch_one(grants_conn, "a" * 64)
    assert stored is not None
    assert stored["review_status"] == "pending", (
        f"review_status should reset to 'pending' but got {stored['review_status']!r}"
    )
