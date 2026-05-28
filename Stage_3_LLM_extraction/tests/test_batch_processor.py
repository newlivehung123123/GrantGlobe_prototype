"""
Unit tests for stage3.batch_processor.

All tests run without a live PostgreSQL database or Gemini API key.
The database layer (get_cursor / conn) is replaced by lightweight mock objects
that:
  - capture every SQL statement executed
  - expose a controllable ``rowcount`` attribute
  - simulate the context-manager protocol of psycopg2 cursors

Design note on test_claim_rows_skip_locked
------------------------------------------
PostgreSQL's FOR UPDATE SKIP LOCKED guarantee is a database-engine feature;
we cannot reproduce true lock contention in a unit test.  Instead we verify:
  1. The SELECT SQL emitted by claim_pending_rows contains the exact phrase
     ``FOR UPDATE SKIP LOCKED``, which is the precondition for the guarantee.
  2. Two simulated workers receive disjoint row sets — the outcome that
     SKIP LOCKED produces in production.  Each worker's mock cursor returns
     different rows, exactly as SKIP LOCKED would arrange in a real database
     (the second worker skips rows already locked by the first).
"""

import gzip
import json
import threading
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from stage3.batch_processor import (
    claim_pending_rows,
    prepare_html_page,
    prepare_pdf_page,
    reset_stale_processing_rows,
    scan_for_pending_pages,
    truncate_to_token_budget,
)

# Directory holding static fixture files created by the fixture generation script.
FIXTURE_DIR = Path(__file__).parent / "fixtures"
# The raw_cache root used by the HTML fixture meta files.
FIXTURE_RAW_CACHE = FIXTURE_DIR / "raw_cache"


# ---------------------------------------------------------------------------
# Mock infrastructure
# ---------------------------------------------------------------------------

class _FakeCursor:
    """Minimal stand-in for a psycopg2 cursor.

    Captures every (sql, params) pair passed to execute() and exposes a
    controllable rowcount.  fetchall() returns a pre-set list of rows.
    """

    def __init__(self, *, fetchall_rows: list[dict] | None = None, rowcount: int = 1):
        self._fetchall_rows: list[dict] = fetchall_rows or []
        self.rowcount: int = rowcount
        self.executions: list[tuple[str, Any]] = []  # recorded (sql, params) pairs

    def execute(self, sql: str, params=None) -> None:
        self.executions.append((sql, params))

    def fetchall(self) -> list[dict]:
        return list(self._fetchall_rows)

    # Context-manager support (psycopg2 cursors are context managers)
    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


def _make_conn(cursor: "_FakeCursor") -> MagicMock:
    """Build a mock psycopg2 connection wired to the given fake cursor.

    get_cursor(conn) calls ``conn.cursor(cursor_factory=…)`` as a context
    manager, so we rig the mock accordingly.
    """
    conn = MagicMock()
    conn.cursor.return_value = cursor   # cursor() returns the fake cursor
    # The fake cursor already supports __enter__/__exit__, so MagicMock's
    # default context-manager protocol will call cursor.__enter__() → cursor.
    return conn


# ---------------------------------------------------------------------------
# test_reset_stale_rows
# ---------------------------------------------------------------------------

def test_reset_stale_rows():
    """reset_stale_processing_rows emits the correct UPDATE and returns rowcount.

    The spec says stale rows are those in 'processing' with processed_at older
    than 8 hours.  We verify:
      - the emitted SQL targets status='processing' and the 8-hour threshold
      - the sentinel message 'reset from stale processing' is embedded in the SQL
      - the function returns the cursor's rowcount (simulating 2 rows reset)
    """
    cursor = _FakeCursor(rowcount=2)
    conn = _make_conn(cursor)

    result = reset_stale_processing_rows(conn)

    assert result == 2, "Must return the rowcount reported by the cursor"
    assert len(cursor.executions) == 1, "Exactly one SQL statement expected"

    sql, _params = cursor.executions[0]

    assert "8 hours" in sql, "SQL must reference the 8-hour staleness threshold"
    assert "reset from stale processing" in sql, (
        "SQL must set the 'reset from stale processing' error_message"
    )
    assert "'pending'" in sql, "SQL must set status back to 'pending'"
    assert "'processing'" in sql, "SQL must filter on status='processing'"

    # Ensure the database connection is committed (get_cursor commits on exit)
    conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# test_scan_inserts_changed_pages
# ---------------------------------------------------------------------------

