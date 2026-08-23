"""One institutional-email verification authority for every consumer."""
from __future__ import annotations

import hmac
from typing import Protocol


class _VerificationRow(Protocol):
    status: str
    verified_email_hash: str | None


class _ProfileRow(Protocol):
    institutional_email_hash: str | None


def has_authoritative_institutional_email_proof(
    verification: _VerificationRow | None,
    profile: _ProfileRow | None,
) -> bool:
    """Accept only a positive proof bound to the currently persisted email."""

    if (
        verification is None
        or profile is None
        or verification.status != "verified"
        or verification.verified_email_hash is None
        or profile.institutional_email_hash is None
    ):
        return False
    return hmac.compare_digest(
        verification.verified_email_hash,
        profile.institutional_email_hash,
    )
