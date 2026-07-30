"""Durable transactional outbox for the tutoring domain (SAATHI-123/127 P2).

This is the ``otp_outbox`` pattern generalised to the Wave 2 aggregates:

1. A mutation writes its business rows AND a ``tutoring_outbox`` row
   (status=pending) in the SAME transaction, then returns an opaque
   :class:`OutboxIntent`. If the transaction rolls back, the intent's row never
   existed and nothing can be dispatched — no "notified about a booking that
   does not exist" failure mode.
2. AFTER the caller commits, :func:`run_delivery` dispatches that one intent and
   records the outcome in its own transaction.
3. If the process dies between commit and dispatch, the committed pending row is
   picked up later by :func:`relay_pending` — the durable half of the promise.

Exactly-once-ish semantics without a ``processing`` status (the schema's
``OUTBOX_STATUSES`` are pending/sent/failed/void):

* A dispatcher CLAIMS a row with an atomic compare-and-swap on
  ``(id, status, attempts)`` — ``UPDATE ... SET attempts = attempts + 1 WHERE
  id = :id AND status IN ('pending','failed') AND attempts = :seen``. Only one
  concurrent relay can observe ``rowcount == 1``, so a row is dispatched at most
  once per attempt even with several relays running.
* Rows already ``sent`` are never re-dispatched, so a retry of a partially
  completed relay produces no duplicate side effects.
* After ``settings.worker_max_attempts`` failed attempts the row is moved to
  ``void`` (dead letter) instead of being retried forever.

Privacy: ``payload_json`` and ``last_error`` are for IDS and CODES only.
:func:`assert_payload_safe` rejects a payload carrying a forbidden field name or
a token/PAN-shaped value, and :func:`error_code` reduces any exception to a
short snake_case code so a provider message can never smuggle PII into
``last_error`` (VARCHAR 200).
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.wave2 import OUTBOX_KINDS, TutoringOutbox
from app.services.tutoring.errors import ValidationError

# --------------------------------------------------------------------------- #
# Privacy guards
# --------------------------------------------------------------------------- #

#: Field names that must never appear in an outbox payload (exact, lowercased).
FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "pan", "card_number", "cardnumber", "cvv", "cvc", "otp", "payment_otp",
        "token", "raw_token", "join_token", "jointoken", "access_token",
        "secret", "provider_secret", "api_key", "password", "authorization",
        "sdp", "ice", "ice_candidate", "candidate", "media", "device_label",
        "narrative", "private_narrative", "email", "phone", "mobile",
        "address", "dob", "aadhaar", "raw_body",
    }
)
#: Value shapes that must never appear in an outbox payload.
_JOIN_TOKEN_RE = re.compile(r"^(join_|eyJ)")
_PAN_LIKE_RE = re.compile(r"(?:\d[ -]?){13,19}")
#: Legitimate id/instant shapes exempted from the PAN scan (an all-digit UUID or
#: an ISO instant must not be mistaken for a card number).
_EXEMPT_VALUE_RE = re.compile(
    r"^(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"|\d{4}-\d{2}-\d{2}(?:[T ].*)?)$"
)


def assert_payload_safe(payload: dict | None, *, where: str = "outbox payload") -> None:
    """Raise ValidationError if a payload carries a forbidden field or value."""

    def walk(node: object, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                key_norm = str(key).strip().lower().replace("-", "_")
                if key_norm in FORBIDDEN_PAYLOAD_KEYS:
                    raise ValidationError(
                        f"{where} may not carry '{key}'", field=f"{path}{key}"
                    )
                walk(value, f"{path}{key}.")
        elif isinstance(node, (list, tuple)):
            for index, item in enumerate(node):
                walk(item, f"{path}{index}.")
        elif isinstance(node, str):
            if _EXEMPT_VALUE_RE.match(node):
                return
            if _JOIN_TOKEN_RE.match(node) or _PAN_LIKE_RE.search(node.replace(":", "")):
                raise ValidationError(
                    f"{where} may not carry a credential/PAN-shaped value",
                    field=path.rstrip("."),
                )

    walk(payload or {}, "")


_CODE_RE = re.compile(r"[^a-z0-9_]+")


def error_code(exc: BaseException, *, fallback: str = "dispatch_failed") -> str:
    """Reduce an exception to a short, non-PII snake_case code (<=64 chars)."""
    raw = getattr(exc, "code", None) or type(exc).__name__
    code = _CODE_RE.sub("_", str(raw).strip().lower()).strip("_")
    return (code or fallback)[:64]


# --------------------------------------------------------------------------- #
# Intent + dispatcher seam
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class OutboxIntent:
    """Opaque reference to a persisted delivery instruction (cf. DeliveryIntent)."""

    outbox_id: uuid.UUID
    kind: str


class OutboxDispatchError(Exception):
    """Raised by a dispatcher; ``retryable`` decides retry vs dead-letter."""

    def __init__(self, message: str, *, code: str = "dispatch_failed", retryable: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@runtime_checkable
class OutboxDispatcher(Protocol):
    def dispatch(self, kind: str, aggregate_id: uuid.UUID, payload: dict | None) -> None: ...


class CapturingDispatcher:
    """In-memory dispatcher for dev/test. Records (kind, aggregate_id, payload)."""

    def __init__(self, *, fail_times: int = 0, retryable: bool = True) -> None:
        self.delivered: list[tuple[str, uuid.UUID, dict | None]] = []
        self._fail_times = fail_times
        self._retryable = retryable
        self.attempts = 0

    def dispatch(self, kind: str, aggregate_id: uuid.UUID, payload: dict | None) -> None:
        self.attempts += 1
        if self._fail_times > 0:
            self._fail_times -= 1
            raise OutboxDispatchError(
                "transient dispatch failure",
                code="transient",
                retryable=self._retryable,
            )
        self.delivered.append((kind, aggregate_id, payload))


class NullDispatcher:
    """Explicit "delivery disabled": records nothing, succeeds silently."""

    def dispatch(self, kind: str, aggregate_id: uuid.UUID, payload: dict | None) -> None:
        return None


def build_outbox_dispatcher() -> OutboxDispatcher:
    """Resolve a dispatcher. Defaults to the no-op sink.

    A real deployment binds an email/push transport here; the relay is written so
    that binding one later needs no service-layer change. Unlike the payment and
    video seams this never returns ``None``: a notification that cannot be sent
    is not a correctness failure, it just stays ``pending`` in the outbox.
    """
    return NullDispatcher()


# --------------------------------------------------------------------------- #
# Enqueue (same transaction as the business change)
# --------------------------------------------------------------------------- #


def enqueue(
    session: Session,
    *,
    kind: str,
    aggregate_id: uuid.UUID,
    payload: dict | None = None,
) -> OutboxIntent:
    """Write a pending outbox row in the CALLER's transaction; return the intent.

    Does not commit: the row lives or dies with the business change.
    """
    if kind not in OUTBOX_KINDS:
        raise ValidationError(f"unknown outbox kind: {kind}", field="kind")
    assert_payload_safe(payload)
    row = TutoringOutbox(
        kind=kind,
        aggregate_id=aggregate_id,
        payload_json=payload,
        status="pending",
        attempts=0,
    )
    session.add(row)
    session.flush()
    return OutboxIntent(outbox_id=row.id, kind=kind)


# --------------------------------------------------------------------------- #
# Delivery
# --------------------------------------------------------------------------- #


def _claim(session: Session, row: TutoringOutbox, *, seen_attempts: int) -> bool:
    """Atomically claim one attempt on a row. True iff this caller won it."""
    result = session.execute(
        update(TutoringOutbox)
        .where(
            TutoringOutbox.id == row.id,
            TutoringOutbox.status.in_(("pending", "failed")),
            TutoringOutbox.attempts == seen_attempts,
        )
        .values(attempts=seen_attempts + 1)
    )
    session.commit()
    return (result.rowcount or 0) == 1


def _finish(
    session: Session,
    row_id: uuid.UUID,
    *,
    status: str,
    last_error: str | None,
    now: datetime,
) -> None:
    session.execute(
        update(TutoringOutbox)
        .where(TutoringOutbox.id == row_id)
        .values(
            status=status,
            last_error=(last_error[:200] if last_error else None),
            delivered_at=(now if status == "sent" else None),
        )
    )
    session.commit()


def run_delivery(
    session: Session,
    intent: OutboxIntent,
    dispatcher: OutboxDispatcher,
    *,
    now: datetime | None = None,
    max_attempts: int | None = None,
) -> bool:
    """Dispatch ONE intent AFTER the caller committed. Own transaction.

    Returns True when the row ends up ``sent`` (including "was already sent",
    which is what makes a retry safe). Never raises for a dispatch failure: the
    row is marked ``failed`` (retryable, the relay will pick it up) or ``void``
    (dead letter) and False is returned.
    """
    now = now or datetime.now(timezone.utc)
    limit = max_attempts if max_attempts is not None else settings.worker_max_attempts
    row = session.get(TutoringOutbox, intent.outbox_id)
    if row is None or row.status == "void":
        return False
    if row.status == "sent":
        return True  # idempotent: never dispatch a delivered row twice
    seen = row.attempts
    if not _claim(session, row, seen_attempts=seen):
        return False  # another relay owns this attempt
    try:
        dispatcher.dispatch(row.kind, row.aggregate_id, row.payload_json)
    except Exception as exc:
        retryable = bool(getattr(exc, "retryable", True))
        exhausted = (seen + 1) >= limit
        _finish(
            session,
            intent.outbox_id,
            status=("failed" if retryable and not exhausted else "void"),
            last_error=error_code(exc),
            now=now,
        )
        return False
    _finish(session, intent.outbox_id, status="sent", last_error=None, now=now)
    return True


@dataclass
class RelayReport:
    """Outcome of one relay pass. Counts only — no payloads, no PII."""

    claimed: int = 0
    sent: int = 0
    failed: int = 0
    dead_lettered: int = 0
    skipped: int = 0

    def as_dict(self) -> dict:
        return {
            "claimed": self.claimed,
            "sent": self.sent,
            "failed": self.failed,
            "dead_lettered": self.dead_lettered,
            "skipped": self.skipped,
        }


def pending_rows(
    session: Session, *, limit: int = 50, kinds: tuple[str, ...] | None = None
) -> list[TutoringOutbox]:
    """Deterministically ordered retryable rows (oldest first, id tie-break)."""
    stmt = (
        select(TutoringOutbox)
        .where(TutoringOutbox.status.in_(("pending", "failed")))
        .order_by(TutoringOutbox.created_at, TutoringOutbox.id)
        .limit(limit)
    )
    if kinds:
        stmt = stmt.where(TutoringOutbox.kind.in_(kinds))
    return list(session.scalars(stmt).all())


def relay_pending(
    session: Session,
    dispatcher: OutboxDispatcher,
    *,
    limit: int = 50,
    max_attempts: int | None = None,
    now: datetime | None = None,
    kinds: tuple[str, ...] | None = None,
) -> RelayReport:
    """Durable relay pass: claim pending/failed rows and dispatch each once.

    Safe to run repeatedly and concurrently. A row that reached ``sent`` in an
    earlier pass is never dispatched again, so "retry the relay" can never
    duplicate a side effect.
    """
    now = now or datetime.now(timezone.utc)
    limit_attempts = (
        max_attempts if max_attempts is not None else settings.worker_max_attempts
    )
    report = RelayReport()
    for row in pending_rows(session, limit=limit, kinds=kinds):
        row_id, kind, aggregate_id, payload = (
            row.id,
            row.kind,
            row.aggregate_id,
            row.payload_json,
        )
        seen = row.attempts
        if seen >= limit_attempts:
            _finish(
                session, row_id, status="void", last_error="attempts_exhausted", now=now
            )
            report.dead_lettered += 1
            continue
        if not _claim(session, row, seen_attempts=seen):
            report.skipped += 1
            continue
        report.claimed += 1
        try:
            dispatcher.dispatch(kind, aggregate_id, payload)
        except Exception as exc:
            retryable = bool(getattr(exc, "retryable", True))
            exhausted = (seen + 1) >= limit_attempts
            if retryable and not exhausted:
                _finish(
                    session, row_id, status="failed", last_error=error_code(exc), now=now
                )
                report.failed += 1
            else:
                _finish(
                    session, row_id, status="void", last_error=error_code(exc), now=now
                )
                report.dead_lettered += 1
            continue
        _finish(session, row_id, status="sent", last_error=None, now=now)
        report.sent += 1
    return report
