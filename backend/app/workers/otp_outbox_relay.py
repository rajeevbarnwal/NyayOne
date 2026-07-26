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
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_sessionmaker
from app.models.registration import OtpOutbox
from app.services import otp_outbox
from app.services.otp_sender import OtpSender, build_otp_sender


@dataclass(frozen=True)
class RelayResult:
    examined: int
    delivered: int
    failed: int


def deliver_after_response(
    outbox_id,
    sender: OtpSender,
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


def relay_pending(
    *,
    session_factory: Callable[[], Session] | None = None,
    sender: OtpSender | None = None,
    limit: int = 100,
) -> RelayResult:
    """Attempt each eligible row at most once in this invocation."""
    provider = sender or build_otp_sender()
    if provider is None:
        raise RuntimeError("OTP provider is not configured; relay fails closed")
    factory = session_factory or get_sessionmaker()
    with factory() as session:
        statement = (
            select(OtpOutbox.id)
            .where(
                OtpOutbox.status.in_(("pending", "failed")),
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
            ok = otp_outbox.run_delivery(
                session,
                otp_outbox.DeliveryIntent(outbox_id=outbox_id),
                provider,
                raise_on_failure=False,
            )
        if ok:
            delivered += 1
        else:
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