def _write_meta(
    base: Path,
    *,
    url_hash: str,
    domain: str,
    crawl_date: str,
    changed: bool,
) -> None:
    """Write a synthetic .meta.json file in the expected raw_cache layout:
    ``{base}/{domain}/{crawl_date}/pages/{url_hash}.meta.json``
    """
    target = base / domain / crawl_date / "pages" / f"{url_hash}.meta.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "url_hash": url_hash,
                "domain": domain,
                "crawl_date": crawl_date,
                "changed": changed,
                "is_pdf": False,
            }
        ),
        encoding="utf-8",
    )


def test_scan_inserts_changed_pages(tmp_path):
    """scan_for_pending_pages inserts rows only for files where changed=true.

    Setup: three .meta.json files — two with changed=true, one with changed=false.
    Expected: exactly two INSERT statements are issued; return value is 2.
    """
    RUN_DATE = "2026-05-23"

    _write_meta(tmp_path, url_hash="aaaa000000000001", domain="example.com",
                crawl_date=RUN_DATE, changed=True)
    _write_meta(tmp_path, url_hash="bbbb000000000002", domain="grants.org",
                crawl_date=RUN_DATE, changed=True)
    _write_meta(tmp_path, url_hash="cccc000000000003", domain="unchanged.org",
                crawl_date=RUN_DATE, changed=False)

    cursor = _FakeCursor(rowcount=1)   # each INSERT succeeds (rowcount=1)
    conn = _make_conn(cursor)

    result = scan_for_pending_pages(conn, tmp_path, RUN_DATE)

    assert result == 2, "Must return 2 (only the two changed pages)"

    insert_sqls = [
        sql for sql, _ in cursor.executions
        if "INSERT" in sql.upper()
    ]
    assert len(insert_sqls) == 2, (
        f"Expected 2 INSERT statements, got {len(insert_sqls)}: {insert_sqls}"
    )

    # Both inserts reference the correct table
    for sql in insert_sqls:
        assert "extraction_log" in sql

    # The unchanged page's url_hash must NOT appear in any INSERT
    insert_params = [params for _, params in cursor.executions if params]
    inserted_hashes = {p["url_hash"] for p in insert_params if "url_hash" in p}
    assert "cccc000000000003" not in inserted_hashes, (
        "unchanged page must not be inserted"
    )
    assert "aaaa000000000001" in inserted_hashes
    assert "bbbb000000000002" in inserted_hashes


def test_scan_skips_wrong_date(tmp_path):
    """scan_for_pending_pages skips files whose crawl_date does not match run_date."""
    _write_meta(tmp_path, url_hash="dddd000000000004", domain="other.com",
                crawl_date="2026-05-20", changed=True)  # different date
    _write_meta(tmp_path, url_hash="eeee000000000005", domain="match.com",
                crawl_date="2026-05-23", changed=True)

    cursor = _FakeCursor(rowcount=1)
    conn = _make_conn(cursor)

    result = scan_for_pending_pages(conn, tmp_path, "2026-05-23")

    assert result == 1, "Only the file with the matching date should be inserted"


# ---------------------------------------------------------------------------
# test_claim_rows_skip_locked
# ---------------------------------------------------------------------------

