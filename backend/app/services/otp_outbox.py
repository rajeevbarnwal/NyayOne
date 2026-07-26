"""Transactional-outbox OTP delivery (SAATHI-448 A2).

Invariant: an OTP is NEVER handed to a provider before the registration/challenge
transaction commits. The service writes an ``otp_outbox`` row (status=pending)
with a short-lived encrypted payload in the SAME transaction as the challenge
and returns an opaque ``DeliveryIntent``. The endpoint commits, then calls
``run_delivery``:

- commit fails  → the outbox row is never persisted and ``run_delivery`` is never
  reached → zero delivery, zero rows.
- commit succeeds → exactly one ``sender.send`` is attempted; the outbox row is
  marked ``sent`` (or ``failed`` with a non-PII error) in its own transaction.

The raw code and plaintext destination are never persisted or logged. Both are
stored only as version-stamped ciphertext until the row is delivered, at which
point the OTP ciphertext is erased. This permits a committed pending row to be
relayed after a process crash without persisting a plaintext OTP.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.crypto import active_key_version, decrypt, encrypt
from app.models.registration import OtpChallenge, OtpOutbox
from app.services.otp_sender import OtpSender, OtpSendError


@dataclass
class DeliveryIntent:
    """Opaque reference to a persisted delivery instruction."""

    outbox_id: uuid.UUID


def enqueue(
    session: Session,
    challenge: OtpChallenge,
    *,
    destination_ct: str,
    code: str,
    purpose: str,
) -> DeliveryIntent:
    """Write the pending outbox row in the challenge's transaction; return intent."""
    row = OtpOutbox(
        challenge_id=challenge.id,
        destination_ct=destination_ct,
        code_ct=encrypt(code),
        key_version=active_key_version(),
        purpose=purpose,
        status="pending",
        attempts=0,
    )
    session.add(row)
    session.flush()
    return DeliveryIntent(outbox_id=row.id)


def run_delivery(
    session: Session,
    intent: DeliveryIntent,
    sender: OtpSender,
    *,
    raise_on_failure: bool,
) -> bool:
    """Deliver AFTER the caller has committed. Updates the outbox in its own txn.

    Returns True on success. On provider failure: marks the outbox row ``failed``
    (retryable by a relay) and either raises OtpSendError (signup — surfaces a
    typed 502 to the user) or returns False (recovery — fire-and-forget so known
    vs unknown stays indistinguishable).
    """
    row = session.get(OtpOutbox, intent.outbox_id)
    if row is None or row.status == "void":
        if raise_on_failure:
            raise OtpSendError("otp delivery intent unavailable")
        return False
    if row.status == "sent":
        return True
    if not row.code_ct:
        row.status = "void"
        row.last_error = "missing_encrypted_payload"
        session.commit()
        if raise_on_failure:
            raise OtpSendError("otp delivery payload unavailable")
        return False

    destination = decrypt(row.destination_ct)
    code = decrypt(row.code_ct)
    try:
        sender.send(destination, code)
    except OtpSendError:
        row.status = "failed"
        row.attempts += 1
        row.last_error = "provider_send_failed"
        session.commit()
        if raise_on_failure:
            raise
        return False
    finally:
        destination = ""
        code = ""
    row.status = "sent"
    row.attempts += 1
    row.last_error = None
    row.code_ct = None
    row.delivered_at = datetime.now(timezone.utc)
    session.commit()
    return True
