"""
End-to-end integration test for Stage 3.

Runs the full pipeline against a fixture raw_cache directory.
Requires a real PostgreSQL test database (set DATABASE_URL env var).
Uses a MOCKED _extract_fn instead of the real Gemini Batch API.

The fixture raw_cache contains exactly 10 pages (grant_a … grant_j):

  Page       | Type | Expected outcome
  -----------|------|-----------------------------------------------------------
  grant_a    | HTML | 1 record inserted, review_status='approved'
  grant_b    | HTML | 2 records inserted
  grant_c    | PDF  | 1 record, requires_review=True, review_status='pending'
  grant_d    | HTML | 0 records (navigation page), extraction_log='completed'
  grant_e    | HTML | 0 records (content too short), extraction_log='skipped'
  grant_f    | HTML | same content_hash as grant_a, lower confidence → skipped
  grant_g    | HTML | same content_hash as grant_a, higher confidence → update
  grant_h    | HTML | 1 record, current_status='Rolling'
  grant_i    | HTML | 1 record, current_status='Closed'
  grant_j    | HTML | 1 record, current_status='Open'
"""

from __future__ import annotations

import gzip
import io
import json
import os
from pathlib import Path

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Skip entire module when DATABASE_URL is absent
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set — skipping end-to-end tests",
)

_SCHEMA = "stage3_test"
_RUN_DATE = "2026-05-23"

# ---------------------------------------------------------------------------
# Shared confidence-score building blocks
# ---------------------------------------------------------------------------

_HIGH_CS: dict = {
    "grant_title": "high",
    "funder_name": "high",
    "application_deadline": "high",
    "eoi_deadline": "not_found",
    "grant_opening_date": "not_found",
    "funding_amount": "not_found",
    "current_status": "not_found",
    "geographic_focus": "high",
    "thematic_sectors": "high",
    "individual_eligibility": "not_found",
    "organisation_types": "high",
    "applicant_base": "high",
    "ai_focused": "high",
}

# aggregate for _HIGH_CS: 3+3+3+0+0+0+0+3+3+0+3+3+3 = 24
_AGG_HIGH = 24

_LOW_CS: dict = {k: "low" for k in _HIGH_CS}
# aggregate for _LOW_CS: 13 * 1 = 13

_HIGH_CS_G: dict = {
    **_HIGH_CS,
    "eoi_deadline": "high",   # was not_found in grant_a → adds 3
    "funding_amount": "high", # was not_found in grant_a → adds 3
}
# aggregate for _HIGH_CS_G: 24 + 6 = 30
_AGG_G = 30

# ---------------------------------------------------------------------------
# Mock grant definitions (match the controlled vocabularies exactly)
# ---------------------------------------------------------------------------

_BASE_GEO = ["global"]      # normalises to regions=['Global'], no 'Others'
_BASE_SECTOR = ["Science, Technology, Engineering and Mathematics (STEM)"]
_BASE_ORGTYPE = ["University / Higher Education Institution"]

MOCK_GRANT_A: dict = {
    "grant_title": "Innovation Research Grant 2026",
    "funder_name": "Test Foundation International",
    "description": "A flagship grant for cutting-edge innovation research.",
    "application_deadline_raw": "2026-12-31",
    "eoi_deadline_raw": None,
    "grant_opening_date_raw": None,
    "deadline_notes": None,
    "funding_amount_min": 50000,
    "funding_amount_max": 200000,
    "currency_raw": "USD",
    "current_status_raw": None,
    "application_portal_url": "https://example.com/apply",
    "source_language_raw": "en",
    "ai_focused": False,
    "individuals_not_eligible": False,
    "organisation_types_raw": _BASE_ORGTYPE,
    "individual_eligibility_raw": [],
    "applicant_base_raw": _BASE_GEO,
    "geographic_focus_raw": _BASE_GEO,
    "thematic_sectors_raw": _BASE_SECTOR,
    "grant_types_raw": ["Research Grant"],
    "confidence_scores": _HIGH_CS,
    "raw_notes": None,
}

# Same funder + title → same content_hash; lower confidence → upsert skipped
MOCK_GRANT_F: dict = {
    **MOCK_GRANT_A,
    "confidence_scores": _LOW_CS,
}

