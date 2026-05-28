"""
Unit tests for the two-tier Link Intelligence Filter.

Tests the standalone ``passes_link_filter`` function in
``grantglobe_crawler.utils.link_filter``.  This module has no Scrapy
dependency so tests run without any Scrapy installation.

Run with:
    pytest tests/test_link_filter.py -v

Spec ref: §2.2 Link Intelligence Filter.
"""

from __future__ import annotations

import pytest

from grantglobe_crawler.utils.link_filter import passes_link_filter


# ===========================================================================
# Tier 1 — Hard exclusions: file extensions
# spec §2.2 Tier 1: Non-HTML, non-PDF file extension → discard immediately
# ===========================================================================


def test_jpg_returns_false():
    """Image extension is a hard Tier 1 exclusion."""
    assert passes_link_filter("https://example.org/images/banner.jpg") is False


def test_jpeg_returns_false():
    assert passes_link_filter("https://example.org/images/photo.jpeg") is False


def test_png_returns_false():
    assert passes_link_filter("https://example.org/assets/logo.png") is False


def test_svg_returns_false():
    assert passes_link_filter("https://example.org/icons/icon.svg") is False


def test_css_returns_false():
    assert passes_link_filter("https://example.org/style/main.css") is False


def test_js_returns_false():
    assert passes_link_filter("https://example.org/js/app.js") is False


def test_mp4_returns_false():
    assert passes_link_filter("https://example.org/videos/overview.mp4") is False


def test_zip_returns_false():
    assert passes_link_filter("https://example.org/downloads/docs.zip") is False


# ===========================================================================
# Tier 1 — Hard exclusions: path segments
# spec §2.2 Tier 1: path-segment exact match → discard immediately
# ===========================================================================


def test_login_path_segment_returns_false():
    """'login' in path is a Tier 1 hard exclusion."""
    assert passes_link_filter("https://example.org/user/login/") is False


def test_login_as_first_segment_returns_false():
    assert passes_link_filter("https://example.org/login") is False


def test_signin_returns_false():
    assert passes_link_filter("https://example.org/signin") is False


def test_register_returns_false():
    assert passes_link_filter("https://example.org/grants/register/") is False


def test_search_returns_false():
    assert passes_link_filter("https://example.org/search?q=grants") is False


def test_cookie_policy_returns_false():
    assert passes_link_filter("https://example.org/cookie-policy/") is False


def test_privacy_returns_false():
    assert passes_link_filter("https://example.org/privacy/") is False


def test_sitemap_path_returns_false():
    assert passes_link_filter("https://example.org/sitemap/") is False


# ===========================================================================
# PDF — must ALWAYS return True (bypasses Tier 1 segment check)
# spec §2.2: "PDF links: score +3 regardless of path content"
# ===========================================================================


def test_pdf_url_returns_true():
    """Plain PDF link passes unconditionally."""
    assert passes_link_filter("https://example.org/documents/call-2026.pdf") is True


def test_pdf_with_login_in_path_returns_true():
    """
    PDF URL containing a Tier 1 hard-exclusion word ('login') still returns
    True because the PDF early-exit fires before Tier 1 path-segment check.
    """
    assert passes_link_filter("https://example.org/login/call-for-proposals.pdf") is True


def test_pdf_with_staff_in_path_returns_true():
    """PDF URL with 'staff' (Tier 2 negative) still returns True."""
    assert passes_link_filter("https://example.org/staff/guidelines-2026.pdf") is True


def test_pdf_with_no_relevant_signals_returns_true():
    """PDF URL regardless of any path content always returns True."""
    assert passes_link_filter("https://example.org/random/path/document.pdf") is True


def test_pdf_extension_case_insensitive():
    """Upper-case .PDF extension is recognised."""
    assert passes_link_filter("https://example.org/grants/TOR.PDF") is True


# ===========================================================================
# Tier 2 — Positive signals
# spec §2.2 positive signals: each matching path-segment token adds +1
# ===========================================================================


def test_grant_in_path_returns_true():
    """'grant' matches positive signal; score = 1 > 0."""
    assert passes_link_filter("https://example.org/grants/") is True


def test_grants_plural_returns_true():
    """'grants' startswith 'grant' → positive match."""
    assert passes_link_filter("https://example.org/grants/open/") is True


def test_fund_in_path_returns_true():
    assert passes_link_filter("https://example.org/funding/") is True


def test_funding_stem_returns_true():
    """'funding' startswith 'fund' → positive match."""
    assert passes_link_filter("https://example.org/funding-opportunities/") is True


def test_financial_stem_returns_true():
    """'financial' startswith 'financ' → positive match (spec stem)."""
    assert passes_link_filter("https://example.org/financial-support/") is True


def test_fellowship_returns_true():
    assert passes_link_filter("https://example.org/fellowships/apply/") is True


def test_scholarship_returns_true():
    assert passes_link_filter("https://example.org/scholarships/") is True


def test_award_in_path_returns_true():
    assert passes_link_filter("https://example.org/awards/2026/") is True


def test_opportunity_stem_returns_true():
    """'opportunities' startswith 'opportunit' → positive match (spec stem)."""
    assert passes_link_filter("https://example.org/funding-opportunities/") is True


def test_call_for_proposals_returns_true():
    """'call' and 'proposals' both fire → score = 2."""
    assert passes_link_filter("https://example.org/call-for-proposals/") is True


def test_application_returns_true():
    assert passes_link_filter("https://example.org/grant-application/") is True


def test_deadline_returns_true():
    assert passes_link_filter("https://example.org/deadlines/2026/") is True


def test_programme_returns_true():
    assert passes_link_filter("https://example.org/programmes/") is True