def test_claim_rows_skip_locked():
    """Two concurrent workers calling claim_pending_rows must not share a row.

    Worker A's cursor returns row id=1; Worker B's cursor returns row id=2,
    simulating the outcome PostgreSQL's FOR UPDATE SKIP LOCKED produces
    (the second worker automatically skips the row already locked by the first).

    Assertions:
      - claimed sets are disjoint (no shared rows)
      - every SELECT emitted contains 'FOR UPDATE SKIP LOCKED'
      - claimed rows are immediately updated to 'processing'
    """
    row_a = {
        "id": 1,
        "url_hash": "aaaa000000000001",
        "domain": "alpha.com",
        "crawl_date": date(2026, 5, 23),
    }
    row_b = {
        "id": 2,
        "url_hash": "bbbb000000000002",
        "domain": "beta.com",
        "crawl_date": date(2026, 5, 23),
    }

    cursor_a = _FakeCursor(fetchall_rows=[row_a], rowcount=1)
    cursor_b = _FakeCursor(fetchall_rows=[row_b], rowcount=1)

    conn_a = _make_conn(cursor_a)
    conn_b = _make_conn(cursor_b)

    results: dict[str, list] = {}

    def _worker(name: str, conn, cursor) -> None:
        claimed = claim_pending_rows(conn)
        results[name] = claimed

    # Run both workers in separate threads to demonstrate concurrent-safe design.
    # Each worker has its own connection+cursor pair — they never share state.
    t_a = threading.Thread(target=_worker, args=("a", conn_a, cursor_a))
    t_b = threading.Thread(target=_worker, args=("b", conn_b, cursor_b))
    t_a.start()
    t_b.start()
    t_a.join()
    t_b.join()

    ids_a = {r["id"] for r in results["a"]}
    ids_b = {r["id"] for r in results["b"]}

    assert ids_a.isdisjoint(ids_b), (
        f"Workers claimed overlapping rows: {ids_a & ids_b}"
    )

    # Verify both workers used the concurrency-safe SELECT form
    for worker_name, cursor in [("a", cursor_a), ("b", cursor_b)]:
        select_sql = next(
            sql for sql, _ in cursor.executions if "SELECT" in sql.upper()
        )
        assert "FOR UPDATE SKIP LOCKED" in select_sql, (
            f"Worker {worker_name}: SELECT must contain 'FOR UPDATE SKIP LOCKED'; "
            f"got: {select_sql!r}"
        )

    # Verify each worker emitted an UPDATE to mark its row as 'processing'
    for worker_name, cursor in [("a", cursor_a), ("b", cursor_b)]:
        update_sqls = [
            sql for sql, _ in cursor.executions if "UPDATE" in sql.upper()
        ]
        assert update_sqls, (
            f"Worker {worker_name}: expected an UPDATE to set status='processing'"
        )
        assert any("processing" in sql for sql in update_sqls), (
            f"Worker {worker_name}: UPDATE must set status to 'processing'"
        )


# ===========================================================================
# Content preparation tests (Phase A — Prompt 3)
# ===========================================================================
#
# All four tests mock ``stage3.batch_processor._count_tokens`` so no Gemini
# API key is required.  The mock uses a deterministic formula:
#
#   tokens(text) = len(text.split())   (1 token per whitespace-separated word)
#
# This is simpler than 1.5 tokens/word and makes expected values exact.
# ===========================================================================

_MODEL = "gemini-3.5-flash"  # value is irrelevant — count_tokens is mocked


def _proportional_count(text: str, _model: str) -> int:
    """Deterministic token counter: 1 token per whitespace-separated word."""
    return len(text.split())


# ---------------------------------------------------------------------------
# test_html_preparation_returns_text
# ---------------------------------------------------------------------------

def test_html_preparation_returns_text():
    """prepare_html_page returns a non-empty string for a normal grant page.

    Uses tests/fixtures/sample_meta_html.json → sample_page.html.gz (~679 words).
    With the proportional mock (1 token/word), count ≈ 679 — well within the
    [50, 6000] window, so no truncation occurs.
    """
    meta_path = FIXTURE_DIR / "sample_meta_html.json"
    assert meta_path.exists(), f"Fixture missing: {meta_path}"

    with patch("stage3.batch_processor._count_tokens", side_effect=_proportional_count):
        text, reason = prepare_html_page(meta_path, FIXTURE_RAW_CACHE, _MODEL)

    assert reason is None, f"Expected no skip reason, got {reason!r}"
    assert isinstance(text, str) and text.strip(), "Expected a non-empty text string"
    # Spot-check: stripped content should contain words from the source HTML.
    assert "grant" in text.lower() or "innovation" in text.lower()


# ---------------------------------------------------------------------------
# test_short_page_returns_none
# ---------------------------------------------------------------------------

def test_short_page_returns_none():
    """prepare_html_page returns (None, 'content_too_short') for a short page.

    Uses tests/fixtures/sample_meta_short.json → short_page.html.gz (~28 words).
    With the proportional mock, count ≈ 28 which is below the 50-token minimum.
    """
    meta_path = FIXTURE_DIR / "sample_meta_short.json"
    assert meta_path.exists(), f"Fixture missing: {meta_path}"

    with patch("stage3.batch_processor._count_tokens", side_effect=_proportional_count):
        text, reason = prepare_html_page(meta_path, FIXTURE_RAW_CACHE, _MODEL)

    assert text is None, "Short page should return None for text"
    assert reason == "content_too_short", (
        f"Expected reason 'content_too_short', got {reason!r}"
    )


# ---------------------------------------------------------------------------
# test_html_truncation
# ---------------------------------------------------------------------------