# Same funder + title → same content_hash; higher aggregate → update
MOCK_GRANT_G: dict = {
    **MOCK_GRANT_A,
    "confidence_scores": _HIGH_CS_G,
}

MOCK_GRANT_B1: dict = {
    "grant_title": "Digital Innovation Fund",
    "funder_name": "Tech Research Institute",
    "description": "Funding for digital innovation initiatives.",
    "application_deadline_raw": "2027-03-31",
    "eoi_deadline_raw": None,
    "grant_opening_date_raw": None,
    "deadline_notes": None,
    "funding_amount_min": 10000,
    "funding_amount_max": 50000,
    "currency_raw": "EUR",
    "current_status_raw": None,
    "application_portal_url": None,
    "source_language_raw": "en",
    "ai_focused": False,
    "individuals_not_eligible": False,
    "organisation_types_raw": ["Non-Governmental Organisation (NGO)"],
    "individual_eligibility_raw": [],
    "applicant_base_raw": ["South Asia"],
    "geographic_focus_raw": ["South Asia"],
    "thematic_sectors_raw": ["Digital Technology and Innovation"],
    "grant_types_raw": ["Project Grant"],
    "confidence_scores": _HIGH_CS,
    "raw_notes": None,
}

MOCK_GRANT_B2: dict = {
    "grant_title": "Climate Tech Grant",
    "funder_name": "Tech Research Institute",
    "description": "Support for climate technology solutions.",
    "application_deadline_raw": "2027-06-30",
    "eoi_deadline_raw": None,
    "grant_opening_date_raw": None,
    "deadline_notes": None,
    "funding_amount_min": 25000,
    "funding_amount_max": 100000,
    "currency_raw": "EUR",
    "current_status_raw": None,
    "application_portal_url": None,
    "source_language_raw": "en",
    "ai_focused": False,
    "individuals_not_eligible": False,
    "organisation_types_raw": ["Research Institution / Think Tank"],
    "individual_eligibility_raw": [],
    "applicant_base_raw": _BASE_GEO,
    "geographic_focus_raw": _BASE_GEO,
    "thematic_sectors_raw": ["Climate Change and Environment"],
    "grant_types_raw": ["Research Grant"],
    "confidence_scores": _HIGH_CS,
    "raw_notes": None,
}

# Low deadline confidence → R3 review flag fires → requires_review=True
_CS_C: dict = {**_HIGH_CS, "application_deadline": "low"}

MOCK_GRANT_C: dict = {
    "grant_title": "Medical Research Fellowship 2026",
    "funder_name": "Health Research Council",
    "description": "A fellowship supporting medical research excellence.",
    "application_deadline_raw": "2026-07-15",
    "eoi_deadline_raw": None,
    "grant_opening_date_raw": None,
    "deadline_notes": "Date subject to confirmation by the funder.",
    "funding_amount_min": None,
    "funding_amount_max": None,
    "currency_raw": None,
    "current_status_raw": None,
    "application_portal_url": None,
    "source_language_raw": "en",
    "ai_focused": False,
    "individuals_not_eligible": False,
    "organisation_types_raw": _BASE_ORGTYPE,
    "individual_eligibility_raw": ["Early Career Researcher"],
    "applicant_base_raw": _BASE_GEO,
    "geographic_focus_raw": _BASE_GEO,
    "thematic_sectors_raw": ["Health and Medical Research"],
    "grant_types_raw": ["Fellowship"],
    "confidence_scores": _CS_C,
    "raw_notes": None,
}

