"""Unit tests for stage3/extractor.py — Phase B Prompt 3.

All tests use mocked Gemini API responses.  No real API calls are made.
"""

import json

import pytest
from unittest.mock import patch, MagicMock

from stage3.extractor import parse_llm_response, RESPONSE_SCHEMA, SYSTEM_PROMPT

# ---------------------------------------------------------------------------
# Shared test fixture — a fully-valid grant dict
# ---------------------------------------------------------------------------

_VALID_GRANT: dict = {
    "grant_title": "Innovation Research Grant 2026",
    "funder_name": "International Development Foundation",
    "description": "Supports research in sustainable development.",
    "application_deadline_raw": "30 April 2026",
    "deadline_notes": None,
    "eoi_deadline_raw": "28 February 2026",
    "grant_opening_date_raw": "15 January 2026",
    "funding_amount_min": 50_000.0,
    "funding_amount_max": 500_000.0,
    "currency_raw": "USD",
    "current_status_raw": None,
    "application_portal_url": "https://grants.example.com/apply",
    "source_language_raw": "en",
    "ai_focused": False,
    "individuals_not_eligible": False,
    "organisation_types_raw": ["University / Higher Education Institution", "NGO"],
    "individual_eligibility_raw": [],
    "applicant_base_raw": ["Global"],
    "geographic_focus_raw": ["Sub-Saharan Africa", "South Asia"],
    "thematic_sectors_raw": ["Health and Medical Research", "Education and Training"],
    "grant_types_raw": ["Research Grant"],
    "confidence_scores": {
        "grant_title": "high",
        "funder_name": "high",
        "application_deadline": "high",
        "eoi_deadline": "high",
        "grant_opening_date": "high",
        "funding_amount": "high",
        "current_status": "not_found",
        "geographic_focus": "high",
        "thematic_sectors": "medium",
        "individual_eligibility": "not_found",
        "organisation_types": "medium",
        "applicant_base": "high",
        "ai_focused": "high",
    },
    "raw_notes": None,
}


# ---------------------------------------------------------------------------
# parse_llm_response — correctness tests
# ---------------------------------------------------------------------------


def test_empty_list_response():
    """parse_llm_response('[]') must return an empty list."""
    result = parse_llm_response("[]")
    assert result == []


def test_single_grant():
    """A valid single-grant JSON array returns a list of length 1 with the
    correct fields intact."""
    payload = json.dumps([_VALID_GRANT])
    result = parse_llm_response(payload)
    assert len(result) == 1
    assert result[0]["grant_title"] == _VALID_GRANT["grant_title"]
    assert result[0]["confidence_scores"]["grant_title"] == "high"


def test_multiple_grants():
    """A JSON array with 3 grant objects returns a list of length 3."""
    grant_a = {**_VALID_GRANT, "grant_title": "Grant A"}
    grant_b = {**_VALID_GRANT, "grant_title": "Grant B"}
    grant_c = {**_VALID_GRANT, "grant_title": "Grant C"}
    payload = json.dumps([grant_a, grant_b, grant_c])
    result = parse_llm_response(payload)
    assert len(result) == 3
    titles = {g["grant_title"] for g in result}
    assert titles == {"Grant A", "Grant B", "Grant C"}


def test_malformed_json_raises():
    """Non-JSON input must raise ValueError."""
    with pytest.raises(ValueError, match="not valid JSON"):
        parse_llm_response("not json")


def test_non_list_raises():
    """A valid JSON object (dict, not list) must raise ValueError."""
    with pytest.raises(ValueError, match="must be a JSON list"):
        parse_llm_response('{"grant_title": "x"}')


def test_malformed_item_skipped():
    """An item missing ``confidence_scores`` is silently skipped; a valid
    neighbouring item is still returned."""
    incomplete_grant = {
        "grant_title": "No Confidence Scores Grant",
        "funder_name": "Test Funder",
        # deliberately omits "confidence_scores"
    }
    payload = json.dumps([_VALID_GRANT, incomplete_grant])
    result = parse_llm_response(payload)
    assert len(result) == 1
    assert result[0]["grant_title"] == _VALID_GRANT["grant_title"]


# ---------------------------------------------------------------------------
# RESPONSE_SCHEMA — structural completeness
# ---------------------------------------------------------------------------

# All 13 confidence-score field names mandated by the design doc §6.3
_EXPECTED_CS_FIELDS = {
    "grant_title",
    "funder_name",
    "application_deadline",
    "eoi_deadline",
    "grant_opening_date",
    "funding_amount",
    "current_status",
    "geographic_focus",
    "thematic_sectors",
    "individual_eligibility",
    "organisation_types",
    "applicant_base",
    "ai_focused",
}


def test_response_schema_has_all_fields():
    """RESPONSE_SCHEMA must expose all 13 confidence-score fields including
    ``grant_opening_date`` and ``applicant_base`` (the two most commonly
    omitted by earlier schema drafts)."""
    # Navigate the schema: items → properties → confidence_scores → properties
    cs_props: dict = (
        RESPONSE_SCHEMA["items"]["properties"]["confidence_scores"]["properties"]
    )
    actual_fields = set(cs_props.keys())
    assert actual_fields == _EXPECTED_CS_FIELDS, (
        f"Missing fields: {_EXPECTED_CS_FIELDS - actual_fields}, "
        f"extra fields: {actual_fields - _EXPECTED_CS_FIELDS}"
    )
    # Spot-check the two previously-missing fields explicitly
    assert "grant_opening_date" in cs_props
    assert "applicant_base" in cs_props


# ---------------------------------------------------------------------------
# SYSTEM_PROMPT — Rule 12 correctness
# ---------------------------------------------------------------------------


def test_system_prompt_rule_12_no_translation_promise():
    """Rule 12 must instruct the model NOT to translate, and must NOT promise
    that the normalisation system will perform translation (v1.3 correction).

    Specifically:
    - 'normalisation system' must appear in the prompt (it is referenced by Rule 3).
    - 'do not translate' must appear (Rule 12 directive).
    - No sentence that contains 'normalisation' should also mention translation.
    """
    prompt_lower = SYSTEM_PROMPT.lower()

    # Rule 3 sanity check — the normalisation system is mentioned
    assert "normalisation system" in prompt_lower, (
        "SYSTEM_PROMPT must reference 'normalisation system' in Rule 3"
    )

    # Rule 12 must explicitly prohibit translation
    assert "do not translate" in prompt_lower, (
        "SYSTEM_PROMPT Rule 12 must contain 'Do not translate'"
    )

    # No sentence should combine 'normalisation' with a translation promise
    sentences = prompt_lower.replace("\n", " ").split(".")
    for sentence in sentences:
        if "normalisation" in sentence:
            assert "translat" not in sentence, (
                "SYSTEM_PROMPT must not promise that the normalisation system "
                f"translates values. Offending sentence: {sentence.strip()!r}"
            )
