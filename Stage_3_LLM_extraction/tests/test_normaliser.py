"""
Comprehensive unit tests for stage3/normaliser.py — Phase C Prompt 4.

All tests are offline (no database, no API calls).
"""

import datetime
import pytest

from stage3.normaliser import (
    normalise_grant_title,
    normalise_funder_name,
    normalise_deadline,
    normalise_country,
    normalise_geographic_list,
    normalise_controlled_vocab,
    compute_content_hash,
    aggregate_confidence_score,
    determine_review_flag,
    compute_status,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

today = datetime.date.today()
_PAST = today - datetime.timedelta(days=60)
_FUTURE = today + datetime.timedelta(days=60)
_TOMORROW = today + datetime.timedelta(days=1)


def _cs(**overrides) -> dict:
    """Return a confidence_scores dict with all fields set to 'high' by default."""
    base = {
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
    base.update(overrides)
    return base


def _clean_record(**overrides) -> dict:
    """Return a fully-clean normalised record that triggers no review rules."""
    base = {
        "confidence_scores": _cs(),
        "application_deadline_type": "confirmed",
        "application_deadline": _FUTURE,
        "grant_opening_date": None,
        "current_status": "Open",
        "current_status_raw": None,
        "status_source": "computed",
        "thematic_sectors": ["Health and Medical Research"],
        "geographic_focus_regions": ["Sub-Saharan Africa"],
        "individual_eligibility": [],
        "organisation_types": ["NGO"],
        "individuals_not_eligible": False,
    }
    base.update(overrides)
    return base


# ===========================================================================
# Grant title normalisation
# ===========================================================================

class TestNormaliseGrantTitle:
    def test_title_case_applied(self):
        assert normalise_grant_title("the innovation fund") == "The Innovation Fund"

    def test_terminal_period_stripped(self):
        assert normalise_grant_title("the innovation fund.") == "The Innovation Fund"

    def test_terminal_question_mark_preserved(self):
        assert normalise_grant_title("who benefits?") == "Who Benefits?"

    def test_terminal_exclamation_preserved(self):
        assert normalise_grant_title("apply now!") == "Apply Now!"

    def test_leading_trailing_whitespace_stripped(self):
        assert normalise_grant_title("  clean title  ") == "Clean Title"

    def test_none_returns_none(self):
        assert normalise_grant_title(None) is None

    def test_blank_string_returns_none(self):
        assert normalise_grant_title("   ") is None

    def test_multiple_trailing_punctuation(self):
        # e.g. "Grant A..." should strip all trailing punctuation
        result = normalise_grant_title("grant a...")
        assert result == "Grant A"

    def test_colon_stripped(self):
        assert normalise_grant_title("phase two:") == "Phase Two"


# ===========================================================================
# Deadline normalisation
# ===========================================================================

class TestNormaliseDeadline:
    def test_rolling_keyword(self):
        result = normalise_deadline("rolling applications", "high")
        assert result["type"] == "rolling"
        assert result["date"] is None

    def test_open_continuously_is_rolling(self):
        result = normalise_deadline("open continuously until filled", "medium")
        assert result["type"] == "rolling"

    def test_no_deadline_is_rolling(self):
        assert normalise_deadline("no deadline", "high")["type"] == "rolling"

    def test_ongoing_is_rolling(self):
        assert normalise_deadline("ongoing", "high")["type"] == "rolling"

    def test_tbc_keyword(self):
        result = normalise_deadline("TBC", "low")
        assert result["type"] == "tbc"
        assert result["date"] is None

    def test_to_be_confirmed(self):
        assert normalise_deadline("to be confirmed", "medium")["type"] == "tbc"

    def test_coming_soon(self):
        assert normalise_deadline("coming soon", "high")["type"] == "tbc"

    def test_tba(self):
        assert normalise_deadline("TBA", "high")["type"] == "tbc"

    def test_none_not_found_is_not_published(self):
        result = normalise_deadline(None, "not_found")
        assert result == {"date": None, "type": "not_published"}

    def test_none_low_confidence_is_unextracted(self):
        result = normalise_deadline(None, "low")
        assert result == {"date": None, "type": "unextracted"}

    def test_none_medium_confidence_is_unextracted(self):
        result = normalise_deadline(None, "medium")
        assert result == {"date": None, "type": "unextracted"}

    def test_dd_month_yyyy_confirmed(self):
        result = normalise_deadline("15 March 2027", "high")
        assert result["type"] == "confirmed"
        assert result["date"] == datetime.date(2027, 3, 15)

    def test_month_dd_yyyy_confirmed(self):
        result = normalise_deadline("March 15, 2027", "high")
        assert result["type"] == "confirmed"
        assert result["date"] == datetime.date(2027, 3, 15)

    def test_dd_mm_yyyy_slash_confirmed(self):
        result = normalise_deadline("15/03/2027", "high")
        assert result["type"] == "confirmed"
        assert result["date"] == datetime.date(2027, 3, 15)

    def test_unparseable_date_is_unextracted(self):
        result = normalise_deadline("someday eventually", "high")
        assert result["type"] == "unextracted"
        assert result["date"] is None


# ===========================================================================
# Country normalisation
# ===========================================================================

class TestNormaliseCountry:
    def test_united_kingdom_exact(self):
        assert normalise_country("United Kingdom") == "GB"

    def test_uk_abbreviation(self):
        assert normalise_country("uk") == "GB"

    def test_britain_fuzzy(self):
        # "britain" is in country_lookup.json directly
        assert normalise_country("Britain") == "GB"

    def test_democratic_republic_of_congo(self):
        assert normalise_country("Democratic Republic of the Congo") == "CD"

    def test_drc_abbreviation(self):
        assert normalise_country("DRC") == "CD"

    def test_unrecognised_returns_ot(self):
        assert normalise_country("Zxqwerty") == "OT"

    def test_none_returns_ot(self):
        assert normalise_country(None) == "OT"

    def test_empty_string_returns_ot(self):
        assert normalise_country("") == "OT"

    def test_kenya(self):
        assert normalise_country("Kenya") == "KE"

    def test_nigeria(self):
        assert normalise_country("Nigeria") == "NG"


# ===========================================================================
# Content hash
# ===========================================================================

class TestComputeContentHash:
    def test_returns_64_char_hex(self):
        h = compute_content_hash("Wellcome Trust", "Grant A")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_stable_across_calls(self):
        h1 = compute_content_hash("Wellcome Trust", "Grant A")
        h2 = compute_content_hash("Wellcome Trust", "Grant A")
        assert h1 == h2

    def test_case_insensitive(self):
        h1 = compute_content_hash("Wellcome Trust", "Grant A")
        h2 = compute_content_hash("WELLCOME TRUST", "grant a")
        assert h1 == h2

    def test_different_title_different_hash(self):
        h1 = compute_content_hash("Funder", "Title 1")
        h2 = compute_content_hash("Funder", "Title 2")
        assert h1 != h2

    def test_different_funder_different_hash(self):
        h1 = compute_content_hash("Funder A", "Title")
        h2 = compute_content_hash("Funder B", "Title")
        assert h1 != h2

    def test_unicode_normalisation(self):
        # NFKC: ligature ﬁ → fi
        h1 = compute_content_hash("Uni\ufb01ed Fund", "Grant")
        h2 = compute_content_hash("Unified Fund", "Grant")
        assert h1 == h2


# ===========================================================================
# Status auto-computation
# ===========================================================================

class TestComputeStatus:
    def _record(self, **overrides) -> dict:
        base = {
            "current_status_raw": None,
            "confidence_scores": _cs(current_status="not_found", grant_opening_date="not_found"),
            "application_deadline_type": "confirmed",
            "application_deadline": _FUTURE,
            "grant_opening_date": None,
        }
        base.update(overrides)
        return base

    def test_rule1_explicit_open_extracted(self):
        """R1: status_raw='open' + high confidence → 'Open', source='extracted'."""
        r = compute_status(self._record(
            current_status_raw="open",
            confidence_scores=_cs(current_status="high"),
        ))
        assert r == {"current_status": "Open", "status_source": "extracted"}

    def test_rule1_maps_to_controlled_vocab(self):
        """R1: mixed-case raw value maps to canonical capitalisation."""
        r = compute_status(self._record(
            current_status_raw="SUSPENDED",
            confidence_scores=_cs(current_status="high"),
        ))
        assert r["current_status"] == "Suspended"
        assert r["status_source"] == "extracted"

    def test_rule1_unmapped_becomes_others(self):
        """R1: status_raw not in vocab → 'Others'."""
        r = compute_status(self._record(
            current_status_raw="Paused",
            confidence_scores=_cs(current_status="high"),
        ))
        assert r["current_status"] == "Others"
        assert r["status_source"] == "extracted"

    def test_rule1_requires_high_confidence(self):
        """R1 only fires when confidence is exactly 'high'.
        When status_raw is present but confidence is 'medium', Rule 1 is skipped.
        Rules 2–4 all require status_raw is None, so the sentinel (Rule 5) is
        the correct fallback — the status cannot be safely computed."""
        r = compute_status(self._record(
            current_status_raw="Open",
            confidence_scores=_cs(current_status="medium"),
        ))
        assert r["current_status"] is None
        assert r["status_source"] == "sentinel"

    def test_rule2_rolling(self):
        """R2: rolling deadline + no status_raw → 'Rolling', 'computed'."""
        r = compute_status(self._record(
            application_deadline_type="rolling",
            application_deadline=None,
        ))
        assert r == {"current_status": "Rolling", "status_source": "computed"}

    def test_rule3_upcoming_future_opening(self):
        """R3: future opening date + high confidence → 'Upcoming'."""
        r = compute_status(self._record(
            confidence_scores=_cs(current_status="not_found", grant_opening_date="high"),
            grant_opening_date=_TOMORROW,
        ))
        assert r == {"current_status": "Upcoming", "status_source": "computed"}

    def test_rule3_confidence_gate_low_falls_through(self):
        """R3 confidence gate: low confidence on grant_opening_date → does NOT
        set Upcoming even if opening date is in the future."""
        r = compute_status(self._record(
            confidence_scores=_cs(
                current_status="not_found",
                grant_opening_date="low",
                application_deadline="high",
            ),
            grant_opening_date=_TOMORROW,
            application_deadline=_FUTURE,
            application_deadline_type="confirmed",
        ))
        # Rule 3 is skipped → Rule 4 fires → Open
        assert r["current_status"] == "Open"
        assert r["status_source"] == "computed"

    def test_rule3_beats_rule4_future_opening_and_deadline(self):
        """R3 precedes R4: a grant not yet opened cannot be 'Open'."""
        r = compute_status(self._record(
            confidence_scores=_cs(
                current_status="not_found",
                grant_opening_date="high",
                application_deadline="high",
            ),
            grant_opening_date=_TOMORROW,
            application_deadline=_FUTURE,
            application_deadline_type="confirmed",
        ))
        assert r["current_status"] == "Upcoming"

    def test_rule4a_past_deadline_closed(self):
        """R4a: confirmed past deadline → 'Closed', 'computed'."""
        r = compute_status(self._record(
            confidence_scores=_cs(current_status="not_found", application_deadline="high"),
            application_deadline=_PAST,
            application_deadline_type="confirmed",
        ))
        assert r == {"current_status": "Closed", "status_source": "computed"}

    def test_rule4b_future_deadline_open(self):
        """R4b: confirmed future deadline → 'Open', 'computed'."""
        r = compute_status(self._record(
            confidence_scores=_cs(current_status="not_found", application_deadline="high"),
            application_deadline=_FUTURE,
            application_deadline_type="confirmed",
        ))
        assert r == {"current_status": "Open", "status_source": "computed"}

    def test_rule5_sentinel_fallback(self):
        """R5: no confirmed high-confidence deadline → sentinel (None)."""
        r = compute_status(self._record(
            confidence_scores=_cs(
                current_status="not_found",
                application_deadline="low",
                grant_opening_date="not_found",
            ),
            application_deadline_type="unextracted",
            application_deadline=None,
        ))
        assert r == {"current_status": None, "status_source": "sentinel"}


# ===========================================================================
# Review flag
# ===========================================================================

class TestDetermineReviewFlag:
    def test_clean_record_no_flag(self):
        """No rules fire when all fields are high-confidence and no Others."""
        assert determine_review_flag(_clean_record()) is False

    def test_r1_grant_title_not_found(self):
        """R1: grant_title confidence 'not_found' → flag."""
        record = _clean_record(confidence_scores=_cs(grant_title="not_found"))
        assert determine_review_flag(record) is True

    def test_r1_grant_title_low(self):
        """R1: grant_title confidence 'low' → flag."""
        record = _clean_record(confidence_scores=_cs(grant_title="low"))
        assert determine_review_flag(record) is True

    def test_r2_funder_name_low(self):
        """R2: funder_name confidence 'low' → flag."""
        record = _clean_record(confidence_scores=_cs(funder_name="low"))
        assert determine_review_flag(record) is True

    def test_r3_deadline_low_and_not_excused(self):
        """R3: application_deadline confidence 'low' + type 'confirmed' → flag."""
        record = _clean_record(
            confidence_scores=_cs(application_deadline="low"),
            application_deadline_type="confirmed",
        )
        assert determine_review_flag(record) is True

    def test_r3_deadline_low_but_rolling_excused(self):
        """R3 excused: deadline confidence 'low' but type 'rolling' → no flag."""
        record = _clean_record(
            confidence_scores=_cs(application_deadline="low"),
            application_deadline_type="rolling",
        )
        assert determine_review_flag(record) is False

    def test_r4_current_status_others(self):
        """R4: current_status == 'Others' → flag."""
        record = _clean_record(current_status="Others")
        assert determine_review_flag(record) is True

    def test_r5_others_in_thematic_sectors(self):
        """R5: 'Others' in thematic_sectors → flag."""
        record = _clean_record(thematic_sectors=["Health and Medical Research", "Others"])
        assert determine_review_flag(record) is True

    def test_r5_organisation_types_not_in_r5(self):
        """R5 only covers thematic_sectors, geographic_focus, individual_eligibility
        (§5.2). organisation_types is excluded from R5; 'Others' there must not
        trigger the review flag."""
        record = _clean_record(organisation_types=["Others"])
        assert determine_review_flag(record) is False

    def test_r6_ai_focused_medium_does_not_trigger_at_low_threshold(self):
        """R6 fixed threshold: ai_focused 'medium' at 'low' threshold → no flag."""
        record = _clean_record(confidence_scores=_cs(ai_focused="medium"))
        assert determine_review_flag(record, threshold="low") is False

    def test_r6_ai_focused_low_triggers(self):
        """R6: ai_focused confidence 'low' → flag regardless of threshold."""
        record = _clean_record(confidence_scores=_cs(ai_focused="low"))
        assert determine_review_flag(record, threshold="low") is True

    def test_r6_ai_focused_not_found_triggers(self):
        """R6: ai_focused confidence 'not_found' → flag."""
        record = _clean_record(confidence_scores=_cs(ai_focused="not_found"))
        assert determine_review_flag(record) is True

    def test_r7_individuals_not_eligible_none(self):
        """R7: individuals_not_eligible is None → flag."""
        record = _clean_record(individuals_not_eligible=None)
        assert determine_review_flag(record) is True

    def test_medium_threshold_fires_on_medium_grant_title(self):
        """At 'medium' threshold, R1 fires for grant_title 'medium' confidence."""
        record = _clean_record(confidence_scores=_cs(grant_title="medium"))
        assert determine_review_flag(record, threshold="medium") is True
        assert determine_review_flag(record, threshold="low") is False

    def test_medium_threshold_r4_r7_unchanged(self):
        """R4-R7 are structural; the threshold does not affect them."""
        record = _clean_record(current_status="Others")
        assert determine_review_flag(record, threshold="low") is True
        assert determine_review_flag(record, threshold="medium") is True


# ===========================================================================
# Aggregate confidence score
# ===========================================================================

class TestAggregateConfidenceScore:
    def test_two_high(self):
        assert aggregate_confidence_score({"grant_title": "high", "funder_name": "high"}) == 6

    def test_mixed(self):
        # high=3, medium=2, low=1, not_found=0
        result = aggregate_confidence_score({
            "a": "high", "b": "medium", "c": "low", "d": "not_found"
        })
        assert result == 6  # 3+2+1+0

    def test_all_not_found(self):
        assert aggregate_confidence_score({"a": "not_found", "b": "not_found"}) == 0

    def test_unknown_label_contributes_zero(self):
        assert aggregate_confidence_score({"a": "unknown_value"}) == 0

    def test_empty_dict(self):
        assert aggregate_confidence_score({}) == 0


# ===========================================================================
# Geographic list normalisation (integration smoke test)
# ===========================================================================

class TestNormaliseGeographicList:
    def test_country_mapped(self):
        result = normalise_geographic_list(["Kenya"])
        assert "KE" in result["countries"]

    def test_supranational_expanded(self):
        result = normalise_geographic_list(["EU Member States"])
        assert "EU Member States" in result["regions"]
        assert "DE" in result["countries"]
        assert "FR" in result["countries"]

    def test_region_only_item(self):
        result = normalise_geographic_list(["South Asia"])
        assert "South Asia" in result["regions"]
        # "South Asia" is not a country → OT in countries
        assert "OT" in result["countries"]

    def test_unmatched_country_becomes_ot(self):
        result = normalise_geographic_list(["Zxqwerty"])
        assert "OT" in result["countries"]

    def test_empty_list(self):
        result = normalise_geographic_list([])
        assert result == {"regions": [], "countries": []}

    def test_none_list(self):
        result = normalise_geographic_list(None)
        assert result == {"regions": [], "countries": []}


# ===========================================================================
# Controlled vocabulary normalisation
# ===========================================================================

class TestNormaliseControlledVocab:
    _VOCAB = [
        "University / Higher Education Institution",
        "NGO",
        "Government / Public Authority",
        "Others",
    ]

    def test_exact_match_case_insensitive(self):
        result = normalise_controlled_vocab(["ngo"], self._VOCAB)
        assert result == ["NGO"]

    def test_canonical_capitalisation_preserved(self):
        result = normalise_controlled_vocab(
            ["university / higher education institution"], self._VOCAB
        )
        assert result == ["University / Higher Education Institution"]

    def test_unmatched_becomes_others(self):
        result = normalise_controlled_vocab(["Unknown Org Type"], self._VOCAB)
        assert result == ["Others"]

    def test_mixed_matched_and_unmatched(self):
        result = normalise_controlled_vocab(["NGO", "Alien Corp"], self._VOCAB)
        assert result == ["NGO", "Others"]

    def test_empty_list_returns_empty(self):
        assert normalise_controlled_vocab([], self._VOCAB) == []

    def test_none_returns_empty(self):
        assert normalise_controlled_vocab(None, self._VOCAB) == []
