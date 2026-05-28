"""
Tests for stage3/status_refresh.py — Phase D Prompt 1.

All tests require a live PostgreSQL connection and are automatically skipped
when DATABASE_URL is not set.

The critical invariant under test is the mandatory transition order:
    1. Upcoming → Open   (grant_opening_date ≤ today)
    2. Open    → Closed  (application_deadline < today)

A grant whose opening date AND deadline have both passed must land in 'Closed'
after a single run_status_refresh call.
"""

import datetime
import pytest
from psycopg2.extras import RealDictCursor

from tests.conftest import needs_db, make_record
from stage3.writer import upsert_grant
from stage3.status_refresh import run_status_refresh

today = datetime.date.today()
yesterday = today - datetime.timedelta(days=1)
ten_days_ago = today - datetime.timedelta(days=10)
five_days_ago = today - datetime.timedelta(days=5)
tomorrow = today + datetime.timedelta(days=1)
future = today + datetime.timedelta(days=60)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _get_status(conn, content_hash: str) -> str | None:
    """Fetch current_status for a row by content_hash."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT current_status FROM grants WHERE content_hash = %s",
            (content_hash,),
        )
        row = cur.fetchone()
    return row["current_status"] if row else None


def _insert(conn, hash_suffix: str, **overrides) -> str:
    """Insert a record with a unique content_hash and return the hash."""
    content_hash = (hash_suffix * 64)[:64]
    record = make_record(content_hash=content_hash, **overrides)
    upsert_grant(conn, record)
    return content_hash


# ---------------------------------------------------------------------------
# Test 1: Open → Closed when deadline has passed
# ---------------------------------------------------------------------------

@needs_db
def test_open_to_closed(grants_conn):
    """An Open record with application_deadline = yesterday must become Closed."""
    h = _insert(
        grants_conn, "a",
        current_status="Open",
        status_source="computed",
        application_deadline=yesterday,
        application_deadline_type="confirmed",
    )

    result = run_status_refresh(grants_conn)

    assert _get_status(grants_conn, h) == "Closed"
    assert result["open_to_closed"] >= 1


# ---------------------------------------------------------------------------
# Test 2: Upcoming → Open when opening date has passed
# ---------------------------------------------------------------------------

@needs_db
def test_upcoming_to_open(grants_conn):
    """An Upcoming record with grant_opening_date = yesterday must become Open."""
    h = _insert(
        grants_conn, "b",
        current_status="Upcoming",
        status_source="computed",
        grant_opening_date=yesterday,
        # Keep deadline in the future so it won't immediately flip to Closed
        application_deadline=future,
        application_deadline_type="confirmed",
    )

    result = run_status_refresh(grants_conn)

    assert _get_status(grants_conn, h) == "Open"
    assert result["upcoming_to_open"] >= 1


# ---------------------------------------------------------------------------
# Test 3: Both dates passed → must land on Closed in a single run
# ---------------------------------------------------------------------------

@needs_db
def test_both_passed_lands_closed(grants_conn):
    """Critical ordering test: if grant_opening_date = 10 days ago AND
    application_deadline = 5 days ago, a single run_status_refresh must
    produce 'Closed', not 'Open'.

    Correct order (passes): Upcoming→Open first, then Open→Closed picks it up.
    Wrong order (would fail): Open→Closed runs first (nothing to close yet),
    then Upcoming→Open produces 'Open' with no second pass.
    """
    h = _insert(
        grants_conn, "c",
        current_status="Upcoming",
        status_source="computed",
        grant_opening_date=ten_days_ago,
        application_deadline=five_days_ago,
        application_deadline_type="confirmed",
    )

    result = run_status_refresh(grants_conn)

    final_status = _get_status(grants_conn, h)
    assert final_status == "Closed", (
        f"Expected 'Closed' but got {final_status!r}. "
        "This indicates the transition order is wrong: "
        "Open→Closed must run AFTER Upcoming→Open."
    )
    # Both transitions must have fired in this single call
    assert result["upcoming_to_open"] >= 1
    assert result["open_to_closed"] >= 1


# ---------------------------------------------------------------------------
# Test 4: Future deadline — Open record must not be touched
# ---------------------------------------------------------------------------

@needs_db
def test_future_not_touched(grants_conn):
    """An Open record with a future application_deadline must remain Open."""
    h = _insert(
        grants_conn, "d",
        current_status="Open",
        status_source="computed",
        application_deadline=future,
        application_deadline_type="confirmed",
    )

    run_status_refresh(grants_conn)

    assert _get_status(grants_conn, h) == "Open"


# ---------------------------------------------------------------------------
# Test 5: status_source = "extracted" — must not be touched
# ---------------------------------------------------------------------------

@needs_db
def test_extracted_status_not_touched(grants_conn):
    """A record with status_source = 'extracted' must not be modified even
    if its deadline has passed — only 'computed' records are eligible."""
    h = _insert(
        grants_conn, "e",
        current_status="Open",
        status_source="extracted",   # ← explicitly extracted, not computed
        application_deadline=yesterday,
        application_deadline_type="confirmed",
    )

    run_status_refresh(grants_conn)

    # The job must not touch this record
    assert _get_status(grants_conn, h) == "Open"


# ---------------------------------------------------------------------------
# Test 6: Deadline = today — must remain Open (< not <=)
# ---------------------------------------------------------------------------

@needs_db
def test_same_day_deadline(grants_conn):
    """The Open→Closed transition uses strict less-than (<), so a record
    whose application_deadline is exactly today must remain Open."""
    h = _insert(
        grants_conn, "f",
        current_status="Open",
        status_source="computed",
        application_deadline=today,
        application_deadline_type="confirmed",
    )

    run_status_refresh(grants_conn)

    assert _get_status(grants_conn, h) == "Open", (
        "A deadline of exactly today should not close the record — "
        "the transition fires on application_deadline < CURRENT_DATE (strict less-than)."
    )
