"""Canonical student academic-profile vocabulary shared by every write path."""
from __future__ import annotations

import re
import unicodedata

CANONICAL_COLLEGES = (
    "National Law School of India University",
    "NALSAR University of Law",
    "The West Bengal National University of Juridical Sciences",
    "Other",
)
CANONICAL_YEARS = ("1st", "2nd", "3rd", "4th", "5th", "llm")

_LEGACY_COLLEGE = {
    "NLSIU": "National Law School of India University",
    "National Law School of India University (NLSIU)": (
        "National Law School of India University"
    ),
    "NALSAR": "NALSAR University of Law",
    "The West Bengal NUJS": (
        "The West Bengal National University of Juridical Sciences"
    ),
    "WBNUJS": "The West Bengal National University of Juridical Sciences",
}
_LEGACY_YEAR = {
    "1st year": "1st",
    "2nd year": "2nd",
    "3rd year": "3rd",
    "4th year \u00b7 B.A. LL.B. (Hons.)": "4th",
    "4th year": "4th",
    "5th year": "5th",
    "LL.M.": "llm",
    "LLM": "llm",
}


def _normalized_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value.strip())
    return re.sub(r"\s+", " ", normalized)


def canonical_college(value: str | None) -> str | None:
    """Map known legacy labels while retaining unknown stored-row compatibility."""

    if value is None:
        return None
    normalized = _normalized_text(value)
    return _LEGACY_COLLEGE.get(normalized, normalized)


def canonical_year(value: str | None) -> str | None:
    """Map known legacy labels while retaining unknown stored-row compatibility."""

    if value is None:
        return None
    normalized = _normalized_text(value)
    return _LEGACY_YEAR.get(normalized, normalized)


def normalize_college(value: str | None) -> str | None:
    """Canonicalize a mutation value and reject anything outside the allowlist."""

    canonical = canonical_college(value)
    if canonical is not None and canonical not in CANONICAL_COLLEGES:
        raise ValueError("unsupported college")
    return canonical


def normalize_year(value: str | None) -> str | None:
    """Canonicalize a mutation value and reject anything outside the allowlist."""

    canonical = canonical_year(value)
    if canonical is not None and canonical not in CANONICAL_YEARS:
        raise ValueError("unsupported year of study")
    return canonical