# Rolling deadline → Rule 2 → current_status='Rolling'
MOCK_GRANT_H: dict = {
    "grant_title": "Rolling Support Programme",
    "funder_name": "Open Foundation Trust",
    "description": "Continuous support with rolling application windows.",
    "application_deadline_raw": "Rolling — applications accepted year-round",
    "eoi_deadline_raw": None,
    "grant_opening_date_raw": None,
    "deadline_notes": None,
    "funding_amount_min": 5000,
    "funding_amount_max": 30000,
    "currency_raw": "GBP",
    "current_status_raw": None,
    "application_portal_url": None,
    "source_language_raw": "en",
    "ai_focused": False,
    "individuals_not_eligible": False,
    "organisation_types_raw": ["Non-Governmental Organisation (NGO)"],
    "individual_eligibility_raw": [],
    "applicant_base_raw": _BASE_GEO,
    "geographic_focus_raw": _BASE_GEO,
    "thematic_sectors_raw": ["Poverty Reduction and Social Protection"],
    "grant_types_raw": ["Project Grant"],
    "confidence_scores": _HIGH_CS,
    "raw_notes": None,
}

# Past confirmed deadline + high confidence → Rule 4 → current_status='Closed'
MOCK_GRANT_I: dict = {
    "grant_title": "Historical Environment Grant",
    "funder_name": "Heritage Preservation Fund",
    "description": "Grants for heritage site preservation projects.",
    "application_deadline_raw": "2020-01-15",
    "eoi_deadline_raw": None,
    "grant_opening_date_raw": None,
    "deadline_notes": None,
    "funding_amount_min": None,
    "funding_amount_max": 80000,
    "currency_raw": "GBP",
    "current_status_raw": None,
    "application_portal_url": None,
    "source_language_raw": "en",
    "ai_focused": False,
    "individuals_not_eligible": False,
    "organisation_types_raw": ["Government / Public Authority"],
    "individual_eligibility_raw": [],
    "applicant_base_raw": ["South Asia"],
    "geographic_focus_raw": ["South Asia"],
    "thematic_sectors_raw": ["Arts, Culture and Heritage"],
    "grant_types_raw": ["Project Grant"],
    "confidence_scores": _HIGH_CS,
    "raw_notes": None,
}

# Future confirmed deadline + high confidence → Rule 4 → current_status='Open'
MOCK_GRANT_J: dict = {
    "grant_title": "Future Innovation Grant",
    "funder_name": "Forward Thinking Foundation",
    "description": "Transformative grants for future-oriented innovation.",
    "application_deadline_raw": "2030-01-01",
    "eoi_deadline_raw": None,
    "grant_opening_date_raw": None,
    "deadline_notes": None,
    "funding_amount_min": 100000,
    "funding_amount_max": 500000,
    "currency_raw": "USD",
    "current_status_raw": None,
    "application_portal_url": None,
    "source_language_raw": "en",
    "ai_focused": False,
    "individuals_not_eligible": False,
    "organisation_types_raw": ["Foundation / Philanthropic Organisation"],
    "individual_eligibility_raw": [],
    "applicant_base_raw": _BASE_GEO,
    "geographic_focus_raw": _BASE_GEO,
    "thematic_sectors_raw": _BASE_SECTOR,
    "grant_types_raw": ["Research Grant"],
    "confidence_scores": _HIGH_CS,
    "raw_notes": None,
}

# Mapping: url_hash → list of raw grant dicts returned by the mock
MOCK_GRANTS_BY_HASH: dict[str, list[dict]] = {
    "grant_a": [MOCK_GRANT_A],
    "grant_b": [MOCK_GRANT_B1, MOCK_GRANT_B2],
    "grant_c": [MOCK_GRANT_C],
    "grant_d": [],          # navigation page — LLM returns empty list
    # grant_e is skipped by prepare_html_page (content_too_short) — never reaches mock
    "grant_f": [MOCK_GRANT_F],   # same hash as grant_a, lower confidence
    "grant_g": [MOCK_GRANT_G],   # same hash as grant_a, higher confidence
    "grant_h": [MOCK_GRANT_H],
    "grant_i": [MOCK_GRANT_I],
    "grant_j": [MOCK_GRANT_J],
}


# ---------------------------------------------------------------------------
# Fixture factory helpers
# ---------------------------------------------------------------------------

def _gz(html_content: str) -> bytes:
    """Gzip-compress an HTML string and return bytes."""
    buf = io.BytesIO()
    with gzip.open(buf, "wb") as fh:
        fh.write(html_content.encode("utf-8"))
    return buf.getvalue()


