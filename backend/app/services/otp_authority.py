"""Stable OTP authority and durable abuse budgets (NYAY-4).

Raw identifiers and network addresses never enter these tables.  The authority
subject is a domain-separated SHA-256 of the existing keyed mobile lookup hash;
rate subjects are separately domain-separated keyed hashes.  Callers consume
the three rate buckets in a short transaction before taking domain locks.
"""
from __future__ import annotations

import hashlib
import ipaddress
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import keyed_hash
from app.models.registration import (
    OtpPurposeAuthority,
    OtpRateLimitBucket,
    StudentRegistration,
)

_AUTHORITY_ID_NAMESPACE = uuid.UUID("d4bd542f-dd07-4512-ac24-c7d789287708")
_RATE_BUCKET_ID_NAMESPACE = uuid.UUID("4426bb1b-326a-4bda-9b34-23c7c3470d8b")
_PURPOSES = frozenset({"signup", "login", "recovery"})
_ACTIONS = frozenset({"issue", "resend", "verify"})


def as_utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def authority_subject_from_mobile_hash(mobile_hash: str) -> str:
    """Derive the stable authority subject from an existing keyed hash."""

    if (
        not isinstance(mobile_hash, str)
        or len(mobile_hash) != 64
        or any(character not in "0123456789abcdef" for character in mobile_hash)
    ):
        raise ValueError("mobile lookup hash has an invalid shape")
    return hashlib.sha256(
        f"nyayone:otp-authority:v1:{mobile_hash}".encode("ascii")
    ).hexdigest()


def authority_subject_for_mobile(mobile: str) -> str:
    return authority_subject_from_mobile_hash(keyed_hash(mobile))


def _insert_for(session: Session, model):
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        return pg_insert(model)
    if dialect == "sqlite":
        return sqlite_insert(model)
    raise RuntimeError("OTP authority requires PostgreSQL or SQLite")


def _authority_id(subject_hash: str, purpose: str) -> uuid.UUID:
    return uuid.uuid5(_AUTHORITY_ID_NAMESPACE, f"{subject_hash}:{purpose}")