def test_html_truncation(tmp_path):
    """prepare_html_page truncates content that exceeds 6 000 tokens to ≤ 6 000.

    Strategy: synthesise a 9 000-word HTML page in a tmp_path raw_cache, then
    apply the proportional mock (1 token/word).  The full stripped text will
    report 9 000 tokens > 6 000, triggering truncation.  After truncation the
    returned text must contain ≤ 6 000 words.
    """
    # Build a 9 000-word HTML body to guarantee the over-budget path is exercised.
    body_words = " ".join(f"grant-keyword-{i}" for i in range(9_000))
    large_html = (
        "<!DOCTYPE html><html><head><title>Large Grant Page</title></head>"
        f"<body><p>{body_words}</p></body></html>"
    )

    # Write the .html.gz into a temporary raw_cache directory.
    pages_dir = tmp_path / "large.org" / "2026-05-23" / "pages"
    pages_dir.mkdir(parents=True)
    gz_path = pages_dir / "large00000000001.html.gz"
    gz_path.write_bytes(gzip.compress(large_html.encode()))

    meta = {
        "url_hash": "large00000000001",
        "domain": "large.org",
        "crawl_date": "2026-05-23",
        "changed": True,
        "is_pdf": False,
        "html_path": "large.org/2026-05-23/pages/large00000000001.html.gz",
    }
    meta_path = tmp_path / "large_meta.json"
    meta_path.write_text(json.dumps(meta))

    with patch("stage3.batch_processor._count_tokens", side_effect=_proportional_count):
        text, reason = prepare_html_page(meta_path, tmp_path, _MODEL)

    assert reason is None, f"Expected no error, got reason={reason!r}"
    assert text is not None

    word_count = len(text.split())
    assert word_count <= 6_000, (
        f"Truncated text has {word_count} words > 6 000 token limit"
    )
    assert word_count > 0, "Truncated text must not be empty"


# ---------------------------------------------------------------------------
# test_pdf_preparation
# ---------------------------------------------------------------------------

def test_pdf_preparation():
    """prepare_pdf_page returns the pdf_text string from the meta JSON.

    Uses tests/fixtures/sample_meta_pdf.json which contains ~213 words of PDF
    text.  With the proportional mock, count ≈ 213 — within [50, 12 000], so
    the text is returned as-is without truncation.
    """
    meta_path = FIXTURE_DIR / "sample_meta_pdf.json"
    assert meta_path.exists(), f"Fixture missing: {meta_path}"

    # Load the expected pdf_text for an exact content check.
    meta = json.loads(meta_path.read_text())
    expected_text = meta["pdf_text"]

    with patch("stage3.batch_processor._count_tokens", side_effect=_proportional_count):
        text, reason = prepare_pdf_page(meta_path, _MODEL)

    assert reason is None, f"Expected no skip reason, got {reason!r}"
    assert text == expected_text, (
        "Returned text must match the pdf_text field verbatim when no truncation occurs"
    )


# ---------------------------------------------------------------------------
# Error handling — missing file / missing field
# ---------------------------------------------------------------------------

def test_prepare_html_missing_gz(tmp_path):
    """prepare_html_page returns (None, 'html_read_error') if .html.gz is absent."""
    meta = {
        "url_hash": "missing000000001",
        "domain": "gone.com",
        "crawl_date": "2026-05-23",
        "changed": True,
        "is_pdf": False,
        "html_path": "gone.com/2026-05-23/pages/missing.html.gz",  # does not exist
    }
    meta_path = tmp_path / "missing_meta.json"
    meta_path.write_text(json.dumps(meta))

    with patch("stage3.batch_processor._count_tokens", side_effect=_proportional_count):
        text, reason = prepare_html_page(meta_path, tmp_path, _MODEL)

    assert text is None
    assert reason == "html_read_error"


def test_prepare_pdf_no_pdf_text(tmp_path):
    """prepare_pdf_page returns (None, 'no_pdf_text') when pdf_text is absent."""
    meta = {
        "url_hash": "nopdf000000000001",
        "domain": "gone.com",
        "crawl_date": "2026-05-23",
        "changed": True,
        "is_pdf": True,
        # no pdf_text field
    }
    meta_path = tmp_path / "no_pdf_meta.json"
    meta_path.write_text(json.dumps(meta))

    with patch("stage3.batch_processor._count_tokens", side_effect=_proportional_count):
        text, reason = prepare_pdf_page(meta_path, _MODEL)

    assert text is None
    assert reason == "no_pdf_text"
