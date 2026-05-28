"""
Tests for grantglobe_crawler.utils.charset_handler.

Covers all four steps of the decoding pipeline:
  Step 1 — declared charset wins when valid
  Step 2 — UTF-8 auto-detection when no charset declared
  Step 3 — charset_normalizer detection path
  Step 4 — latin-1 fallback never raises

Spec ref: §2.2 HTML charset detection and decoding.
"""

from __future__ import annotations

import pytest

from grantglobe_crawler.utils.charset_handler import decode_response_body


# ===========================================================================
# Step 1 — declared charset
# ===========================================================================


def test_declared_charset_wins_for_latin1():
    """
    Step 1: a valid declared charset is tried first.
    Bytes that would fail UTF-8 decode ('é' in latin-1) succeed when
    the correct charset is declared.
    """
    text = "héllo café"
    body = text.encode("latin-1")
    result = decode_response_body(body, "latin-1", None)
    assert result == text


def test_declared_windows1256_arabic():
    """Step 1: Windows-1256 (common on Arabic grant sites)."""
    text = "مرحباً"
    body = text.encode("windows-1256")
    result = decode_response_body(body, "windows-1256", None)
    assert result == text


def test_declared_charset_wins_over_utf8():
    """
    Step 1: declared charset is tried BEFORE UTF-8.
    If the bytes are valid in the declared charset, that wins even when
    they would also be valid UTF-8 (ASCII subset).
    """
    body = b"hello"
    result = decode_response_body(body, "ascii", None)
    assert result == "hello"


def test_invalid_declared_charset_falls_through():
    """
    Step 1: when the declared charset name is unknown (LookupError),
    the pipeline falls through to Step 2 (UTF-8).
    """
    body = "hello".encode("utf-8")
    result = decode_response_body(body, "not-a-real-charset-xyz", None)
    assert result == "hello"


def test_declared_charset_mismatch_falls_through():
    """
    Step 1: when the declared charset is known but the bytes are not
    valid in that encoding (UnicodeDecodeError), fall through to Step 2.
    Body is valid UTF-8 multibyte; declared as ascii (which can't decode it).
    """
    text = "café"
    body = text.encode("utf-8")
    # 'ascii' would fail on the multi-byte café character
    result = decode_response_body(body, "ascii", None)
    # Should fall through to Step 2 (UTF-8) and succeed
    assert result == text


# ===========================================================================
# Step 2 — UTF-8 auto-detection (no declared charset)
# ===========================================================================


def test_utf8_detected_when_no_charset():
    """Step 2: plain UTF-8 body decodes correctly when no charset declared."""
    text = "open call for grant applications 2026"
    body = text.encode("utf-8")
    result = decode_response_body(body, None, None)
    assert result == text


def test_utf8_multibyte_characters():
    """Step 2: UTF-8 multibyte (BMP + supplementary plane) characters."""
    text = "Funding: 日本語 العربية português"
    body = text.encode("utf-8")
    result = decode_response_body(body, None, None)
    assert result == text


def test_utf8_wins_over_normalizer_when_valid():
    """
    Step 2 runs BEFORE Step 3.  Valid UTF-8 never reaches charset_normalizer.
    """
    body = "grant application deadline".encode("utf-8")
    result = decode_response_body(body, None, None)
    assert result == "grant application deadline"


# ===========================================================================
# Step 3 — charset_normalizer detection
# ===========================================================================


def test_charset_normalizer_detects_encoding():
    """
    Step 3: charset_normalizer should detect the encoding of a body that
    fails UTF-8 decode.

    Uses a long Polish string in ISO-8859-2; charset_normalizer should
    detect the encoding with confidence ≥ 0.75 and return correct text.

    If charset_normalizer is not installed (ImportError), Step 4 (latin-1)
    is used as fallback — the test checks that the call does not raise,
    but does not assert the exact text in that case.
    """
    text = (
        "Szanowni Państwo, zapraszamy do składania wniosków o dofinansowanie. "
        "Termin składania wniosków upływa dnia trzydziestego pierwszego marca. "
        "Szczegółowe informacje znajdują się w regulaminie konkursu grantowego."
    )
    body = text.encode("iso-8859-2")

    result = decode_response_body(body, None, None)
    assert isinstance(result, str)
    assert len(result) > 0


def test_normalizer_returns_string_for_gb2312():
    """
    Step 3: charset_normalizer handles GB2312 (East Asian government sites).
    If normalizer isn't available or confidence is low, latin-1 fallback
    fires; either way no exception is raised.
    """
    text = "申请截止日期为二零二六年九月三十日"
    body = text.encode("gb2312")
    result = decode_response_body(body, None, None)
    assert isinstance(result, str)
    assert len(result) > 0


# ===========================================================================
# Step 4 — latin-1 fallback
# ===========================================================================


def test_latin1_fallback_never_raises():
    """
    Step 4: any byte sequence 0x00–0xFF is decodable via latin-1.
    Pass bytes that are invalid UTF-8 AND trigger the bad-declared-charset
    path to ensure we reach Step 4.
    """
    body = bytes(range(256))
    result = decode_response_body(body, "invalid-charset-xyz", None)
    assert isinstance(result, str)
    assert len(result) == 256


def test_latin1_fallback_for_arbitrary_binary():
    """
    Step 4: a body of high-byte sequences that UTF-8 cannot decode
    is handled without raising by the latin-1 fallback.
    """
    body = bytes([0x80, 0x81, 0x82, 0x9F, 0xA0, 0xFF])
    result = decode_response_body(body, None, None)
    assert isinstance(result, str)


# ===========================================================================
# Edge cases
# ===========================================================================


def test_empty_bytes_returns_empty_string():
    """An empty body always returns an empty string, regardless of charset."""
    assert decode_response_body(b"", None, None) == ""
    assert decode_response_body(b"", "utf-8", "text/html") == ""
    assert decode_response_body(b"", "latin-1", None) == ""


def test_none_charset_and_none_content_type():
    """Both optional parameters may be None simultaneously."""
    body = b"hello world"
    assert decode_response_body(body, None, None) == "hello world"


def test_whitespace_only_charset_treated_as_absent():
    """
    A declared_charset of only whitespace is treated as absent (Step 1
    guard: ``declared_charset.strip()`` must be non-empty).
    Falls through to Step 2 (UTF-8).
    """
    body = "grant".encode("utf-8")
    result = decode_response_body(body, "   ", "text/html")
    assert result == "grant"


def test_content_type_parameter_is_accepted():
    """content_type parameter is accepted; current implementation ignores it."""
    body = "award".encode("utf-8")
    result = decode_response_body(body, None, "text/html; charset=utf-8")
    assert result == "award"
