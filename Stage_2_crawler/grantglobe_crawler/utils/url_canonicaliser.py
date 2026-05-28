"""
URL canonicalisation — spec §2.2 URL canonicalisation.

Applies all seven rules in order before computing the SHA-256 URL hash used
as the filename stem throughout the raw_cache/ tree.

Imported by:
  - Spider request construction
  - Pre-flight manifest writer
  - Change-detection pipeline
  - Any code that needs a stable URL identity
"""

from __future__ import annotations

import hashlib
import posixpath
import re
from urllib.parse import (
    parse_qsl,
    urlencode,
    urlparse,
    urlunparse,
)

# ---------------------------------------------------------------------------
# Settings import — gracefully degrade for isolated tests that don't have the
# full Scrapy project in sys.path.
# ---------------------------------------------------------------------------
try:
    from grantglobe_crawler import settings as _settings

    _TRACKING_PARAMS: frozenset[str] = frozenset(
        p.lower() for p in _settings.URL_TRACKING_PARAMS
    )
    _HASH_LENGTH: int = _settings.URL_HASH_LENGTH
except Exception:  # ImportError or AttributeError during early bootstrap
    _TRACKING_PARAMS = frozenset(
        [
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_term",
            "utm_content",
            "fbclid",
            "gclid",
            "msclkid",
            "twclid",
            "igshid",
        ]
    )
    _HASH_LENGTH = 16

# Matches a file extension in the final path segment: a literal dot followed
# by 1–10 alphanumeric characters at the end of the string.
# e.g.  report.pdf, index.html, page.php, data.xml  →  match
#       /grants/, /open-calls, ..  →  no match
_EXTENSION_RE = re.compile(r"\.[a-zA-Z0-9]{1,10}$")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def canonicalise(url: str) -> str:
    """
    Apply the seven canonicalisation rules from spec §2.2 in order and return
    the normalised URL string.

    Rules:
      1. Convert scheme to lowercase.
      2. Upgrade http → https.
      3. Strip ``www.`` prefix from hostname.
      4. Lowercase the entire hostname.
      5. Normalise path: collapse double slashes, resolve ``.`` and ``..``
         segments, lowercase, add trailing slash to bare paths.
      6. Strip tracking query parameters (``URL_TRACKING_PARAMS`` in settings)
         while preserving all content-affecting parameters.
      7. Remove the URL fragment.

    >>> canonicalise("HTTP://WWW.EXAMPLE.ORG/Grants?utm_source=x#apply")
    'https://example.org/grants/?'

    The returned string is suitable for direct SHA-256 hashing.  It is also
    stored in ``.meta.json`` alongside the original URL so the mapping is
    always recoverable.
    """
    if not url or not url.strip():
        return url

    parsed = urlparse(url.strip())

    # ── Rule 1: scheme to lowercase ─────────────────────────────────────────
    scheme = parsed.scheme.lower()

    # ── Rule 2: http → https ─────────────────────────────────────────────────
    if scheme == "http":
        scheme = "https"

    # ── Rules 3 & 4: strip www., lowercase hostname ───────────────────────
    # parsed.hostname is always lowercase and never includes a port number.
    hostname: str = parsed.hostname or ""
    if hostname.startswith("www."):
        hostname = hostname[4:]
    # Reconstruct netloc, preserving port if present (uncommon for grant sites
    # but correct to preserve for canonicalisation stability).
    netloc = f"{hostname}:{parsed.port}" if parsed.port else hostname

    # ── Rule 5: normalise path ────────────────────────────────────────────────
    path = parsed.path or "/"
    # posixpath.normpath: collapses consecutive slashes, resolves . and ..
    # Side-effect: removes trailing slashes (except on bare "/").
    path = posixpath.normpath(path)
    if path == ".":  # normpath("") → "."
        path = "/"
    # POSIX normpath intentionally preserves a leading '//' (it has a defined
    # meaning on some POSIX systems), but that construction is never valid in
    # an HTTP URL path.  Collapse any leading double-slash to a single slash.
    if path.startswith("//"):
        path = "/" + path.lstrip("/")
    # Lowercase after normpath so case-folding doesn't interfere with . and ..
    # resolution (path segments are case-insensitive on case-insensitive
    # filesystems, and the spec mandates uniform lowercase representation).
    path = path.lower()
    # Add trailing slash to bare paths.  A "bare path" is one whose final
    # segment has no file extension (e.g. /grants, /open-calls).  Paths with
    # an extension (e.g. /files/report.pdf, /index.html) are left unchanged.
    if path != "/" and not _EXTENSION_RE.search(path.rsplit("/", 1)[-1]):
        path = path + "/"

    # ── Rule 6: strip tracking query parameters ───────────────────────────
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    kept = [(k, v) for k, v in pairs if k.lower() not in _TRACKING_PARAMS]
    # urlencode with quote_via=str avoids double-encoding already-encoded chars.
    query = urlencode(kept)

    # ── Rule 7: remove fragment ───────────────────────────────────────────
    fragment = ""

    return urlunparse((scheme, netloc, path, parsed.params, query, fragment))


def url_to_hash(url: str) -> str:
    """
    Canonicalise *url* and return the first ``URL_HASH_LENGTH`` hex characters
    of its SHA-256 digest.

    This is the filename stem used throughout the cache:
      ``pages/{url_to_hash(url)}.html``
      ``pages/{url_to_hash(url)}.meta.json``
      ``pages/{url_to_hash(url)}.jsonld``

    SHA-256 is used for its negligible collision probability at GrantGlobe's
    scale (< 10⁶ URLs) and deterministic output across platforms.
    Spec ref: §2.6 Content deduplication.
    """
    normalised = canonicalise(url)
    return hashlib.sha256(normalised.encode()).hexdigest()[:_HASH_LENGTH]
