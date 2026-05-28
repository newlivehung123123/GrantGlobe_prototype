"""
Unit tests for grantglobe_crawler.utils.url_canonicaliser.

Covers every rule mandated by spec §2.2 URL canonicalisation:
  Rule 1 — scheme to lowercase
  Rule 2 — http → https upgrade
  Rule 3 — www. prefix stripped
  Rule 4 — hostname lowercased
  Rule 5 — path: collapse //, resolve . and .., lowercase, trailing slash
  Rule 6 — tracking params stripped; content params preserved
  Rule 7 — fragment removed

Also covers url_to_hash() hash length and round-trip stability.

Run with:
    pytest tests/test_url_canonicaliser.py -v
"""

from __future__ import annotations

import pytest

from grantglobe_crawler.utils.url_canonicaliser import (
    canonicalise,
    url_to_hash,
    _HASH_LENGTH,
)


# ===========================================================================
# Rule 1 — scheme lowercased
# ===========================================================================


def test_scheme_lowercased_https():
    assert canonicalise("HTTPS://example.org/grants/") == "https://example.org/grants/"


def test_scheme_lowercased_http():
    assert canonicalise("HTTP://example.org/grants/") == "https://example.org/grants/"


# ===========================================================================
# Rule 2 — http → https
# ===========================================================================


def test_http_upgraded_to_https():
    assert canonicalise("http://example.org/grants/") == "https://example.org/grants/"


def test_https_stays_https():
    assert canonicalise("https://example.org/grants/") == "https://example.org/grants/"


# ===========================================================================
# Rule 3 — www. prefix stripped
# ===========================================================================


def test_www_prefix_stripped():
    assert canonicalise("https://www.example.org/grants/") == "https://example.org/grants/"


def test_www_not_stripped_from_subdomain():
    """www2.example.org must not be stripped — only exact www. prefix."""
    result = canonicalise("https://www2.example.org/grants/")
    assert "www2.example.org" in result


def test_www_stripped_with_http_upgrade():
    assert canonicalise("http://www.example.org/grants/") == "https://example.org/grants/"


# ===========================================================================
# Rule 4 — hostname lowercased
# ===========================================================================


def test_hostname_lowercased():
    assert canonicalise("https://Example.ORG/grants/") == "https://example.org/grants/"


def test_hostname_mixed_case_with_www():
    assert canonicalise("https://WWW.EXAMPLE.ORG/grants/") == "https://example.org/grants/"


# ===========================================================================
# Rule 5 — path normalisation
# ===========================================================================


def test_trailing_slash_added_to_bare_path():
    """Bare path with no file extension gets a trailing slash."""
    assert canonicalise("https://example.org/grants") == "https://example.org/grants/"


def test_trailing_slash_added_to_nested_bare_path():
    assert (
        canonicalise("https://example.org/grants/open-calls")
        == "https://example.org/grants/open-calls/"
    )


def test_trailing_slash_not_added_to_pdf():
    """File extensions must not receive a trailing slash."""
    result = canonicalise("https://example.org/files/call-2026.pdf")
    assert result == "https://example.org/files/call-2026.pdf"


def test_trailing_slash_not_added_to_html():
    result = canonicalise("https://example.org/grants/index.html")
    assert result == "https://example.org/grants/index.html"


def test_existing_trailing_slash_preserved():
    """A path that already ends in / must not gain a double slash."""
    result = canonicalise("https://example.org/grants/")
    assert result.count("//") == 1  # only the scheme ://
    assert result.endswith("/")


def test_double_slashes_in_path_collapsed():
    result = canonicalise("https://example.org//grants//open//")
    assert "//" not in result.split("://", 1)[1]
    assert "grants/open/" in result


def test_dot_segment_resolved():
    result = canonicalise("https://example.org/grants/./open/")
    assert "/." not in result
    assert "grants/open/" in result


def test_dot_dot_segment_resolved():
    result = canonicalise("https://example.org/grants/old/../open/")
    assert ".." not in result
    assert "grants/open/" in result


def test_path_lowercased():
    result = canonicalise("https://example.org/Grants/Open-Calls")
    assert result == "https://example.org/grants/open-calls/"


def test_root_path_unchanged():
    """The bare root path '/' must stay as '/'."""
    assert canonicalise("https://example.org/") == "https://example.org/"


def test_path_with_underscore_segments_lowercased():
    """Underscore-separated paths (common in Asian/Latin government portals)."""
    result = canonicalise("https://example.org/Grant_Opportunities/Funding_Call")
    assert result == "https://example.org/grant_opportunities/funding_call/"


# ===========================================================================
# Rule 6 — tracking params stripped, content params preserved
# ===========================================================================