def lock_or_create_authority(
    session: Session,
    *,
    subject_hash: str,
    purpose: str,
    registration_id: uuid.UUID | None,
    now: datetime,
) -> OtpPurposeAuthority:
    """Return the one locked subject+purpose authority, creating it race-safely.

    This is the supported seeding seam for native PostgreSQL gates and service
    tests.  A former decoy authority may be promoted to the matching real
    registration; it can never be rebound from one registration to another.
    """

    if purpose not in _PURPOSES:
        raise ValueError("unsupported OTP purpose")
    # Revalidate the 64-lowercase-hex domain at this public boundary.
    authority_subject_from_mobile_hash(subject_hash)
    now = as_utc(now)
    statement = _insert_for(session, OtpPurposeAuthority).values(
        id=_authority_id(subject_hash, purpose),
        subject_hash=subject_hash,
        registration_id=registration_id,
        purpose=purpose,
        failed_attempts=0,
        max_attempts=settings.otp_max_attempts,
        locked_until=None,
        attempt_window_started_at=None,
        last_issued_at=None,
        cooldown_until=None,
        resend_window_started_at=None,
        resend_count=0,
        max_resends=settings.otp_max_resends_per_window,
        active_expires_at=None,
        generation=0,
        created_at=now,
        updated_at=now,
    )
    session.execute(
        statement.on_conflict_do_nothing(
            index_elements=["subject_hash", "purpose"]
        )
    )
    authority = session.scalar(
        select(OtpPurposeAuthority)
        .where(
            OtpPurposeAuthority.subject_hash == subject_hash,
            OtpPurposeAuthority.purpose == purpose,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if authority is None:
        raise RuntimeError("OTP authority could not be established")
    if authority.registration_id is None and registration_id is not None:
        authority.registration_id = registration_id
    elif (
        registration_id is not None
        and authority.registration_id is not None
        and authority.registration_id != registration_id
    ):
        raise RuntimeError("OTP authority registration binding is ambiguous")
    refresh_lock_window(authority, now)
    session.flush()
    return authority


def lock_or_create_registration_authority(
    session: Session,
    registration: StudentRegistration,
    purpose: str,
    now: datetime,
) -> OtpPurposeAuthority:
    return lock_or_create_authority(
        session,
        subject_hash=authority_subject_from_mobile_hash(registration.mobile_hash),
        purpose=purpose,
        registration_id=registration.id,
        now=now,
    )


def refresh_lock_window(
    authority: OtpPurposeAuthority, now: datetime
) -> None:
    now = as_utc(now)
    if (
        authority.locked_until is not None
        and as_utc(authority.locked_until) <= now
    ):
        authority.failed_attempts = 0
        authority.locked_until = None
        authority.attempt_window_started_at = None
        authority.max_attempts = settings.otp_max_attempts


def locked_for_seconds(
    authority: OtpPurposeAuthority, now: datetime
) -> int:
    refresh_lock_window(authority, now)
    if authority.locked_until is None:
        return 0
    return max(
        0,
        math.ceil(
            (as_utc(authority.locked_until) - as_utc(now)).total_seconds()
        ),
    )


@dataclass(frozen=True)
class RateLimitExceeded(Exception):
    retry_after_seconds: int

    def __str__(self) -> str:
        return "OTP abuse budget exhausted"


@dataclass(frozen=True)
class _Budget:
    scope: str
    subject_hash: str
    window_seconds: int
    maximum: int


def _network_subject(client_ip: str | None) -> str:
    value = (client_ip or "unavailable").strip()
    try:
        value = ipaddress.ip_address(value).compressed
    except ValueError:
        # TestClient and Unix-domain peers are still placed in one opaque
        # budget; proxy headers are intentionally never consulted here.
        value = "unavailable"
    return keyed_hash(f"nyayone:otp-rate-ip:v1:{value}")


def _limits(action: str) -> tuple[int, int, int, int]:
    if action not in _ACTIONS:
        raise ValueError("unsupported OTP rate action")
    return (
        int(getattr(settings, f"otp_{action}_rate_window_seconds")),
        int(getattr(settings, f"otp_{action}_identity_limit")),
        int(getattr(settings, f"otp_{action}_ip_limit")),
        int(getattr(settings, f"otp_{action}_global_limit")),
    )


def consume_rate_budgets(
    session: Session,
    *,
    subject_hash: str,
    client_ip: str | None,
    action: str,
    purpose: str = "signup",
    now: datetime,
    commit: bool = True,
) -> None:
    """Atomically consume identity, peer-IP and global fixed-window budgets."""

    authority_subject_from_mobile_hash(subject_hash)
    if purpose not in _PURPOSES:
        raise ValueError("unsupported OTP rate purpose")
    now = as_utc(now)
    window, identity_max, ip_max, global_max = _limits(action)
    budgets = sorted(
        (
            _Budget(
                "identity",
                keyed_hash(
                    "nyayone:otp-rate-identity:v1:"
                    f"{purpose}:{subject_hash}"
                ),
                window,
                identity_max,
            ),
            _Budget("ip", _network_subject(client_ip), window, ip_max),
            _Budget(
                "global",
                keyed_hash("nyayone:otp-rate-global:v1"),
                window,
                global_max,
            ),
        ),
        key=lambda item: (item.scope, item.subject_hash),
    )
    for budget in budgets:
        row_id = uuid.uuid5(
            _RATE_BUCKET_ID_NAMESPACE,
            f"{budget.scope}:{budget.subject_hash}:{action}",
        )
        statement = _insert_for(session, OtpRateLimitBucket).values(
            id=row_id,
            scope=budget.scope,
            subject_hash=budget.subject_hash,
            action=action,
            window_started_at=now,
            window_seconds=budget.window_seconds,
            request_count=0,
            max_requests=budget.maximum,
            created_at=now,
            updated_at=now,
        )
        session.execute(
            # The UUID is deterministic from the same natural key.  Under a
            # concurrent first insert PostgreSQL may surface either the
            # primary-key collision or the natural-key collision, so the
            # idempotent bootstrap must accept either conflict.
            statement.on_conflict_do_nothing()
        )
    rows = list(
        session.scalars(
            select(OtpRateLimitBucket)
            .where(
                OtpRateLimitBucket.action == action,
                or_(
                    *[
                        (
                            (OtpRateLimitBucket.scope == budget.scope)
                            & (
                                OtpRateLimitBucket.subject_hash
                                == budget.subject_hash
                            )
                        )
                        for budget in budgets
                    ]
                ),
            )
            .order_by(OtpRateLimitBucket.scope, OtpRateLimitBucket.subject_hash)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    by_key = {(row.scope, row.subject_hash): row for row in rows}
    if len(by_key) != 3:
        session.rollback()
        raise RuntimeError("OTP abuse budget graph is incomplete")

    retry_after = 0
    for budget in budgets:
        row = by_key[(budget.scope, budget.subject_hash)]
        window_end = as_utc(row.window_started_at) + timedelta(
            seconds=row.window_seconds
        )
        if window_end <= now:
            row.window_started_at = now
            row.window_seconds = budget.window_seconds
            row.request_count = 0
            row.max_requests = budget.maximum
            window_end = now + timedelta(seconds=budget.window_seconds)
        if row.request_count >= row.max_requests:
            retry_after = max(
                retry_after,
                max(1, math.ceil((window_end - now).total_seconds())),
            )
    if retry_after:
        session.rollback()
        raise RateLimitExceeded(retry_after)
    for row in rows:
        row.request_count += 1
        row.updated_at = now
    if commit:
        session.commit()
    else:
        session.flush()


def purge_expired_rate_buckets(session: Session, *, now: datetime) -> int:
    cutoff = as_utc(now) - timedelta(
        seconds=settings.otp_rate_bucket_retention_seconds
    )
    result = session.execute(
        delete(OtpRateLimitBucket).where(
            OtpRateLimitBucket.updated_at < cutoff
        )
    )
    session.flush()
    return int(result.rowcount or 0)
