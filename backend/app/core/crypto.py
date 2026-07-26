"""Registration field protection (SAATHI-366/448).

Approved model (Product decision 2026-07-26 §5): sensitive lookup values are
stored as a normalized keyed HMAC hash (for uniqueness/search — never reversible)
PLUS Fernet ciphertext for authorized display. Raw mobile/email/enrolment/DOB are
never stored in plaintext or written to logs/URLs/audit snapshots.
"""
from __future__ import annotations

import base64
import hashlib
import hmac

from cryptography.fernet import Fernet

from app.core.config import settings


def _key() -> bytes:
    return settings.registration_secret.get_secret_value().encode("utf-8")


def _fernet() -> Fernet:
    # Derive a stable 32-byte urlsafe key from the configured secret.
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(_key()).digest()))


def normalize(value: str, *, lower: bool = False) -> str:
    v = (value or "").strip()
    return v.lower() if lower else v


def keyed_hash(value: str, *, lower: bool = False) -> str:
    """Deterministic keyed hash for uniqueness/lookup. Not reversible."""
    norm = normalize(value, lower=lower).encode("utf-8")
    return hmac.new(_key(), norm, hashlib.sha256).hexdigest()


def encrypt(value: str) -> str:
    return _fernet().encrypt((value or "").encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode("ascii")).decode("utf-8")


def otp_verifier(code: str, *, salt: str) -> str:
    """Store only a keyed verifier for an OTP — never the raw code."""
    return hmac.new(_key(), f"{salt}:{code}".encode("utf-8"), hashlib.sha256).hexdigest()