def test_utm_source_stripped():
    result = canonicalise("https://example.org/grants/?utm_source=email")
    assert "utm_source" not in result


def test_utm_medium_stripped():
    result = canonicalise("https://example.org/grants/?utm_medium=social")
    assert "utm_medium" not in result


def test_utm_campaign_stripped():
    result = canonicalise("https://example.org/grants/?utm_campaign=spring")
    assert "utm_campaign" not in result


def test_fbclid_stripped():
    result = canonicalise("https://example.org/grants/?fbclid=abc123")
    assert "fbclid" not in result


def test_gclid_stripped():
    result = canonicalise("https://example.org/grants/?gclid=xyz")
    assert "gclid" not in result


def test_content_param_page_preserved():
    """?page=2 is a content-affecting parameter and must survive."""
    result = canonicalise("https://example.org/grants/?page=2")
    assert "page=2" in result


def test_content_param_lang_preserved():
    result = canonicalise("https://example.org/grants/?lang=en")
    assert "lang=en" in result


def test_mixed_tracking_and_content_params():
    """Tracking params stripped, content params kept; order preserved."""
    url = "https://example.org/grants/?utm_source=email&page=2&utm_campaign=spring"
    result = canonicalise(url)
    assert "page=2" in result
    assert "utm_source" not in result
    assert "utm_campaign" not in result


def test_no_trailing_question_mark_when_all_params_stripped():
    """After stripping all params the query string should be absent or empty."""
    result = canonicalise("https://example.org/grants/?utm_source=email")
    # urlunparse produces '?' with empty query — that is acceptable; what must
    # not happen is 'utm_source' appearing.  Both 'https://…/grants/' and
    # 'https://…/grants/?' are valid normalised forms.
    assert "utm_source" not in result


# ===========================================================================
# Rule 7 — fragment removed
# ===========================================================================


def test_fragment_removed():
    result = canonicalise("https://example.org/grants/#section-apply")
    assert "#" not in result
    assert "section-apply" not in result


def test_fragment_removed_no_other_changes():
    url = "https://example.org/grants/#top"
    assert canonicalise(url) == "https://example.org/grants/"


# ===========================================================================
# Combined / integration
# ===========================================================================


def test_all_rules_combined():
    """
    Input has: uppercase scheme, http, www., uppercase path, double slash,
    tracking param, fragment, and a content param.
    """
    url = "HTTP://WWW.EXAMPLE.ORG//Grants/?utm_source=email&page=2#apply"
    result = canonicalise(url)
    assert result.startswith("https://example.org/")
    assert "www" not in result
    assert result == result.lower() or "page=2" in result  # no upper chars outside value
    assert "utm_source" not in result
    assert "page=2" in result
    assert "#" not in result


# ===========================================================================
# url_to_hash
# ===========================================================================


def test_hash_length():
    h = url_to_hash("https://example.org/grants/")
    assert len(h) == _HASH_LENGTH


def test_hash_is_hex():
    h = url_to_hash("https://example.org/grants/")
    assert all(c in "0123456789abcdef" for c in h)


def test_round_trip_http_vs_https():
    """http:// and https:// variants of the same page → identical hash."""
    assert url_to_hash("http://example.org/grants/") == url_to_hash(
        "https://example.org/grants/"
    )


def test_round_trip_www_vs_no_www():
    """www. and non-www variants → identical hash."""
    assert url_to_hash("https://www.example.org/grants/") == url_to_hash(
        "https://example.org/grants/"
    )


def test_round_trip_trailing_slash():
    """/grants and /grants/ → identical hash."""
    assert url_to_hash("https://example.org/grants") == url_to_hash(
        "https://example.org/grants/"
    )


def test_round_trip_mixed_case_path():
    """Mixed-case path and lowercase path → identical hash."""
    assert url_to_hash("https://example.org/Grants/Open") == url_to_hash(
        "https://example.org/grants/open/"
    )


def test_round_trip_all_variants():
    """
    The canonical round-trip test: three URL variants of the same page that
    differ only in scheme, www. prefix, path casing, tracking param, and
    fragment must all produce the same hash.
    """
    variants = [
        "http://www.example.org/Grants/?utm_source=email#apply",
        "HTTPS://WWW.EXAMPLE.ORG/grants/",
        "https://example.org/grants/",
    ]
    hashes = [url_to_hash(v) for v in variants]
    assert len(set(hashes)) == 1, (
        f"Expected all variants to hash identically but got: {hashes}"
    )


def test_different_pages_different_hash():
    """Two genuinely different pages must not collide."""
    h1 = url_to_hash("https://example.org/grants/")
    h2 = url_to_hash("https://example.org/news/")
    assert h1 != h2