# Long enough that mock_count_tokens (word-count based) returns > 50
_LONG_HTML_BODY = " ".join([
    "This prestigious grant programme supports innovative research projects",
    "that address global challenges through rigorous scientific inquiry.",
    "Eligible applicants must demonstrate institutional affiliation and a clear",
    "research agenda. The total award value is up to USD 200,000 per project",
    "over twenty-four months. Applications are accepted via the online portal.",
    "The review panel comprises international experts in the relevant fields.",
    "All funded projects must publish results under an open-access licence.",
    "Indirect costs may be included up to twenty percent of direct costs.",
    "Contact the grants office for pre-application advice and guidance.",
    "The deadline for full proposals is indicated on the programme website.",
])

# Deliberately tiny — mock_count_tokens must return < 50 words
_SHORT_HTML_BODY = "Navigation Menu Home About Contact"


def _make_raw_cache(base_dir: Path, run_date: str) -> None:
    """Build the 10-page fixture raw_cache directory under *base_dir*."""
    pages_dir = base_dir / "example.com" / run_date / "pages"
    pages_dir.mkdir(parents=True)

    # --- HTML pages ---
    html_pages = {
        "grant_a": _LONG_HTML_BODY,
        "grant_b": _LONG_HTML_BODY,
        "grant_d": _LONG_HTML_BODY,   # navigation page — long content, mock returns []
        "grant_e": _SHORT_HTML_BODY,  # content too short — never reaches mock
        "grant_f": _LONG_HTML_BODY,
        "grant_g": _LONG_HTML_BODY,
        "grant_h": _LONG_HTML_BODY,
        "grant_i": _LONG_HTML_BODY,
        "grant_j": _LONG_HTML_BODY,
    }
    for name, body in html_pages.items():
        html_rel = f"example.com/{run_date}/pages/{name}.html.gz"
        gz_path = base_dir / html_rel
        gz_path.write_bytes(_gz(f"<html><body><p>{body}</p></body></html>"))
        meta = {
            "url": f"https://example.com/grants/{name}",
            "url_hash": name,
            "domain": "example.com",
            "crawl_date": run_date,
            "changed": True,
            "is_pdf": False,
            "html_path": html_rel,
        }
        (pages_dir / f"{name}.meta.json").write_text(
            json.dumps(meta), encoding="utf-8"
        )

    # --- PDF page (grant_c) — pdf_text stored in meta.json ---
    meta_c = {
        "url": "https://example.com/grants/grant_c",
        "url_hash": "grant_c",
        "domain": "example.com",
        "crawl_date": run_date,
        "changed": True,
        "is_pdf": True,
        "pdf_text": _LONG_HTML_BODY,
    }
    (pages_dir / "grant_c.meta.json").write_text(
        json.dumps(meta_c), encoding="utf-8"
    )

    # --- Sentinel ---
    (base_dir / f"crawl_complete_{run_date}.json").write_text(
        json.dumps({"date": run_date, "status": "complete"}), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Mock extraction function
# ---------------------------------------------------------------------------

def _make_mock_extract_fn(grants_by_hash: dict):
    """Return an _extract_fn that returns pre-written grants by url_hash.

    Each grant dict has ``__url_hash`` injected so the orchestrator can look
    up provenance (source_url, domain) from page_contents.
    The mock also calls ``mark_completed`` for each page row so that
    extraction_log reflects the correct final status.
    """
    from stage3.batch_processor import mark_completed

    def _mock_fn(page_contents: list[dict], conn) -> list[dict]:
        all_grants: list[dict] = []
        for item in page_contents:
            url_hash = item["url_hash"]
            row = item["row"]
            grants = grants_by_hash.get(url_hash, [])
            for g in grants:
                g_copy = dict(g)
                g_copy["__url_hash"] = url_hash
                all_grants.append(g_copy)
            mark_completed(conn, row["id"], len(grants))
        conn.commit()
        return all_grants

    return _mock_fn


# ---------------------------------------------------------------------------
# Module-scoped fixture: run the pipeline once, yield results
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def e2e_run(db_conn, tmp_path_factory):  # noqa: PT004
    """Build fixture raw_cache, run the full pipeline with mocked Gemini,
    and yield a dict with the psycopg2 connection, output directory, and
    pipeline statistics.

    The pipeline runs exactly ONCE per test module; individual tests only
    query the database and inspect files.
    """
    tmp = tmp_path_factory.mktemp("e2e")
    raw_cache = tmp / "raw_cache"
    output_dir = tmp / "output"
    raw_cache.mkdir()
    output_dir.mkdir()

    _make_raw_cache(raw_cache, _RUN_DATE)

    # Truncate both tables for a clean run
    with db_conn.cursor() as cur:
        cur.execute(
            f"TRUNCATE TABLE {_SCHEMA}.grants RESTART IDENTITY CASCADE"
        )
        cur.execute(
            f"TRUNCATE TABLE {_SCHEMA}.extraction_log RESTART IDENTITY CASCADE"
        )
    db_conn.commit()

    from conftest import _make_patched_get_connection

    def _mock_count_tokens(text: str, model_name: str) -> int:
        """Return word count — avoids real Gemini API calls in tests."""
        return len(text.split())

    mock_fn = _make_mock_extract_fn(MOCK_GRANTS_BY_HASH)

    with (
        patch(
            "stage3.db.get_connection",
            _make_patched_get_connection(_SCHEMA),
        ),
        patch(
            "stage3.batch_processor._count_tokens",
            _mock_count_tokens,
        ),
        patch.dict(os.environ, {
            "RAW_CACHE_DIR": str(raw_cache),
            "STAGE3_OUTPUT_DIR": str(output_dir),
        }),
    ):
        from stage3.batch_processor import run_extraction_cycle

        stats = run_extraction_cycle(
            force=True,
            run_date=_RUN_DATE,
            _extract_fn=mock_fn,
        )

    yield {"conn": db_conn, "output_dir": output_dir, "stats": stats}


# ---------------------------------------------------------------------------
# Helper — run a query against the test schema
# ---------------------------------------------------------------------------

def _query(conn, sql: str, params=None) -> list[dict]:
    """Execute *sql* against the test schema and return rows as dicts."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def _scalar(conn, sql: str, params=None):
    rows = _query(conn, sql, params)
    return rows[0][list(rows[0].keys())[0]] if rows else None


# Fully-qualified table references — independent of search_path on db_conn
_G = f"{_SCHEMA}.grants"
_EL = f"{_SCHEMA}.extraction_log"


# ===========================================================================
# Test class — all tests share the single module-scoped pipeline run
# ===========================================================================

class TestEndToEnd:

    # -----------------------------------------------------------------------
    # grants table — row counts
    # -----------------------------------------------------------------------

    def test_total_unique_grants(self, e2e_run):
        """Pipeline must produce exactly 7 unique records in the grants table."""
        conn = e2e_run["conn"]
        count = _scalar(conn, f"SELECT COUNT(*) FROM {_G}")
        assert count == 7

    def test_stats_records_inserted(self, e2e_run):
        """stats dict must report 7 unique inserts (a, b×2, c, h, i, j)."""
        stats = e2e_run["stats"]
        # grant_a inserted 1, b 2, c 1, h 1, i 1, j 1 → 7 inserted
        assert stats["records_inserted_new"] == 7

    def test_stats_records_updated(self, e2e_run):
        """grant_g updates grant_a (same hash, higher confidence)."""
        stats = e2e_run["stats"]
        assert stats["records_updated_higher_confidence"] == 1

    def test_stats_records_duplicate_skipped(self, e2e_run):
        """grant_f is skipped (same hash as grant_a, lower confidence)."""
        stats = e2e_run["stats"]
        assert stats["records_duplicate_lower_confidence"] == 1

    # -----------------------------------------------------------------------
    # grant_a: review_status='approved', updated by grant_g
    # -----------------------------------------------------------------------

    def _get_grant_by_title(self, conn, title: str) -> dict:
        rows = _query(conn, f"SELECT * FROM {_G} WHERE grant_title = %s", (title,))
        assert rows, f"Grant '{title}' not found in DB"
        return rows[0]

    def test_grant_a_review_status_approved(self, e2e_run):
        """grant_a must have review_status='approved' (requires_review=False)."""
        g = self._get_grant_by_title(
            e2e_run["conn"], "Innovation Research Grant 2026"
        )
        assert g["review_status"] == "approved"

    def test_grant_a_requires_review_false(self, e2e_run):
        """grant_a must have requires_review=False (all high confidence)."""
        g = self._get_grant_by_title(
            e2e_run["conn"], "Innovation Research Grant 2026"
        )
        assert g["requires_review"] is False

    def test_grant_g_updated_grant_a_confidence(self, e2e_run):
        """After grant_g upsert, grant_a's aggregate_confidence_score must equal
        grant_g's aggregate (30 > original 24)."""
        g = self._get_grant_by_title(
            e2e_run["conn"], "Innovation Research Grant 2026"
        )
        assert g["aggregate_confidence_score"] == _AGG_G

    def test_grant_g_preserves_approved_status(self, e2e_run):
        """CASE guard must keep review_status='approved' after grant_g update."""
        g = self._get_grant_by_title(
            e2e_run["conn"], "Innovation Research Grant 2026"
        )
        assert g["review_status"] == "approved"

    def test_grant_f_no_duplicate_created(self, e2e_run):
        """grant_f has the same content_hash as grant_a → only 1 record must exist
        for that funder+title combination."""
        conn = e2e_run["conn"]
        rows = _query(
            conn,
            f"SELECT * FROM {_G} WHERE grant_title = %s AND funder_name = %s",
            ("Innovation Research Grant 2026", "Test Foundation International"),
        )
        assert len(rows) == 1, "Duplicate content_hash must not create two DB rows"

    # -----------------------------------------------------------------------
    # grant_b: 2 records on one page
    # -----------------------------------------------------------------------

    def test_grant_b_two_records(self, e2e_run):
        """grant_b page must produce exactly 2 records in the grants table."""
        conn = e2e_run["conn"]
        rows = _query(
            conn,
            f"SELECT * FROM {_G} WHERE funder_name = %s",
            ("Tech Research Institute",),
        )
        assert len(rows) == 2

    # -----------------------------------------------------------------------
    # grant_c: requires_review=True, review_status='pending'
    # -----------------------------------------------------------------------

    def test_grant_c_requires_review_true(self, e2e_run):
        """grant_c deadline confidence is 'low' → requires_review must be True."""
        g = self._get_grant_by_title(
            e2e_run["conn"], "Medical Research Fellowship 2026"
        )
        assert g["requires_review"] is True

    def test_grant_c_review_status_pending(self, e2e_run):
        """grant_c must have review_status='pending' (review flag is set)."""
        g = self._get_grant_by_title(
            e2e_run["conn"], "Medical Research Fellowship 2026"
        )
        assert g["review_status"] == "pending"

    # -----------------------------------------------------------------------
    # grant_h, grant_i, grant_j: status auto-computation
    # -----------------------------------------------------------------------

    def test_grant_h_rolling_status(self, e2e_run):
        """Rolling deadline phrase → current_status='Rolling'."""
        g = self._get_grant_by_title(e2e_run["conn"], "Rolling Support Programme")
        assert g["current_status"] == "Rolling"

    def test_grant_i_closed_status(self, e2e_run):
        """Past confirmed deadline + high confidence → current_status='Closed'."""
        g = self._get_grant_by_title(e2e_run["conn"], "Historical Environment Grant")
        assert g["current_status"] == "Closed"

    def test_grant_j_open_status(self, e2e_run):
        """Future confirmed deadline + high confidence → current_status='Open'."""
        g = self._get_grant_by_title(e2e_run["conn"], "Future Innovation Grant")
        assert g["current_status"] == "Open"

    def test_grant_h_deadline_type_rolling(self, e2e_run):
        """application_deadline_type must be 'rolling' for grant_h."""
        g = self._get_grant_by_title(e2e_run["conn"], "Rolling Support Programme")
        assert g["application_deadline_type"] == "rolling"

    # -----------------------------------------------------------------------
    # extraction_log: 10 rows, 9 completed, 1 skipped, 0 failed
    # -----------------------------------------------------------------------

    def test_extraction_log_total_rows(self, e2e_run):
        """extraction_log must have exactly 10 rows (one per fixture page)."""
        conn = e2e_run["conn"]
        count = _scalar(conn, f"SELECT COUNT(*) FROM {_EL} WHERE crawl_date = %s", (_RUN_DATE,))
        assert count == 10

    def test_extraction_log_completed_count(self, e2e_run):
        """9 pages must be marked 'completed' in extraction_log."""
        conn = e2e_run["conn"]
        count = _scalar(
            conn,
            f"SELECT COUNT(*) FROM {_EL} WHERE status = 'completed' AND crawl_date = %s",
            (_RUN_DATE,),
        )
        assert count == 9

    def test_extraction_log_skipped_count(self, e2e_run):
        """Exactly 1 page (grant_e) must be 'skipped' in extraction_log."""
        conn = e2e_run["conn"]
        count = _scalar(
            conn,
            f"SELECT COUNT(*) FROM {_EL} WHERE status = 'skipped' AND crawl_date = %s",
            (_RUN_DATE,),
        )
        assert count == 1

    def test_extraction_log_no_failed(self, e2e_run):
        """No pages must be 'failed' in extraction_log."""
        conn = e2e_run["conn"]
        count = _scalar(
            conn,
            f"SELECT COUNT(*) FROM {_EL} WHERE status = 'failed' AND crawl_date = %s",
            (_RUN_DATE,),
        )
        assert count == 0

    def test_extraction_log_grant_e_skipped(self, e2e_run):
        """grant_e must be the skipped row (content_too_short)."""
        conn = e2e_run["conn"]
        rows = _query(
            conn,
            f"SELECT * FROM {_EL} WHERE url_hash = 'grant_e' AND crawl_date = %s",
            (_RUN_DATE,),
        )
        assert rows, "grant_e must have an extraction_log row"
        assert rows[0]["status"] == "skipped"

    def test_extraction_log_grant_d_completed_zero_records(self, e2e_run):
        """grant_d (navigation page) must be 'completed' with records_extracted=0."""
        conn = e2e_run["conn"]
        rows = _query(
            conn,
            f"SELECT * FROM {_EL} WHERE url_hash = 'grant_d' AND crawl_date = %s",
            (_RUN_DATE,),
        )
        assert rows, "grant_d must have an extraction_log row"
        assert rows[0]["status"] == "completed"
        assert rows[0]["records_extracted"] == 0

    # -----------------------------------------------------------------------
    # Output files
    # -----------------------------------------------------------------------

    def test_review_queue_csv_exists(self, e2e_run):
        """review_queue_{run_date}.csv must be written to STAGE3_OUTPUT_DIR."""
        csv_path = e2e_run["output_dir"] / f"review_queue_{_RUN_DATE}.csv"
        assert csv_path.exists(), f"Review queue CSV not found: {csv_path}"

    def test_review_queue_contains_grant_c(self, e2e_run):
        """grant_c (requires_review=True) must appear in the review queue CSV."""
        csv_path = e2e_run["output_dir"] / f"review_queue_{_RUN_DATE}.csv"
        content = csv_path.read_text(encoding="utf-8")
        assert "Medical Research Fellowship 2026" in content

    def test_review_queue_does_not_contain_grant_a(self, e2e_run):
        """grant_a (requires_review=False) must NOT appear in the review queue."""
        csv_path = e2e_run["output_dir"] / f"review_queue_{_RUN_DATE}.csv"
        content = csv_path.read_text(encoding="utf-8")
        assert "Innovation Research Grant 2026" not in content

    def test_extraction_report_json_exists(self, e2e_run):
        """extraction_report_{run_date}.json must be written to STAGE3_OUTPUT_DIR."""
        report_path = e2e_run["output_dir"] / f"extraction_report_{_RUN_DATE}.json"
        assert report_path.exists(), f"Extraction report not found: {report_path}"

    def test_extraction_report_pages_skipped_content_too_short(self, e2e_run):
        """QA report must record pages_skipped_content_too_short == 1."""
        report_path = e2e_run["output_dir"] / f"extraction_report_{_RUN_DATE}.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["pages_skipped_content_too_short"] == 1

    def test_extraction_report_pages_processed(self, e2e_run):
        """QA report must record pages_processed == 10 (all claimed rows)."""
        report_path = e2e_run["output_dir"] / f"extraction_report_{_RUN_DATE}.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["pages_processed"] == 10

    def test_extraction_report_records_inserted(self, e2e_run):
        """QA report records_inserted_new must equal 7."""
        report_path = e2e_run["output_dir"] / f"extraction_report_{_RUN_DATE}.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["records_inserted_new"] == 7

    def test_extraction_report_no_failures(self, e2e_run):
        """QA report must record pages_failed == 0."""
        report_path = e2e_run["output_dir"] / f"extraction_report_{_RUN_DATE}.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["pages_failed"] == 0

    # -----------------------------------------------------------------------
    # Pipeline stats dict (returned by run_extraction_cycle)
    # -----------------------------------------------------------------------

    def test_stats_pages_processed(self, e2e_run):
        """stats['pages_processed'] must equal 10."""
        assert e2e_run["stats"]["pages_processed"] == 10

    def test_stats_pages_skipped_content_too_short(self, e2e_run):
        """stats['pages_skipped_content_too_short'] must equal 1."""
        assert e2e_run["stats"]["pages_skipped_content_too_short"] == 1

    def test_stats_records_flagged_review(self, e2e_run):
        """stats['records_flagged_review'] must equal 1 (only grant_c)."""
        assert e2e_run["stats"]["records_flagged_review"] == 1

    # -----------------------------------------------------------------------
    # Content-hash / deduplication invariants
    # -----------------------------------------------------------------------

    def test_content_hash_consistency_a_f_g(self, e2e_run):
        """grant_a, grant_f, and grant_g share a content_hash; only one DB row
        must exist for that hash after the full pipeline run."""
        from stage3.normaliser import compute_content_hash, normalise_grant_title, normalise_funder_name

        title = normalise_grant_title("Innovation Research Grant 2026")
        funder = normalise_funder_name("Test Foundation International")["canonical_name"]
        expected_hash = compute_content_hash(funder, title)

        conn = e2e_run["conn"]
        count = _scalar(
            conn,
            f"SELECT COUNT(*) FROM {_G} WHERE content_hash = %s",
            (expected_hash,),
        )
        assert count == 1, "Exactly one row must exist for the shared content_hash"

    def test_grant_a_source_url_populated(self, e2e_run):
        """source_url must be the URL from the meta.json fixture."""
        g = self._get_grant_by_title(
            e2e_run["conn"], "Innovation Research Grant 2026"
        )
        assert g["source_url"] == "https://example.com/grants/grant_a"

    def test_grant_c_source_url_populated(self, e2e_run):
        """PDF page source_url must come from the meta.json 'url' field."""
        g = self._get_grant_by_title(
            e2e_run["conn"], "Medical Research Fellowship 2026"
        )
        assert g["source_url"] == "https://example.com/grants/grant_c"

    def test_all_grants_have_non_null_domain(self, e2e_run):
        """Every grant record must have domain = 'example.com'."""
        conn = e2e_run["conn"]
        bad = _scalar(
            conn,
            f"SELECT COUNT(*) FROM {_G} WHERE domain IS NULL OR domain = ''",
        )
        assert bad == 0

    def test_all_grants_have_crawl_date(self, e2e_run):
        """Every grant must have crawl_date = 2026-05-23."""
        conn = e2e_run["conn"]
        bad = _scalar(
            conn,
            f"SELECT COUNT(*) FROM {_G} WHERE crawl_date != '2026-05-23'",
        )
        assert bad == 0

    def test_grant_h_status_source_computed(self, e2e_run):
        """Rolling status must be marked status_source='computed', not 'extracted'."""
        g = self._get_grant_by_title(e2e_run["conn"], "Rolling Support Programme")
        assert g["status_source"] == "computed"

    def test_grant_i_application_deadline_parsed(self, e2e_run):
        """grant_i deadline '2020-01-15' must be stored as a date value."""
        import datetime
        g = self._get_grant_by_title(e2e_run["conn"], "Historical Environment Grant")
        assert g["application_deadline"] == datetime.date(2020, 1, 15)
