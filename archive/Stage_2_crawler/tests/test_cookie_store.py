"""
Tests for grantglobe_crawler.utils.cookie_store.CookieStore.

Spec ref: §2.5 Layer 4 — Cookie and session management.

Run with:
    pytest tests/test_cookie_store.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from grantglobe_crawler.utils.cookie_store import CookieStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def key() -> str:
    """Fresh Fernet key string for each test."""
    return Fernet.generate_key().decode()


@pytest.fixture()
def store(tmp_path: Path, key: str) -> CookieStore:
    """CookieStore backed by a fresh temp directory."""
    return CookieStore(tmp_path, key)


@pytest.fixture()
def sample_cookies() -> list[dict]:
    return [
        {"name": "session", "value": "abc123", "domain": "example.org", "path": "/"},
        {"name": "csrf", "value": "xyz789", "domain": "example.org", "path": "/"},
    ]


# ===========================================================================
# Round-trip: save → load
# ===========================================================================


def test_save_then_load_returns_original_cookies(store, sample_cookies):
    """save() + load() must return the original cookie list unchanged."""
    store.save("example.org", sample_cookies)
    loaded = store.load("example.org")
    assert loaded == sample_cookies


def test_save_empty_list_round_trips(store):
    """An empty cookie list is a valid value to save and load."""
    store.save("example.org", [])
    assert store.load("example.org") == []


def test_load_after_multiple_saves_returns_latest(store, sample_cookies):
    """A second save() overwrites the first; load() returns the latest."""
    store.save("example.org", sample_cookies)
    new_cookies = [{"name": "new", "value": "token", "domain": "example.org"}]
    store.save("example.org", new_cookies)
    loaded = store.load("example.org")
    assert loaded == new_cookies


def test_different_domains_are_isolated(store, sample_cookies):
    """Each domain's cookies are stored independently."""
    cookies_a = [{"name": "a", "value": "1"}]
    cookies_b = [{"name": "b", "value": "2"}]
    store.save("alpha.org", cookies_a)
    store.save("beta.org", cookies_b)
    assert store.load("alpha.org") == cookies_a
    assert store.load("beta.org") == cookies_b


# ===========================================================================
# Missing file
# ===========================================================================


def test_load_missing_domain_returns_none(store):
    """load() returns None when no .enc file exists for the domain."""
    result = store.load("nonexistent.org")
    assert result is None


# ===========================================================================
# Wrong key → InvalidToken → returns None
# ===========================================================================


def test_wrong_key_returns_none(tmp_path, key):
    """
    Decrypting with a different Fernet key raises InvalidToken.
    load() must catch it and return None (not re-raise).
    """
    store1 = CookieStore(tmp_path, key)
    store1.save("example.org", [{"name": "x", "value": "y"}])

    wrong_key = Fernet.generate_key().decode()
    store2 = CookieStore(tmp_path, wrong_key)
    result = store2.load("example.org")
    assert result is None


# ===========================================================================
# has_cookies
# ===========================================================================


def test_has_cookies_false_before_save(store):
    """has_cookies() returns False when no .enc file exists."""
    assert store.has_cookies("example.org") is False


def test_has_cookies_true_after_save(store, sample_cookies):
    """has_cookies() returns True after a successful save()."""
    store.save("example.org", sample_cookies)
    assert store.has_cookies("example.org") is True


def test_has_cookies_false_for_different_domain(store, sample_cookies):
    """has_cookies() distinguishes between domains."""
    store.save("example.org", sample_cookies)
    assert store.has_cookies("other.org") is False


# ===========================================================================
# index.json metadata
# ===========================================================================


def test_index_json_created_after_save(store, tmp_path, sample_cookies):
    """save() writes index.json in the store directory."""
    store.save("example.org", sample_cookies)
    index_path = tmp_path / "index.json"
    assert index_path.exists()


def test_index_json_contains_correct_count(store, tmp_path, sample_cookies):
    """index.json records the correct cookie count for the domain."""
    store.save("example.org", sample_cookies)
    index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert index["example.org"]["count"] == len(sample_cookies)


def test_index_json_contains_saved_at(store, tmp_path, sample_cookies):
    """index.json records a 'saved_at' ISO 8601 timestamp."""
    store.save("example.org", sample_cookies)
    index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert "saved_at" in index["example.org"]
    saved_at = index["example.org"]["saved_at"]
    # Basic ISO 8601 format check: starts with YYYY-MM-DD
    assert saved_at[:10].count("-") == 2


def test_index_json_does_not_contain_cookie_values(store, tmp_path, sample_cookies):
    """Cookie values must NEVER appear in index.json."""
    store.save("example.org", sample_cookies)
    index_text = (tmp_path / "index.json").read_text(encoding="utf-8")
    for cookie in sample_cookies:
        assert cookie["value"] not in index_text, (
            f"Cookie value '{cookie['value']}' found in index.json — "
            "this is a security violation."
        )


def test_index_json_updated_for_multiple_domains(store, tmp_path):
    """Multiple save() calls update index.json independently per domain."""
    store.save("alpha.org", [{"name": "a"}])
    store.save("beta.org", [{"name": "b"}, {"name": "c"}])
    index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert index["alpha.org"]["count"] == 1
    assert index["beta.org"]["count"] == 2


# ===========================================================================
# ValueError for missing key
# ===========================================================================


def test_none_key_raises_value_error(tmp_path):
    """Passing encryption_key=None must raise ValueError immediately."""
    with pytest.raises(ValueError, match="COOKIE_ENCRYPTION_KEY"):
        CookieStore(tmp_path, None)


def test_empty_string_key_raises_value_error(tmp_path):
    """An empty encryption_key string must raise ValueError."""
    with pytest.raises(ValueError, match="COOKIE_ENCRYPTION_KEY"):
        CookieStore(tmp_path, "")


def test_whitespace_only_key_raises_value_error(tmp_path):
    """A whitespace-only key is treated as absent → ValueError."""
    with pytest.raises(ValueError, match="COOKIE_ENCRYPTION_KEY"):
        CookieStore(tmp_path, "   ")


# ===========================================================================
# Store directory is created if absent
# ===========================================================================


def test_store_dir_created_automatically(tmp_path, key):
    """CookieStore creates the store directory tree if it does not exist."""
    nested = tmp_path / "deeply" / "nested" / "cookie_store"
    assert not nested.exists()
    CookieStore(nested, key)
    assert nested.exists()


# ===========================================================================
# Encrypted file must not contain plaintext cookie values
# ===========================================================================


def test_enc_file_does_not_contain_plaintext_value(store, tmp_path, sample_cookies):
    """
    The .enc file on disk must not contain cookie values in plaintext.
    This is a basic sanity check on Fernet encryption — the ciphertext
    should not contain the literal session token.
    """
    store.save("example.org", sample_cookies)
    enc_bytes = (tmp_path / "example.org.enc").read_bytes()
    for cookie in sample_cookies:
        assert cookie["value"].encode() not in enc_bytes, (
            f"Cookie value '{cookie['value']}' found unencrypted in .enc file."
        )
