"""Shared institutional-email normalization and allowability contract."""
from __future__ import annotations

import re
import unicodedata


INSTITUTIONAL_EMAIL_MAX_LENGTH = 254
CONSUMER_EMAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "yahoo.com",
        "outlook.com",
        "hotmail.com",
        "proton.me",
        "icloud.com",
        "rediffmail.com",
    }
)
INSTITUTIONAL_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")


def normalize_institutional_email(value: str | None) -> str | None:
    normalized = unicodedata.normalize("NFC", (value or "").strip()).casefold()
    if not normalized:
        return None
    if (
        len(normalized) > INSTITUTIONAL_EMAIL_MAX_LENGTH
        or not INSTITUTIONAL_EMAIL_RE.fullmatch(normalized)
        or normalized.rpartition("@")[2] in CONSUMER_EMAIL_DOMAINS
    ):
        raise ValueError("invalid institutional email")
    return normalized
