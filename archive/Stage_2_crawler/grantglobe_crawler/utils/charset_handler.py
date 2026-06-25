"""
HTML charset detection and decoding pipeline — spec §2.2.

All HTML responses from the crawler pass through ``decode_response_body``
before text is written to the cache.  Non-UTF-8 pages are common across
several of GrantGlobe's source regions:

- Arabic grant sites frequently use Windows-1256
- Some East Asian government portals use GB2312 or EUC-KR
- Some Eastern European sources use ISO-8859-2

**charset-normalizer** is used in preference to ``chardet`` because it is:
  1. More accurate on Arabic and CJK scripts.
  2. The library used internally by the ``requests`` library.
  3. Actively maintained and ships with Python's ``pip`` by default.

All decoded text is returned as native Python ``str`` (UTF-8 in memory).
It is the caller's responsibility to encode as UTF-8 before writing to disk.

Spec ref: §2.2 HTML charset detection and decoding (four-step pipeline).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# charset_normalizer import — graceful degradation if not installed.
# ---------------------------------------------------------------------------
try:
    from charset_normalizer import from_bytes as _cn_from_bytes

    _CHARSET_NORMALIZER_AVAILABLE = True
except ImportError:  # pragma: no cover
    _CHARSET_NORMALIZER_AVAILABLE = False
    logger.warning(
        "charset_normalizer is not installed; step 3 of the charset detection "
        "pipeline will be skipped.  Install with: pip install charset-normalizer"
    )


def decode_response_body(
    body: bytes,
    declared_charset: str | None,
    content_type: str | None,  # noqa: ARG001 — reserved for future heuristics
) -> str:
    """
    Decode *body* bytes to a Python ``str`` using the four-step pipeline
    defined in spec §2.2.

    Parameters
    ----------
    body:
        Raw HTTP response body bytes.
    declared_charset:
        The charset value extracted from the ``Content-Type`` header or
        the HTML ``<meta charset>`` tag.  Pass ``None`` or empty string
        when not available.
    content_type:
        Full ``Content-Type`` header value, e.g.
        ``'text/html; charset=windows-1256'``.
        Reserved for future use; current steps rely on *declared_charset*
        directly.

    Returns
    -------
    str
        Decoded text.  Empty string if *body* is empty.

    Steps
    -----
    1. If *declared_charset* is non-empty, try ``body.decode(declared_charset)``.
       Succeeds → return immediately.
    2. Try ``body.decode('utf-8')``.
       Succeeds → return immediately.
    3. Run ``charset_normalizer.from_bytes(body)`` to auto-detect encoding.
       If a result exists and ``confidence >= 0.75``, decode with it.
    4. Fallback — ``body.decode('latin-1', errors='replace')``.
       latin-1 maps every byte 0x00–0xFF to a character; it never raises.

    Spec ref: §2.2 "charset detection and normalisation step".
    """
    if not body:
        return ""

    # ── Step 1: declared charset ──────────────────────────────────────────
    if declared_charset and declared_charset.strip():
        charset = declared_charset.strip()
        try:
            return body.decode(charset)
        except (UnicodeDecodeError, LookupError):
            logger.debug(
                "Declared charset %r failed; falling through to UTF-8 detection",
                charset,
            )

    # ── Step 2: UTF-8 ─────────────────────────────────────────────────────
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        pass  # not UTF-8; continue

    # ── Step 3: charset_normalizer auto-detection ─────────────────────────
    if _CHARSET_NORMALIZER_AVAILABLE:
        try:
            results = _cn_from_bytes(body)
            if results:
                best = results[0]  # Results is sorted best-first by confidence
                chaos = float(best.chaos)
                confidence = 1.0 - chaos
                if confidence >= 0.75:
                    encoding = best.encoding
                    logger.debug(
                        "charset_normalizer detected %r (confidence %.2f)",
                        encoding,
                        confidence,
                    )
                    try:
                        return body.decode(encoding)
                    except (UnicodeDecodeError, LookupError):
                        logger.debug(
                            "charset_normalizer encoding %r still failed; "
                            "falling through to latin-1",
                            encoding,
                        )
                else:
                    logger.debug(
                        "charset_normalizer confidence %.2f < 0.75; "
                        "skipping auto-detection result",
                        confidence,
                    )
        except Exception as exc:  # noqa: BLE001
            logger.debug("charset_normalizer raised unexpectedly: %s", exc)

    # ── Step 4: latin-1 fallback (lossless for all byte values) ──────────
    logger.debug("Falling back to latin-1 with errors='replace'")
    return body.decode("latin-1", errors="replace")