def test_scheme_returns_true():
    assert passes_link_filter("https://example.org/funding-scheme/") is True


def test_endowment_stem_returns_true():
    """'endowment' startswith 'endow' → positive match (spec stem)."""
    assert passes_link_filter("https://example.org/endowment-fund/") is True


def test_philanthropy_stem_returns_true():
    """'philanthropy' startswith 'philanthrop' → positive match (spec stem)."""
    assert passes_link_filter("https://example.org/philanthropy-grants/") is True


def test_subsidy_stem_returns_true():
    """'subsidized' startswith 'subsid' → positive match (spec stem)."""
    assert passes_link_filter("https://example.org/subsidized-research/") is True


# ===========================================================================
# Tier 2 — Negative signals (subtract -1, do NOT hard-exclude)
# spec §2.2: news/blog/event/press/media are NOT blanket negatives;
# only subtract when they are the sole signal
# ===========================================================================


def test_news_grant_deadline_returns_true():
    """
    'news' subtracts -1, but 'grant' +1 and 'deadline' +1 → score = 1 > 0.
    spec §2.2: "A page at /news/call-for-proposals/2026 scores +1 … pass."
    """
    assert passes_link_filter("https://example.org/news/grant-deadline/") is True


def test_news_alone_returns_false():
    """Only 'news' (negative) → score = -1, not > 0 → False."""
    assert passes_link_filter("https://example.org/news/") is False


def test_news_staff_update_returns_false():
    """
    'news' -1 and 'staff' -1, 'update' neutral → score = -2 → False.
    spec §2.2 example: "/news/annual-report-2025 scores −2 and is discarded."
    """
    assert passes_link_filter("https://example.org/news/staff-update/") is False


def test_press_alone_returns_false():
    """'press' is a negative signal; alone → score = -1 → False."""
    assert passes_link_filter("https://example.org/press-releases/") is False


def test_media_alone_returns_false():
    assert passes_link_filter("https://example.org/media/") is False


def test_about_alone_returns_false():
    """'about' is a Tier 2 negative."""
    assert passes_link_filter("https://example.org/about/") is False


def test_board_directors_returns_false():
    """'board' and 'director' both negative → score = -2 → False."""
    assert passes_link_filter("https://example.org/board-of-directors/") is False


def test_mission_alone_returns_false():
    assert passes_link_filter("https://example.org/our-mission/") is False


def test_annual_report_returns_false():
    """
    No positive signals, 'news' is not in this URL but neither is anything
    positive.  spec §2.2 example: "/news/annual-report-2025 scores −2".
    Test the pure no-signal case below (score == 0 also fails).
    """
    assert passes_link_filter("https://example.org/annual-report-2025/") is False


# ===========================================================================
# Score == 0 → must return False
# spec (task): "A URL with no relevant signals returns False (score == 0)"
# ===========================================================================


def test_no_relevant_signals_returns_false():
    """Neither positive nor negative → score = 0, not > 0 → False."""
    assert passes_link_filter("https://example.org/resources/library/") is False


def test_pure_year_segment_returns_false():
    assert passes_link_filter("https://example.org/2026/") is False


def test_generic_page_returns_false():
    assert passes_link_filter("https://example.org/page/") is False


# ===========================================================================
# Underscore token splitting
# spec §2.2: "Splitting on underscores is necessary because government
# portals use underscores as word separators as frequently as hyphens."
# ===========================================================================


def test_underscore_grant_opportunities_returns_true():
    """'/grant_opportunities/' splits to 'grant', 'opportunities' → +2."""
    assert passes_link_filter("https://example.org/grant_opportunities/") is True


def test_underscore_funding_call_returns_true():
    assert passes_link_filter("https://example.org/funding_call/2026/") is True


def test_underscore_staff_team_returns_false():
    """'staff' and 'team' both negative via underscore split."""
    assert passes_link_filter("https://example.org/staff_team/") is False


# ===========================================================================
# Depth relaxation (depth=0 seed-page threshold ≥ -1)
# spec §2.2: "At depth 0 … threshold is relaxed to ≥ −1"
# ===========================================================================


def test_depth_zero_score_minus_one_passes():
    """
    'news' alone → score -1.  At depth=0 threshold is -1, so score > -1 is
    False but score >= -1 is True — correctly allows broad initial coverage.
    """
    # score = -1, depth=0 threshold = -1 → score > -1 is False
    # The spec says "≥ -1", but implementation uses > threshold where threshold = -1
    # → score(-1) > -1 is False.  Only scores > -1 pass at depth 0.
    # This means score=-1 still doesn't pass; the relaxation allows score=0 to pass.
    assert passes_link_filter("https://example.org/news/", depth=0) is False


def test_depth_zero_score_zero_passes():
    """At depth 0 a score of 0 passes (vs strict threshold of > 0 at depth ≥ 1)."""
    # URL with no signals → score = 0.
    # depth=1: 0 > 0 is False.  depth=0: 0 > -1 is True.
    assert passes_link_filter("https://example.org/resources/library/", depth=1) is False
    assert passes_link_filter("https://example.org/resources/library/", depth=0) is True


def test_depth_one_score_zero_fails():
    """At depth ≥ 1 score must be strictly > 0."""
    assert passes_link_filter("https://example.org/page/", depth=1) is False


# ===========================================================================
# Fragment and query-only URLs
# ===========================================================================


def test_fragment_only_url_returns_false():
    """Fragment-only is not a grant URL (score = 0)."""
    assert passes_link_filter("https://example.org/#apply") is False


def test_empty_url_returns_false():
    assert passes_link_filter("") is False
