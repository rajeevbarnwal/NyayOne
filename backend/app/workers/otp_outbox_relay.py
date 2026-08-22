"""Durable OTP outbox relay.

The HTTP transaction writes the challenge and encrypted delivery payload
atomically. This relay is the crash/retry path: it scans pending/failed rows,
claims them with ``FOR UPDATE SKIP LOCKED`` on PostgreSQL, and delegates to the
idempotent ``run_delivery`` operation. Successful delivery erases the encrypted
OTP payload; retries never re-send a row already marked ``sent``.

Run once from a scheduler/worker:

    python -m app.workers.otp_outbox_relay
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.session import get_sessionmaker
from app.models.registration import OtpOutbox, RegistrationIdempotencyRecord
from app.services import otp_outbox
from app.services.otp_sender import IdempotentOtpSender, build_otp_sender


@dataclass(frozen=True)
class RelayResult:
    examined: int
    delivered: int
    failed: int


def deliver_after_response(
    outbox_id,
    sender: IdempotentOtpSender,
    session_factory: Callable[[], Session] | None = None,
) -> None:
    """FastAPI background-task adapter using a fresh database session.

    Keeping provider I/O outside the request session makes recovery-start
    response timing independent of whether the mobile belongs to an account.
    """
    factory = session_factory or get_sessionmaker()
    with factory() as session:
        otp_outbox.run_delivery(
            session,
            otp_outbox.DeliveryIntent(outbox_id=outbox_id),
            sender,
            raise_on_failure=False,
        )


def finalize_registration_after_response(
    key_hash: str,
    sender: IdempotentOtpSender,
    session_factory: Callable[[], Session] | None = None,
) -> None:
    """Resume one durable NYAY-17 registration graph after HTTP response.

    Provider failures are expected worker outcomes: the fenced outbox retains
    the same encrypted candidate and provider idempotency key for a later relay.
    They must never alter the already-returned anti-enumerating HTTP response.
    """

    from app.services.registration_service import (
        RegistrationError,
        finalize_pending_registration,
    )

    factory = session_factory or get_sessionmaker()
    with factory() as session:
        try:
            finalize_pending_registration(session, key_hash, sender)
        except RegistrationError:
            session.rollback()


def deliver_resend_after_response(
    registration_id,
    outbox_id,
    sender: IdempotentOtpSender,
    session_factory: Callable[[], Session] | None = None,
    *,
    now: datetime | None = None,
) -> None:
    """Reconcile a signup ledger resend, or deliver an ordinary purpose."""

    from app.services.registration_service import (
        RegistrationError,
        finalize_pending_resend_if_claimed,
    )

    factory = session_factory or get_sessionmaker()
    intent = otp_outbox.DeliveryIntent(outbox_id=outbox_id)
    with factory() as session:
        try:
            claimed = finalize_pending_resend_if_claimed(
                session, registration_id, intent, sender, now=now
            )
            if not claimed:
                otp_outbox.run_delivery(
                    session,
                    intent,
                    sender,
                    raise_on_failure=False,
                    now=now,
                )
        except RegistrationError:
            session.rollback()


def relay_pending(
    *,
    session_factory: Callable[[], Session] | None = None,
    sender: IdempotentOtpSender | None = None,
    limit: int = 100,
) -> RelayResult:
    """Attempt each eligible row at most once in this invocation."""
    provider = sender or build_otp_sender()
    if provider is None:
        raise RuntimeError("OTP provider is not configured; relay fails closed")
    factory = session_factory or get_sessionmaker()
    now = datetime.now(timezone.utc)
    with factory() as session:
        statement = (
            select(OtpOutbox.id)
            .where(
                or_(
                    OtpOutbox.status == "pending",
                    (
                        (OtpOutbox.status == "failed")
                        & (OtpOutbox.next_attempt_at <= now)
                    ),
                    (
                        (OtpOutbox.status == "claimed")
                        & (OtpOutbox.lease_expires_at <= now)
                    ),
                ),
                OtpOutbox.code_ct.is_not(None),
            )
            .order_by(OtpOutbox.created_at, OtpOutbox.id)
            .limit(max(1, min(limit, 1000)))
            .with_for_update(skip_locked=True)
        )
        ids = list(session.scalars(statement))

    delivered = 0
    failed = 0
    for outbox_id in ids:
        with factory() as session:
            key_hash = session.scalar(
                select(
                    RegistrationIdempotencyRecord.idempotency_key_hash
                ).where(
                    RegistrationIdempotencyRecord.outbox_id == outbox_id,
                    RegistrationIdempotencyRecord.state == "pending",
                )
            )
            if key_hash is None:
                ok = otp_outbox.run_delivery(
                    session,
                    otp_outbox.DeliveryIntent(outbox_id=outbox_id),
                    provider,
                    raise_on_failure=False,
                )
            else:
                from app.services.registration_service import (
                    RegistrationError,
                    finalize_pending_registration_with_result,
                )

                try:
                    outcome = finalize_pending_registration_with_result(
                        session,
                        key_hash,
                        provider,
                    )
                except RegistrationError:
                    session.rollback()
                    ok = False
                else:
                    ok = outcome.newly_delivered
        if ok:
            delivered += 1
        else:
            # A concurrent worker may have finalized the stable provider key
            # after this invocation discovered the row. Observing its terminal
            # success is neither a new delivery nor a failure.
            with factory() as state_session:
                status = state_session.scalar(
                    select(OtpOutbox.status).where(OtpOutbox.id == outbox_id)
                )
            if status != "sent":
                failed += 1
    return RelayResult(examined=len(ids), delivered=delivered, failed=failed)


def main() -> None:
    result = relay_pending()
    # Counts only; never print destinations, OTPs, provider payloads or errors.
    print(
        f"otp_outbox_relay examined={result.examined} "
        f"delivered={result.delivered} failed={result.failed}"
    )


if __name__ == "__main__":  # pragma: no cover
    main()
