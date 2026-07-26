"""SAATHI-366 C2/C3 — key-version stamping, rotation, and fail-closed crypto."""
from __future__ import annotations

import pytest

from app.core import crypto
from app.core.crypto import (
    CryptoConfigError,
    KeyRing,
    decrypt,
    encrypt,
    key_version,
    keyed_hash,
    override_keyring,
)


def test_ciphertext_is_version_stamped():
    override_keyring(KeyRing("v1", {"v1": b"key-one"}))
    ct = encrypt("9876543210")
    assert ct.startswith("v1:")
    assert key_version(ct) == "v1"
    assert decrypt(ct) == "9876543210"


def test_prior_key_rotation_decrypts_old_ciphertext():
    # Encrypt under the old active key v1.
    override_keyring(KeyRing("v1", {"v1": b"old-secret"}))
    old_ct = encrypt("date-of-birth")
    assert old_ct.startswith("v1:")
    # Rotate: v2 is now active, v1 retained as a prior key.
    override_keyring(KeyRing("v2", {"v2": b"new-secret", "v1": b"old-secret"}))
    # Old ciphertext still decrypts (active + prior rotation support)...
    assert decrypt(old_ct) == "date-of-birth"
    # ...and new ciphertext is stamped with the new active version.
    new_ct = encrypt("date-of-birth")
    assert new_ct.startswith("v2:")
    assert decrypt(new_ct) == "date-of-birth"


def test_lookup_hash_stays_stable_when_encryption_key_rotates():
    lookup = b"stable-lookup-key"
    override_keyring(KeyRing("v1", {"v1": b"old-secret"}, lookup_secret=lookup))
    old_hash = keyed_hash("9876543210")
    override_keyring(
        KeyRing(
            "v2",
            {"v2": b"new-secret", "v1": b"old-secret"},
            lookup_secret=lookup,
        )
    )
    assert keyed_hash("9876543210") == old_hash


def test_fail_closed_in_production_with_dev_default(monkeypatch):
    override_keyring(None)  # fall back to settings-derived key ring
    from app.core.config import settings

    monkeypatch.setattr(settings, "app_env", "production", raising=False)
    monkeypatch.setattr(
        settings, "registration_secret", type(settings.registration_secret)("dev-registration-secret-change-me"), raising=False
    )
    with pytest.raises(CryptoConfigError):
        crypto.assert_crypto_ready()


def test_production_ok_with_strong_secret(monkeypatch):
    override_keyring(None)
    from pydantic import SecretStr

    from app.core.config import settings

    monkeypatch.setattr(settings, "app_env", "production", raising=False)
    monkeypatch.setattr(settings, "registration_secret", SecretStr("a-strong-production-secret"), raising=False)
    monkeypatch.setattr(settings, "registration_lookup_secret", SecretStr("a-separate-strong-lookup-secret"), raising=False)
    crypto.assert_crypto_ready()  # no raise
    ct = encrypt("x")
    assert decrypt(ct) == "x"
