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
    *, now=None,
) -> bool:
    """Accept only a positive proof bound to the currently persisted email."""

    # New authority rows have a stricter provider+assignment boundary; old
    # mutable flags cannot bypass its expiry, revocation, or identity checks.
    if verification is not None:
        from datetime import datetime, timezone
        from sqlalchemy import inspect
        from sqlalchemy.orm import object_session
        from app.models.student_authority import AuthorityState
        from app.services.student_authority import institutional_is_current
        if inspect(verification, raiseerr=False) is not None:
            session = object_session(verification)
            registration_id = getattr(verification, "registration_id", None)
            if session is not None and registration_id is not None and session.get(AuthorityState, registration_id) is not None:
                return institutional_is_current(session, registration_id, now=now or datetime.now(timezone.utc))

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
