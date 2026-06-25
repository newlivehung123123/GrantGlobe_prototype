"""
Encrypted cookie persistence — spec §2.5 Layer 4.

Session cookies are live authentication-equivalent tokens.  Storing them in
plain text creates risk of accidental exposure via version control commits,
log aggregation, or file sharing.

This module provides ``CookieStore``, which persists cookies in a per-domain
encrypted file (``cookie_store/{domain}.enc``) using Fernet symmetric
encryption.  The encryption key is loaded from the ``COOKIE_ENCRYPTION_KEY``
environment variable (never stored on disk alongside the encrypted data).

An ``index.json`` in the store directory records only non-sensitive metadata
per domain (save timestamp, cookie count) — never the cookie values
themselves.

Spec ref: §2.5 Layer 4 — Cookie and session management.

Usage::

    from grantglobe_crawler.utils.cookie_store import CookieStore

    store = CookieStore("/path/to/cookie_store", encryption_key)
    store.save("example.org", [{"name": "session", "value": "abc"}])
    cookies = store.load("example.org")
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# cryptography import — raise immediately with a clear message if absent.
# ---------------------------------------------------------------------------
try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError as _fernet_import_error:
    raise ImportError(
        "The 'cryptography' package is required for CookieStore.  "
        "Install it with: pip install cryptography"
    ) from _fernet_import_error


class CookieStore:
    """
    Fernet-encrypted per-domain cookie store.

    Parameters
    ----------
    store_dir:
        Directory where ``{domain}.enc`` files and ``index.json`` are written.
        Created automatically if it does not exist.
    encryption_key:
        Fernet-compatible symmetric key as a ``str`` (URL-safe base64,
        32 bytes before encoding) or ``bytes``.  Must not be ``None`` or
        empty — if absent, ``ValueError`` is raised immediately so the
        misconfiguration is caught at construction time rather than silently
        omitting encryption.

        Generate a new key once:
            python -c "from cryptography.fernet import Fernet; \\
                       print(Fernet.generate_key().decode())"
        Store the output as ``COOKIE_ENCRYPTION_KEY=<value>`` in ``.env``.

    Spec ref: §2.5 Layer 4 — "cookies are persisted in a dedicated,
    permission-restricted file: cookie_store/{domain}.enc, encrypted at
    rest using Python's cryptography library (Fernet symmetric encryption
    with a key stored in an environment variable, never on disk alongside
    the encrypted data)."
    """

    def __init__(
        self,
        store_dir: str | Path,
        encryption_key: str | bytes | None,
    ) -> None:
        if not encryption_key or (isinstance(encryption_key, str) and not encryption_key.strip()):
            raise ValueError(
                "COOKIE_ENCRYPTION_KEY must be set in .env before using CookieStore.  "
                "Generate a new key with: "
                "python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\""
            )
        self._store_dir = Path(store_dir)
        self._store_dir.mkdir(parents=True, exist_ok=True)

        key_bytes: bytes = (
            encryption_key.encode("utf-8")
            if isinstance(encryption_key, str)
            else encryption_key
        )
        self._fernet = Fernet(key_bytes)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(self, domain: str, cookies: list[dict]) -> None:
        """
        Serialise *cookies* to JSON, encrypt, and write atomically to
        ``{store_dir}/{domain}.enc``.

        Also updates ``{store_dir}/index.json`` with non-sensitive metadata
        (save timestamp and cookie count only — never cookie values).

        Parameters
        ----------
        domain:
            Registered domain key, e.g. ``'example.org'``.
        cookies:
            List of cookie dicts in the format used by Playwright /
            Scrapy's cookie jar.

        Spec ref: §2.5 Layer 4 — "persisted in a dedicated, permission-
        restricted file".
        """
        cookie_json: bytes = json.dumps(cookies, ensure_ascii=False).encode("utf-8")
        encrypted: bytes = self._fernet.encrypt(cookie_json)

        enc_path = self._store_dir / f"{domain}.enc"
        _write_bytes_atomic(enc_path, encrypted)
        logger.debug("Saved %d cookie(s) for %s", len(cookies), domain)

        self._update_index(domain, len(cookies))

    def load(self, domain: str) -> list[dict] | None:
        """
        Decrypt and deserialise cookies for *domain*.

        Returns
        -------
        list[dict]
            The cookie list, or ``None`` if:
            - The ``.enc`` file does not exist.
            - Decryption fails (wrong key → ``InvalidToken``).

        Spec ref: §2.5 Layer 4 — "valid stored cookies are decrypted and
        injected into the new Playwright browser context before the first
        request".
        """
        enc_path = self._store_dir / f"{domain}.enc"
        if not enc_path.exists():
            return None

        try:
            encrypted = enc_path.read_bytes()
            decrypted: bytes = self._fernet.decrypt(encrypted)
            cookies: list[dict] = json.loads(decrypted.decode("utf-8"))
            logger.debug("Loaded %d cookie(s) for %s", len(cookies), domain)
            return cookies
        except InvalidToken:
            logger.warning(
                "Fernet InvalidToken for domain '%s' — the encryption key may "
                "have changed.  Returning None so the caller can start a fresh "
                "session.  The corrupted file has NOT been deleted.",
                domain,
            )
            return None
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not load cookies for %s: %s", domain, exc)
            return None

    def has_cookies(self, domain: str) -> bool:
        """
        Return ``True`` if an encrypted cookie file exists for *domain*.

        Does not validate the file or check whether the key can decrypt it —
        call :meth:`load` for that.

        Spec ref: §2.5 Layer 4 — "``crawl_manifest.json`` stores only a
        boolean ``has_stored_cookies: true``".
        """
        return (self._store_dir / f"{domain}.enc").exists()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _update_index(self, domain: str, count: int) -> None:
        """
        Update ``{store_dir}/index.json`` with save metadata for *domain*.

        The index stores ONLY metadata: ``saved_at`` (ISO 8601 UTC) and
        ``count`` (number of cookies).  Cookie values are never stored in
        the index.

        Spec ref: §2.5 Layer 4 — "The encryption key is never logged."
        """
        index_path = self._store_dir / "index.json"

        index: dict = {}
        if index_path.exists():
            try:
                with index_path.open(encoding="utf-8") as fh:
                    index = json.load(fh)
            except (json.JSONDecodeError, OSError):
                index = {}

        index[domain] = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "count": count,
        }

        index_bytes = json.dumps(index, ensure_ascii=False, indent=2).encode("utf-8")
        _write_bytes_atomic(index_path, index_bytes)


# ---------------------------------------------------------------------------
# Module-level atomic write helper
# ---------------------------------------------------------------------------


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    """
    Write *data* bytes to *path* atomically using a temp-file rename.

    Guarantees that a partial write never corrupts an existing file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
