"""One Unicode legal-name contract shared by registration and profile writes."""
from __future__ import annotations

import re
import unicodedata


_APPROVED_PUNCTUATION = frozenset({" ", "'", "\u2018", "\u2019", "-", "."})
_ASCII_SPACES = re.compile(r" +")


def normalize_legal_name(value: str) -> str:
    """Normalize NFC and enforce the tracked code-point/state contract."""

    if not isinstance(value, str):
        raise ValueError("invalid legal name")
    normalized = unicodedata.normalize("NFC", value)
    if any(character.isspace() and character != " " for character in normalized):
        raise ValueError("invalid legal name")
    normalized = _ASCII_SPACES.sub(" ", normalized).strip(" ")
    if not 1 <= len(normalized) <= 60:
        raise ValueError("invalid legal name")

    saw_letter = False
    previous_was_letter_or_mark = False
    for character in normalized:
        category = unicodedata.category(character)
        if category.startswith("L"):
            saw_letter = True
            previous_was_letter_or_mark = True
        elif category.startswith("M"):
            if not previous_was_letter_or_mark:
                raise ValueError("invalid legal name")
            previous_was_letter_or_mark = True
        elif character in _APPROVED_PUNCTUATION:
            previous_was_letter_or_mark = False
        else:
            raise ValueError("invalid legal name")
    if not saw_letter:
        raise ValueError("invalid legal name")
    return normalized
