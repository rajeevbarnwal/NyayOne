"""NYAY-12 login-email identity policy (documented, provider-agnostic).

Policy version ``nyay12-email-identity-policy.v1`` (see
docs/architecture/nyay12-verified-email-identity/EMAIL_IDENTITY_CONTRACT.md):

1. Unicode NFC normalization, then trim of leading/trailing ASCII whitespace.
2. Full Unicode ``casefold`` of the whole address. Two addresses that differ
   only by case are one identity.
3. Shape: exactly one ``@``; non-empty local part without whitespace; domain
   with at least one dot and a final label of two or more characters; no
   whitespace anywhere; at most 254 code points after normalization.
4. **No** plus-tag stripping, dot removal or other provider-specific rewriting.
   ``first+tag@example.edu`` and ``first@example.edu`` are distinct identities.
5. Uniqueness is enforced on the keyed hash of the normalized address: at most
   one *verified* owner per address (database partial unique index), at most
   one *primary* identity per user, at most one live claim per (user, address).

Raw addresses are never persisted or logged; only the keyed hash and Fernet
ciphertext are stored, and the owner-facing projection uses ``mask_login_email``.
"""
from __future__ import annotations

import re
import unicodedata

from app.core.crypto import keyed_hash

EMAIL_IDENTITY_POLICY_VERSION = "nyay12-email-identity-policy.v1"
LOGIN_EMAIL_MAX_LENGTH = 254
LOGIN_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")
EMAIL_IDENTITY_HASH_NAMESPACE = "nyay12:email-identity:v1:"
EMAIL_MASK_FILL = "•••••"


def normalize_login_email(value: str | None) -> str:
    """Return the canonical login-email identity or raise ``ValueError``."""

    if not isinstance(value, str):
        raise ValueError("invalid login email")
    normalized = unicodedata.normalize("NFC", value.strip()).casefold()
    if (
        not normalized
        or len(normalized) > LOGIN_EMAIL_MAX_LENGTH
        or normalized.count("@") != 1
        or LOGIN_EMAIL_RE.fullmatch(normalized) is None
        or any(character.isspace() for character in normalized)
    ):
        raise ValueError("invalid login email")
    return normalized


def email_identity_hash(normalized: str) -> str:
    """Keyed lookup hash of a *normalized* address (never of raw input)."""

    return keyed_hash(EMAIL_IDENTITY_HASH_NAMESPACE + normalized)


def mask_login_email(normalized: str) -> str:
    """Owner-facing mask: first local character, fixed fill, full domain."""

    local, _, domain = normalized.rpartition("@")
    return f"{local[:1]}{EMAIL_MASK_FILL}@{domain}"


def is_masked_login_email(value: str | None) -> bool:
    return bool(
        isinstance(value, str)
        and re.fullmatch(r"[^\s@•]•{5}@[^\s@]+\.[^\s@]+", value) is not None
    )
