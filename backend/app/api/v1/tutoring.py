"""SAATHI-123 / SAATHI-127 P3 — the Wave 2 tutoring HTTP surface.

Frozen matrix rows A1-A3, B1-B2, C1-C3, D1-D5, E1-E2, F1-F3 and J1. Every route
here is THIN by contract: validate the request shape, authorise the caller,
delegate to ``app.services.tutoring.*``, and map the typed domain error onto the
HTTP envelope. No business rule lives in this module — if you find yourself
wanting to write one, it belongs in the owning service where a worker and the
CLI can reach it too.

Four house rules this module inherits and does not restate per route:

* **typed envelopes.** A ``TutoringError`` becomes
  ``{"detail": {"code": <STABLE_CODE>, "message": ..., ...extra}}`` at the
  error's own ``status_code`` (see ``app.services.tutoring.errors``), so the
  machine code a client branches on is the SAME one the service raised. Anything
  unexpected is the registered 500 handler's ``internal_error`` — never a leaked
  traceback (``app.core.exceptions``).
* **rollback before raising.** A typed failure rolls the request transaction
  back first, so a refused request leaves no partial row and, because outbox
  rows are written in that same transaction, no dispatchable side effect.
* **non-enumerating reads.** "does not exist" and "is not yours" are ONE shape.
  The services already collapse them into ``NOT_FOUND``; routes must not
  helpfully turn that back into a 403.
* **the price is the SERVER's.** No route accepts a session price. The amount
  is resolved from ``tutor_profiles``, snapshotted onto the booking hold and
  copied from that snapshot into the payment order; the routes PUBLISH it
  (``session_price_paise`` on a tutor, ``price_paise`` on a slot and on a hold)
  so a screen can render it instead of reading a build-time env var. The one
  remaining ``amount_paise`` input is an optional optimistic confirmation whose
  disagreement is ``PAYMENT_AMOUNT_MISMATCH`` with zero mutation.
* **privacy (J1).** No route accepts, echoes, logs or persists a PAN, CVV,
  payment OTP, provider secret, SDP, ICE candidate or device label:
  ``extra="forbid"`` rejects the field outright, the payment surface takes a
  provider TOKEN only (pattern-checked, never stored), and the join credential
  is returned in ONE response body while only its hash reaches a row.

Post-commit dispatch: every mutation commits FIRST and only then hands the
service's ``intents`` to ``outbox_relay.run_delivery``. A dispatch failure after
a successful commit must not turn a successful mutation into a 500 — the durable
relay owns the retry.
"""
from __future__ import annotations

import uuid
from datetime import date as date_type
from datetime import datetime, time, timedelta, timezone
from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy.orm import Session

from app.core.auth import ActorContext, Role, get_actor_context
from app.core.config import settings
from app.core.logging import get_logger
from app.core.rate_limit import (
    BOOKING,
    REVIEW,
    TUTOR_SEARCH,
    RateLimit,
    RateLimitExceeded,
    check,
)
from app.db.session import get_session
from app.models.wave2 import BookingHold, PaymentOrder
from app.services.tutoring import (
    attendance as attendance_service,
    availability,
    booking,
    join_credentials,
    outbox_relay,
    payments,
    reviews as reviews_service,
    sessions as sessions_service,
)
from app.services.tutoring.errors import NotFound, PaymentUnverified, TutoringError

logger = get_logger("nyayone.tutoring.api")

router = APIRouter(tags=["tutoring"])

#: Webhook bodies are provider JSON, not user uploads. A hard ceiling keeps a
#: malformed/hostile delivery from being parsed at all.
MAX_WEBHOOK_BYTES = 64 * 1024
PAYMENT_SIGNATURE_HEADER = "X-Payment-Signature"
#: There is deliberately NO ``VIDEO_SIGNATURE_HEADER`` here. The video adapters
#: disagree about the transport (the deterministic one signs a hex HMAC into
#: ``X-Video-Signature``; a real LiveKit server signs a JWT into ``Authorization``),
#: so each adapter declares its own ``signature_header`` and this route forwards
#: the delivery's headers untouched — see
#: ``app.services.providers.video_provider`` and ``join_credentials.handle_event``.


# --------------------------------------------------------------------------- #
# Error mapping
# --------------------------------------------------------------------------- #


def _error(status_code: int, code: str, message: str, **extra: object) -> HTTPException:
    detail: dict[str, object] = {"code": code, "message": message}
    detail.update(extra)
    return HTTPException(status_code=status_code, detail=detail)


def _typed(session: Session, exc: TutoringError) -> HTTPException:
    """Roll back, then map a domain error onto its frozen HTTP envelope.

    The rollback is what makes "no partial row, no outbox side effect" true for
    every refusal, including the ones raised half-way through a multi-row
    service call (a consumed hold, a booked slot, a written audit row).
    """
    session.rollback()
    return HTTPException(
        status_code=exc.status_code,
        # ``retryable`` is part of the contract, not decoration: a client seeing
        # PROVIDER_UNAVAILABLE must be told whether retrying the same request can
        # succeed, and every TutoringError already answers that question.
        detail={
            "code": exc.code,
            "message": exc.message,
            "retryable": bool(exc.retryable),
            **exc.extra,
        },
    )


# --------------------------------------------------------------------------- #
# Authorisation + rate limiting
# --------------------------------------------------------------------------- #


def _authenticated(actor: ActorContext = Depends(get_actor_context)) -> ActorContext:
    if not actor.is_authenticated:
        raise _error(401, "authentication_required", "Authentication required")
    return actor


def _require(actor: ActorContext, role: Role) -> ActorContext:
    if not actor.has_role(role):
        raise _error(403, "forbidden", f"Requires the {role.value} role")
    return actor


def _student(actor: ActorContext = Depends(_authenticated)) -> ActorContext:
    return _require(actor, Role.STUDENT)


def _admin(actor: ActorContext = Depends(_authenticated)) -> ActorContext:
    return _require(actor, Role.ADMIN)


def _service_role(actor: ActorContext) -> str:
    """Map claim roles onto the ``ACTOR_ROLES`` the services understand.

    Most privileged first, because an admin acting on their own booking should
    still get the admin view. A caller with none of the three roles is refused
    here rather than being silently treated as a student.
    """
    if actor.has_role(Role.ADMIN):
        return "admin"
    if actor.has_role(Role.TUTOR):
        return "tutor"
    if actor.has_role(Role.STUDENT):
        return "student"
    raise _error(403, "forbidden", "This role may not use the tutoring API")


def _participant(actor: ActorContext = Depends(_authenticated)) -> ActorContext:
    _service_role(actor)  # 403 for a role with no tutoring identity at all
    return actor


def _limit(limit: RateLimit, actor: ActorContext) -> None:
    """Apply a config-driven, per-identity limit at the HTTP boundary.

    Hash-only bucketing (``app.core.rate_limit``), thresholds read from
    ``settings`` on every call. The 429 body carries the same
    ``rate_limit_exceeded`` code the public credential endpoint already returns,
    so a client has ONE limit contract to implement.
    """
    try:
        check(limit, str(actor.user_id))
    except RateLimitExceeded as exc:
        raise _error(
            429,
            "rate_limit_exceeded",
            "Too many requests",
            limit=exc.limit,
            window_seconds=exc.window_seconds,
            retry_after_seconds=exc.retry_after,
        ) from exc


def _dispatch(session: Session, intents) -> None:
    """Commit-then-dispatch. A post-commit dispatch failure is NOT a 500."""
    dispatcher = outbox_relay.build_outbox_dispatcher()
    for intent in intents:
        try:
            outbox_relay.run_delivery(session, intent, dispatcher)
        except Exception:  # pragma: no cover - relay swallows dispatch failures
            # The row stays pending/failed and ``relay_pending`` retries it. The
            # mutation itself is already durable, so the caller gets its 200.
            logger.warning("outbox_dispatch_deferred")


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    """UTC-aware ISO-8601, always.

    Every instant column is stored in UTC, but ``DateTime(timezone=True)`` loses
    the offset on sqlite (and on any dialect without a native tz type). Handing a
    client an offset-less timestamp and expecting it to assume UTC is exactly the
    ambiguity the DST policy exists to remove, so the offset is re-attached here.
    """
    aware = _aware(value)
    return aware.isoformat() if aware else None


# --------------------------------------------------------------------------- #
# Projections
# --------------------------------------------------------------------------- #


def _tutor_summary(tutor) -> dict:
    return {
        "id": str(tutor.id),
        "display_name": tutor.display_name,
        "headline": tutor.headline,
        "experience_years": tutor.experience_years,
        "rating_avg": (str(tutor.rating_avg) if tutor.rating_avg is not None else None),
        "rating_count": tutor.rating_count,
        "verified_identity": bool(tutor.verified_identity),
        "verified_credentials": bool(tutor.verified_credentials),
        "status": tutor.status,
        # PUBLISHED so a screen can render the amount instead of reading a build
        # -time env var and guessing. Integer paise, never formatted here — the
        # server owns the number, the client owns the rupee rendering.
        "session_price_paise": int(tutor.session_price_paise),
        "currency": tutor.session_currency,
    }


def _tutor_detail(session: Session, tutor) -> dict:
    """Detail + verified claims/provenance (A2) + the PUBLIC aggregate (F3).

    The aggregate comes from ``reviews.public_aggregate``, which counts published
    rows only — so an unmoderated review is invisible here by construction, not
    by a filter this projection remembers to apply.
    """
    subjects = availability.list_subjects(session, tutor.id)
    aggregate = reviews_service.public_aggregate(session, tutor.id)
    return {
        **_tutor_summary(tutor),
        "source": tutor.source,
        "source_url": tutor.source_url,
        "retrieved_at": _iso(tutor.retrieved_at),
        "subjects": [
            {"subject": s.subject, "level": s.level} for s in subjects
        ],
        "rating_aggregate": aggregate.as_dict(),
    }


def _hold_out(hold, *, replayed: bool = False) -> dict:
    return {
        "id": str(hold.id),
        "slot_id": str(hold.slot_id),
        "status": hold.status,
        "expires_at": _iso(hold.expires_at),
        "hold_minutes": settings.booking_hold_minutes,
        # The IMMUTABLE price snapshot this hold was taken at, and therefore the
        # exact amount ``POST /payments/orders`` will charge. This is what a
        # checkout screen renders; it is published, never accepted back.
        "price_paise": int(hold.price_paise),
        "currency": hold.price_currency,
        "replayed": replayed,
    }


def _order_out(order: PaymentOrder, *, replayed: bool = False) -> dict:
    return {
        "id": str(order.id),
        "hold_id": str(order.hold_id),
        "provider": order.provider,
        "provider_order_ref": order.provider_order_ref,
        "amount_paise": order.amount_paise,
        "currency": order.currency,
        "status": order.status,
        # Issuer display crumbs only. Never a PAN, never a token.
        "brand": order.brand,
        "masked_last4": order.masked_last4,
        "replayed": replayed,
    }


def _session_out(session: Session, sess, *, display_timezone: str | None = None) -> dict:
    tz_name = display_timezone or sess.iana_timezone
    start_utc = _aware(sess.start_utc)
    end_utc = _aware(sess.end_utc)
    row = attendance_service.get_attendance(session, sess.id)
    return {
        "id": str(sess.id),
        "slot_id": str(sess.slot_id),
        "tutor_id": str(sess.tutor_id),
        "student_user_id": str(sess.student_user_id),
        "order_id": (str(sess.order_id) if sess.order_id else None),
        "status": sess.status,
        "version": sess.version,
        "start_utc": start_utc.isoformat(),
        "end_utc": end_utc.isoformat(),
        "iana_timezone": tz_name,
        "start_local": availability.to_local(start_utc, tz_name).isoformat(),
        "end_local": availability.to_local(end_utc, tz_name).isoformat(),
        "attendance_state": (row.state if row else None),
        "attendance_version": (row.version if row else None),
    }


def _attendance_out(mutation) -> dict:
    row = mutation.attendance
    return {
        "session_id": str(row.session_id),
        "state": row.state,
        "version": row.version,
        "recorded_by_role": row.recorded_by_role,
        "recorded_at": _iso(row.recorded_at),
        "confirmed_at": _iso(row.confirmed_at),
        "disputed_at": _iso(row.disputed_at),
        "resolved_at": _iso(row.resolved_at),
        "resolution": row.resolution,
        "session_status": mutation.tutoring_session.status,
    }


def _review_out(mutation) -> dict:
    review = mutation.review
    return {
        "id": str(review.id),
        "session_id": str(review.session_id),
        "tutor_id": str(review.tutor_id),
        "rating": int(review.rating),
        "body": review.body,
        "published": bool(review.published),
        "edit_deadline_at": _iso(review.edit_deadline_at),
        "deleted": review.deleted_at is not None,
        "moderation_state": (mutation.moderation.state if mutation.moderation else None),
        "rating_aggregate": (
            mutation.aggregate.as_dict() if mutation.aggregate else None
        ),
    }


# --------------------------------------------------------------------------- #
# A1/A2/A3 — discovery
# --------------------------------------------------------------------------- #


@router.get("/tutors")
def search_tutors(
    q: str | None = Query(default=None, max_length=120),
    subject: str | None = Query(default=None, max_length=80),
    level: str | None = Query(default=None, max_length=40),
    min_rating: float | None = Query(default=None),
    min_experience_years: int | None = Query(default=None),
    verified_only: bool = Query(default=False),
    sort: str = Query(default="rating_desc", max_length=32),
    limit: int = Query(default=20),
    offset: int = Query(default=0),
    actor: ActorContext = Depends(_student),
    session: Session = Depends(get_session),
) -> dict:
    """A1. Filters/sort/pagination, rate limited at the configured threshold.

    Length ceilings live on the query parameters (an over-length filter is a
    request-shape problem, so it is a 422 before any SQL runs); every VALUE rule
    — unknown sort, rating range, page size — is the service's.
    """
    _limit(TUTOR_SEARCH, actor)
    try:
        page = availability.search_tutors(
            session,
            subject=subject,
            level=level,
            min_rating=min_rating,
            min_experience_years=min_experience_years,
            verified_only=verified_only,
            query=q,
            sort=sort,
            limit=limit,
            offset=offset,
        )
    except TutoringError as exc:
        raise _typed(session, exc) from exc
    return {
        "items": [_tutor_summary(t) for t in page.items],
        "total": page.total,
        "limit": page.limit,
        "offset": page.offset,
        "has_more": page.has_more,
        "sort": sort,
        "allowed_sorts": list(availability.SORTS),
    }


@router.get("/tutors/{tutor_id}")
def get_tutor(
    tutor_id: uuid.UUID,
    actor: ActorContext = Depends(_student),
    session: Session = Depends(get_session),
) -> dict:
    """A2. Unknown/hidden tutor -> non-enumerating 404 ``NOT_FOUND``."""
    _limit(TUTOR_SEARCH, actor)
    try:
        tutor = availability.get_tutor(session, tutor_id)
    except TutoringError as exc:
        raise _typed(session, exc) from exc
    return _tutor_detail(session, tutor)


def _naive_local(value: str, field: str) -> datetime:
    """Parse a NAIVE local wall time. An offset here is a contradiction."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise _error(
            422,
            "VALIDATION_ERROR",
            "expected an ISO-8601 local date-time",
            field=field,
        ) from exc
    if parsed.tzinfo is not None:
        raise _error(
            422,
            "VALIDATION_ERROR",
            "a local wall time must not carry an offset; use from_utc/to_utc",
            field=field,
        )
    return parsed


@router.get("/tutors/{tutor_id}/availability")
def get_availability(
    tutor_id: uuid.UUID,
    timezone_name: str | None = Query(default=None, alias="timezone", max_length=64),
    date: date_type | None = Query(default=None),
    from_local: str | None = Query(default=None, max_length=40),
    to_local: str | None = Query(default=None, max_length=40),
    from_utc: datetime | None = Query(default=None),
    to_utc: datetime | None = Query(default=None),
    limit: int = Query(default=50),
    offset: int = Query(default=0),
    actor: ActorContext = Depends(_student),
    session: Session = Depends(get_session),
) -> dict:
    """A3. Slots + timezone, with the DST policy made VISIBLE to the caller.

    A window may be given as UTC instants (``from_utc``/``to_utc``), as naive
    LOCAL wall times (``from_local``/``to_local``), or as a local calendar
    ``date`` — never as a mixture, because "which zone did you mean" would then
    have two answers.

    A local wall time is resolved by ``availability.resolve_local_instant``, and
    its ``classification`` is returned in ``local_resolution``: ``ambiguous``
    (fall-back overlap, the EARLIER occurrence is used) and ``nonexistent``
    (spring-forward gap, shifted forward past the gap) are reported rather than
    silently rounded, so a caller can tell the user which instant they actually
    asked for.
    """
    _limit(TUTOR_SEARCH, actor)
    local_given = date is not None or from_local is not None or to_local is not None
    utc_given = from_utc is not None or to_utc is not None
    if local_given and utc_given:
        raise _error(
            422,
            "VALIDATION_ERROR",
            "give the window either as UTC instants or as local wall times",
            field="from_local",
        )
    if date is not None and (from_local is not None or to_local is not None):
        raise _error(
            422,
            "VALIDATION_ERROR",
            "date and from_local/to_local are mutually exclusive",
            field="date",
        )
    try:
        availability.zone(timezone_name)  # typed 422 for an unknown IANA name
    except TutoringError as exc:
        raise _typed(session, exc) from exc
    tz_name = (timezone_name or availability.DEFAULT_TIMEZONE).strip()

    resolution: dict[str, dict] = {}
    if date is not None:
        from_local = datetime.combine(date, time.min).isoformat()
        to_local = (
            datetime.combine(date, time.min) + timedelta(days=1) - timedelta(microseconds=1)
        ).isoformat()
    for field, raw in (("from_local", from_local), ("to_local", to_local)):
        if raw is None:
            continue
        parsed = _naive_local(raw, field)
        try:
            resolved = availability.resolve_local_instant(parsed, tz_name)
        except TutoringError as exc:
            raise _typed(session, exc) from exc
        resolution[field] = {
            "requested_local": resolved.requested_local.isoformat(),
            "resolved_local": resolved.resolved_local.isoformat(),
            "instant_utc": resolved.instant_utc.isoformat(),
            "classification": resolved.classification,
            "dst_adjusted": resolved.dst_adjusted,
        }
        if field == "from_local":
            from_utc = resolved.instant_utc
        else:
            to_utc = resolved.instant_utc

    from_utc, to_utc = _aware(from_utc), _aware(to_utc)
    try:
        availability.get_tutor(session, tutor_id)  # 404 before any slot read
        slots = availability.list_slots(
            session,
            tutor_id,
            from_utc=from_utc,
            to_utc=to_utc,
            display_timezone=timezone_name,
            limit=limit,
            offset=offset,
        )
    except TutoringError as exc:
        raise _typed(session, exc) from exc
    return {
        "tutor_id": str(tutor_id),
        "iana_timezone": tz_name,
        "window": {
            "from_utc": (from_utc.isoformat() if from_utc else None),
            "to_utc": (to_utc.isoformat() if to_utc else None),
        },
        "local_resolution": resolution,
        "slots": [view.as_dict() for view in slots],
        "limit": limit,
        "offset": offset,
    }


# --------------------------------------------------------------------------- #
# B1/B2 — booking holds
# --------------------------------------------------------------------------- #


class HoldIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot_id: uuid.UUID
    idempotency_key: str = Field(min_length=1, max_length=200)


@router.post("/tutoring/booking-holds", status_code=201)
def create_booking_hold(
    payload: HoldIn,
    response: Response,
    actor: ActorContext = Depends(_student),
    session: Session = Depends(get_session),
) -> dict:
    """B1. One winner per slot; an identical key replays the SAME hold.

    A replay is answered 200 (nothing was created) and a first create 201, so a
    client can tell the two apart without parsing the body.
    """
    _limit(BOOKING, actor)
    # Asked BEFORE delegating: the service answers a replay with the existing
    # hold, and "was this key already known" is the only way to report 200-vs-201
    # honestly without the service having to grow a flag for the HTTP layer.
    replayed = bool(
        session.scalar(
            sa.select(sa.func.count())
            .select_from(BookingHold)
            .where(BookingHold.idempotency_key == payload.idempotency_key)
        )
    )
    try:
        hold = booking.create_hold(
            session,
            slot_id=payload.slot_id,
            student_user_id=actor.user_id,
            idempotency_key=payload.idempotency_key,
        )
    except TutoringError as exc:
        raise _typed(session, exc) from exc
    session.commit()
    if replayed:
        response.status_code = 200
    return _hold_out(hold, replayed=replayed)


@router.get("/tutoring/booking-holds/{hold_id}")
def get_booking_hold(
    hold_id: uuid.UUID,
    actor: ActorContext = Depends(_student),
    session: Session = Depends(get_session),
) -> dict:
    """B2. Owner-scoped: another student's hold is 404, never 403."""
    try:
        hold = booking.get_hold(session, hold_id, student_user_id=actor.user_id)
    except TutoringError as exc:
        raise _typed(session, exc) from exc
    return {
        **_hold_out(hold),
        "expired": booking.is_expired(hold),
    }


# --------------------------------------------------------------------------- #
# C1/C2/C3 — payments and session creation
# --------------------------------------------------------------------------- #


class OrderIn(BaseModel):
    """Tokenised checkout input.

    ``extra="forbid"`` is the PCI guard: ``pan``, ``card_number``, ``cvv`` and
    ``otp`` are rejected as unknown fields, and the rejection never echoes the
    submitted value (``app.core.exceptions._safe_validation_errors`` strips the
    ``input`` from every validation error). ``payment_token`` accepts a provider
    TOKEN shape only, so a PAN pasted into it fails the pattern rather than
    reaching a service, a log or a row. The token is validated and DISCARDED: no
    code path stores it.

    ``amount_paise`` IS NOT THE PRICE. The price is derived server-side from the
    hold's immutable snapshot (``booking_holds.price_paise``); this field is an
    OPTIONAL optimistic confirmation of what the checkout screen displayed, and
    a disagreement is refused with ``PAYMENT_AMOUNT_MISMATCH`` before anything
    is written or the provider is called. It is retained (rather than deleted)
    only because it is a frozen wire field that shipped clients already send;
    omitting it is now the correct and preferred call, and sending a wrong value
    can no longer under-charge anyone. Same for ``currency``.
    """

    model_config = ConfigDict(extra="forbid")

    hold_id: uuid.UUID
    idempotency_key: str = Field(min_length=1, max_length=200)
    #: Optimistic confirmation only. Never authoritative. See the class docstring.
    amount_paise: StrictInt | None = None
    currency: Literal["INR"] | None = None
    payment_token: str | None = Field(
        default=None, pattern=r"^tok_[A-Za-z0-9_]{3,60}$"
    )


@router.post("/payments/orders", status_code=201)
def create_payment_order(
    payload: OrderIn,
    response: Response,
    actor: ActorContext = Depends(_student),
    session: Session = Depends(get_session),
) -> dict:
    """C1. Order against a LIVE hold; an identical key replays the same order.

    The charged amount comes from the hold's server-side price snapshot. The
    request's ``amount_paise``/``currency``, if present, are forwarded ONLY as
    optimistic confirmations for the service to compare and discard.
    """
    _limit(BOOKING, actor)
    try:
        created = payments.create_order(
            session,
            hold_id=payload.hold_id,
            student_user_id=actor.user_id,
            amount_paise=payload.amount_paise,
            idempotency_key=payload.idempotency_key,
            currency=payload.currency,
        )
    except TutoringError as exc:
        raise _typed(session, exc) from exc
    session.commit()
    _dispatch(session, created.intents)
    if created.replayed:
        response.status_code = 200
    return _order_out(created.order, replayed=created.replayed)


@router.post("/payments/webhook")
async def payment_webhook(
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    """C2. Signature-verified provider event.

    Authorisation on this route IS the signature: there is no end-user identity
    on a provider callback, so a missing or wrong ``X-Payment-Signature`` is the
    unauthenticated case and gets ``PAYMENT_UNVERIFIED`` (400) having read and
    written nothing. Malformed body, duplicate/replayed event id, out-of-order
    delivery and amount/currency/order/user disagreement are all handled by
    ``payments.handle_event``; every refusal rolls back, so a redelivery is
    answered identically instead of half-applying.
    """
    raw = await request.body()
    if len(raw) > MAX_WEBHOOK_BYTES:
        raise _error(413, "payload_too_large", "Webhook body is too large")
    signature = request.headers.get(PAYMENT_SIGNATURE_HEADER, "")
    try:
        outcome = payments.handle_event(
            session, signature=signature, raw_body=raw
        )
    except TutoringError as exc:
        raise _typed(session, exc) from exc
    session.commit()
    _dispatch(session, outcome.intents)
    return {
        "event_type": outcome.event_type,
        "order_id": str(outcome.order.id),
        "order_status": outcome.order.status,
        "applied": not outcome.out_of_order,
        "out_of_order": outcome.out_of_order,
        "slot_released": outcome.slot_released,
        "session_id": (
            str(outcome.tutoring_session.id) if outcome.tutoring_session else None
        ),
    }


class SessionCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hold_id: uuid.UUID


@router.post("/tutoring/sessions", status_code=201)
def create_tutoring_session(
    payload: SessionCreateIn,
    response: Response,
    actor: ActorContext = Depends(_student),
    session: Session = Depends(get_session),
) -> dict:
    """C3. A session exists only for a PAID, signature-verified hold.

    Idempotent by construction: the verified ``paid`` webhook already creates the
    session, so this route normally REPLAYS it (200). An unpaid or unverified
    hold is refused with ``PAYMENT_UNVERIFIED`` and nothing is written.
    """
    _limit(BOOKING, actor)
    try:
        hold = booking.get_hold(
            session, payload.hold_id, student_user_id=actor.user_id
        )
        try:
            order = payments.order_for_hold(
                session, hold.id, student_user_id=actor.user_id
            )
        except NotFound as exc:
            # No order at all is the SAME product failure as an unpaid one:
            # "this hold was never paid for". Reporting 404 here would leak the
            # difference for no benefit.
            raise PaymentUnverified(
                "session creation requires a paid order", hold_id=str(hold.id)
            ) from exc
        created = sessions_service.create_from_paid_hold(
            session, hold=hold, order=order
        )
    except TutoringError as exc:
        raise _typed(session, exc) from exc
    session.commit()
    _dispatch(session, created.intents)
    if created.replayed:
        response.status_code = 200
    return {
        **_session_out(session, created.tutoring_session),
        "replayed": created.replayed,
        "reminder_jobs": created.reminder_jobs,
    }


# --------------------------------------------------------------------------- #
# D1 — session reads
# --------------------------------------------------------------------------- #


@router.get("/tutoring/sessions")
def list_tutoring_sessions(
    status: list[str] | None = Query(default=None),
    from_utc: datetime | None = Query(default=None),
    to_utc: datetime | None = Query(default=None),
    limit: int = Query(default=50),
    offset: int = Query(default=0),
    actor: ActorContext = Depends(_participant),
    session: Session = Depends(get_session),
) -> dict:
    """D1. Scoped to the caller: a student sees theirs, a tutor sees theirs."""
    role = _service_role(actor)
    try:
        rows = sessions_service.list_sessions(
            session,
            user_id=actor.user_id,
            role=role,
            statuses=tuple(status) if status else None,
            from_utc=from_utc,
            to_utc=to_utc,
            limit=limit,
            offset=offset,
        )
    except TutoringError as exc:
        raise _typed(session, exc) from exc
    return {
        "items": [_session_out(session, row) for row in rows],
        "role": role,
        "limit": limit,
        "offset": offset,
    }


@router.get("/tutoring/sessions/{session_id}")
def get_tutoring_session(
    session_id: uuid.UUID,
    actor: ActorContext = Depends(_participant),
    session: Session = Depends(get_session),
) -> dict:
    """D1. Cross-user isolation: someone else's session is 404, never 403."""
    try:
        sess = sessions_service.get_session(
            session, session_id, user_id=actor.user_id, role=_service_role(actor)
        )
    except TutoringError as exc:
        raise _typed(session, exc) from exc
    return _session_out(session, sess)


# --------------------------------------------------------------------------- #
# D2/D3 — reschedule and cancel
# --------------------------------------------------------------------------- #


class RescheduleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_slot_id: uuid.UUID
    expected_version: StrictInt | None = None
    reason: str | None = Field(default=None, max_length=200)
    #: Admin-only escape hatch inside the notice window. The service refuses it
    #: for any other role, so a student setting it gains nothing.
    admin_exception: bool = False


@router.post("/tutoring/sessions/{session_id}/reschedule")
def reschedule_session(
    session_id: uuid.UUID,
    payload: RescheduleIn,
    actor: ActorContext = Depends(_participant),
    session: Session = Depends(get_session),
) -> dict:
    """D2. Free at/after the configured notice window; refused inside it."""
    _limit(BOOKING, actor)
    role = _service_role(actor)
    try:
        mutation = sessions_service.reschedule(
            session,
            session_id,
            new_slot_id=payload.new_slot_id,
            actor_user_id=actor.user_id,
            actor_role=role,
            expected_version=payload.expected_version,
            admin_exception=payload.admin_exception,
            admin_actor_id=(actor.user_id if role == "admin" else None),
            reason=payload.reason,
        )
    except TutoringError as exc:
        raise _typed(session, exc) from exc
    session.commit()
    _dispatch(session, mutation.intents)
    return {
        **_session_out(session, mutation.tutoring_session),
        "reminders_revoked": mutation.reminders_revoked,
    }


class CancelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: StrictInt | None = None
    reason: str | None = Field(default=None, max_length=200)
    admin_exception: bool = False
    exception_amount_paise: StrictInt | None = None


@router.post("/tutoring/sessions/{session_id}/cancel")
def cancel_session(
    session_id: uuid.UUID,
    payload: CancelIn,
    actor: ActorContext = Depends(_participant),
    session: Session = Depends(get_session),
) -> dict:
    """D3. The frozen refund policy is the service's; this maps its verdict."""
    _limit(BOOKING, actor)
    role = _service_role(actor)
    try:
        mutation = sessions_service.cancel(
            session,
            session_id,
            actor_user_id=actor.user_id,
            actor_role=role,
            expected_version=payload.expected_version,
            admin_exception=payload.admin_exception,
            admin_actor_id=(actor.user_id if role == "admin" else None),
            exception_amount_paise=payload.exception_amount_paise,
            reason=payload.reason,
        )
    except TutoringError as exc:
        raise _typed(session, exc) from exc
    session.commit()
    _dispatch(session, mutation.intents)
    return {
        **_session_out(session, mutation.tutoring_session),
        "refund": (
            mutation.refund_assessment.as_dict()
            if mutation.refund_assessment
            else None
        ),
        "refund_id": (str(mutation.refund_id) if mutation.refund_id else None),
        "reminders_revoked": mutation.reminders_revoked,
    }


# --------------------------------------------------------------------------- #
# D4/D5 — completion and attendance
# --------------------------------------------------------------------------- #


@router.post("/tutoring/sessions/{session_id}/complete")
def complete_session(
    session_id: uuid.UUID,
    actor: ActorContext = Depends(_participant),
    session: Session = Depends(get_session),
) -> dict:
    """D4. Tutor or admin, and only AFTER the scheduled end (no early finish)."""
    try:
        mutation = attendance_service.record(
            session,
            session_id,
            actor_user_id=actor.user_id,
            actor_role=_service_role(actor),
        )
    except TutoringError as exc:
        raise _typed(session, exc) from exc
    session.commit()
    _dispatch(session, mutation.intents)
    return _attendance_out(mutation)


class AttendanceConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: StrictInt | None = None


class AttendanceDisputeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: StrictInt | None = None
    #: A CODE, never the student's narrative — it reaches operators and audit.
    reason_code: str | None = Field(
        default=None, max_length=40, pattern=r"^[a-z0-9_]+$"
    )


class AttendanceResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution: str = Field(max_length=24)
    expected_version: StrictInt | None = None
    reason_code: str | None = Field(
        default=None, max_length=40, pattern=r"^[a-z0-9_]+$"
    )


@router.post("/tutoring/sessions/{session_id}/attendance/confirm")
def confirm_attendance(
    session_id: uuid.UUID,
    payload: AttendanceConfirmIn | None = None,
    actor: ActorContext = Depends(_student),
    session: Session = Depends(get_session),
) -> dict:
    """D5. The STUDENT confirms what the tutor recorded."""
    try:
        mutation = attendance_service.confirm(
            session,
            session_id,
            actor_user_id=actor.user_id,
            expected_version=(payload.expected_version if payload else None),
        )
    except TutoringError as exc:
        raise _typed(session, exc) from exc
    session.commit()
    return _attendance_out(mutation)


@router.post("/tutoring/sessions/{session_id}/attendance/dispute")
def dispute_attendance(
    session_id: uuid.UUID,
    payload: AttendanceDisputeIn | None = None,
    actor: ActorContext = Depends(_student),
    session: Session = Depends(get_session),
) -> dict:
    """D5. The STUDENT disputes it; the session becomes ``disputed``."""
    try:
        mutation = attendance_service.dispute(
            session,
            session_id,
            actor_user_id=actor.user_id,
            expected_version=(payload.expected_version if payload else None),
            reason_code=(payload.reason_code if payload else None),
        )
    except TutoringError as exc:
        raise _typed(session, exc) from exc
    session.commit()
    return _attendance_out(mutation)


@router.post("/tutoring/sessions/{session_id}/attendance/resolve")
def resolve_attendance(
    session_id: uuid.UUID,
    payload: AttendanceResolveIn,
    actor: ActorContext = Depends(_admin),
    session: Session = Depends(get_session),
) -> dict:
    """D5. ADMIN only; the allowed resolutions are the service's list."""
    try:
        mutation = attendance_service.resolve(
            session,
            session_id,
            admin_user_id=actor.user_id,
            resolution=payload.resolution,
            actor_role="admin",
            expected_version=payload.expected_version,
            reason_code=payload.reason_code,
        )
    except TutoringError as exc:
        raise _typed(session, exc) from exc
    session.commit()
    return _attendance_out(mutation)


# --------------------------------------------------------------------------- #
# E1/E2 — join credentials and the video webhook
# --------------------------------------------------------------------------- #


@router.get("/tutoring/capabilities")
def tutoring_capabilities() -> dict:
    """Public, secret-free runtime availability for S-35.

    Frontend builds are immutable but the operational video switch is not. The
    UI reads this endpoint before opening devices or offering Join, so a normal
    disable is immediately visible without rebuilding JavaScript. No API key,
    internal service URL or deployment secret is exposed.
    """
    provider = (settings.video_provider or "none").strip().lower()
    enabled = bool(settings.video_calls_enabled and provider != "none")
    return {
        "video_calls_enabled": enabled,
        "video_transport": provider if enabled else "none",
        "video_room_url": (
            settings.livekit_public_url.strip()
            if enabled and provider == "livekit" and settings.livekit_public_url
            else None
        ),
        "video_ice_transport_policy": settings.video_ice_transport_policy.strip().lower(),
        "join_credential_ttl_seconds": settings.join_credential_ttl_seconds,
        "recording_enabled": False,
    }


@router.post("/tutoring/sessions/{session_id}/join-credentials", status_code=201)
def issue_join_credentials(
    session_id: uuid.UUID,
    actor: ActorContext = Depends(_participant),
    session: Session = Depends(get_session),
) -> dict:
    """E1. The ONLY place a raw join token is ever exposed.

    It appears in this response body and nowhere else: the grant row stores a
    SHA-256 hash, the audit row stores neither the token nor its hash, and no
    outbox row is written at all. Issuing supersedes (revokes) the caller's
    previous APPLICATION grant. Self-hosted LiveKit JWTs are stateless and may
    remain provider-valid until their five-minute expiry unless the participant
    is explicitly removed; the application therefore never presents an old
    grant again and bounds that residual provider lifetime with the TTL.
    """
    try:
        issued = join_credentials.issue(
            session,
            session_id,
            actor_user_id=actor.user_id,
            actor_role=_service_role(actor),
        )
    except TutoringError as exc:
        raise _typed(session, exc) from exc
    session.commit()
    return {
        "session_id": str(session_id),
        "grant_id": str(issued.grant.id),
        "room_ref": issued.room_ref,
        "participant_ref": issued.grant.participant_ref,
        "permissions": issued.permissions,
        "join_token": issued.raw_token,
        "issued_at": _iso(issued.issued_at),
        "expires_at": _iso(issued.expires_at),
        "ttl_seconds": issued.ttl_seconds,
        "superseded": issued.superseded,
        "video_room_url": (
            settings.livekit_public_url.strip()
            if (settings.video_provider or "").strip().lower() == "livekit"
            and settings.livekit_public_url
            else None
        ),
        "video_ice_transport_policy": settings.video_ice_transport_policy.strip().lower(),
    }


@router.post("/video/webhook")
async def video_webhook(
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    """E2. Signature-verified room event; duplicates and replays are refused.

    Same shape as the payment webhook: the signature IS the authorisation, an
    unverifiable delivery is ``VIDEO_UNVERIFIED`` (400) with nothing read or
    written, a redelivered ``provider_event_id`` is ``DUPLICATE_EVENT`` (409),
    and a join announced with an expired/revoked/superseded grant is
    ``GRANT_EXPIRED``/``GRANT_REVOKED`` (410). Media-plane data (SDP, ICE,
    device labels) is refused by the provider adapter before this code sees it.

    This handler makes exactly TWO decisions — the body is not absurdly large,
    and the transaction is committed only if the domain succeeded. It does not
    know, and must not know, WHICH header carries the signature: it forwards the
    RAW body (re-serialising would break LiveKit's body digest) plus the headers
    as received, and the configured adapter reads the one it signs. Every
    business rule, including "is this delivery authentic", stays in the
    provider/service layer.
    """
    raw = await request.body()
    if len(raw) > MAX_WEBHOOK_BYTES:
        raise _error(413, "payload_too_large", "Webhook body is too large")
    try:
        outcome = join_credentials.handle_event(
            session, raw_body=raw, headers=dict(request.headers)
        )
    except TutoringError as exc:
        raise _typed(session, exc) from exc
    session.commit()
    return {
        "event_type": outcome.event_type,
        "provider_event_id": outcome.provider_event_id,
        "session_id": str(outcome.tutoring_session.id),
        "session_status": outcome.tutoring_session.status,
        "participant_ref": outcome.participant_ref,
        "grants_revoked": outcome.revoked,
    }


# --------------------------------------------------------------------------- #
# F1/F2/F3 — reviews and moderation
# --------------------------------------------------------------------------- #


class ReviewIn(BaseModel):
    """Rating/text bounds are NOT restated here on purpose.

    ``rating`` is a strict integer and ``body`` an optional bounded string, so
    the shape is validated at the boundary — but 1..5 and 10..1000 are the
    frozen PRODUCT rules and stay in ``reviews.validate_rating`` /
    ``validate_body``, which is what the ``VALIDATION_ERROR`` envelope proves.
    """

    model_config = ConfigDict(extra="forbid")

    rating: StrictInt
    body: str | None = Field(default=None, max_length=4000)


class ReviewPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rating: StrictInt | None = None
    body: str | None = Field(default=None, max_length=4000)


class ModerateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(max_length=16)
    reason: str | None = Field(default=None, max_length=200)


@router.post("/tutoring/sessions/{session_id}/review", status_code=201)
def create_review(
    session_id: uuid.UUID,
    payload: ReviewIn,
    actor: ActorContext = Depends(_student),
    session: Session = Depends(get_session),
) -> dict:
    """F1/F2. One review per session, gated on CONFIRMED attendance."""
    _limit(REVIEW, actor)
    try:
        mutation = reviews_service.create(
            session,
            session_id=session_id,
            author_user_id=actor.user_id,
            rating=payload.rating,
            body=payload.body,
        )
    except TutoringError as exc:
        raise _typed(session, exc) from exc
    session.commit()
    _dispatch(session, mutation.intents)
    return _review_out(mutation)


@router.patch("/tutoring/reviews/{review_id}")
def edit_review(
    review_id: uuid.UUID,
    payload: ReviewPatch,
    actor: ActorContext = Depends(_student),
    session: Session = Depends(get_session),
) -> dict:
    """F1. Author-only, inside the 7-day window; new text re-enters moderation.

    ``body`` is forwarded ONLY when the client actually sent the key, so
    ``{"rating": 5}`` leaves existing text alone while ``{"body": null}``
    deliberately removes it — the distinction ``reviews.edit`` expects from its
    ``_UNSET`` sentinel.
    """
    _limit(REVIEW, actor)
    kwargs: dict = {}
    if "body" in payload.model_fields_set:
        kwargs["body"] = payload.body
    try:
        mutation = reviews_service.edit(
            session,
            review_id,
            author_user_id=actor.user_id,
            rating=payload.rating,
            **kwargs,
        )
    except TutoringError as exc:
        raise _typed(session, exc) from exc
    session.commit()
    _dispatch(session, mutation.intents)
    return _review_out(mutation)


@router.delete("/tutoring/reviews/{review_id}")
def delete_review(
    review_id: uuid.UUID,
    actor: ActorContext = Depends(_student),
    session: Session = Depends(get_session),
) -> dict:
    """F1. Author-only soft delete; drops out of the public aggregate at once."""
    _limit(REVIEW, actor)
    try:
        mutation = reviews_service.delete(
            session, review_id, author_user_id=actor.user_id
        )
    except TutoringError as exc:
        raise _typed(session, exc) from exc
    session.commit()
    return _review_out(mutation)


@router.post("/tutoring/reviews/{review_id}/moderate")
def moderate_review(
    review_id: uuid.UUID,
    payload: ModerateIn,
    actor: ActorContext = Depends(_admin),
    session: Session = Depends(get_session),
) -> dict:
    """F3. Role-gated approve/reject. Approval is what publishes the text.

    Not rate limited by ``rate_limit_review_per_hour``: that limit exists to
    stop a student flooding a tutor with review writes, and applying it to a
    moderator would cap the queue at five decisions an hour.
    """
    try:
        mutation = reviews_service.moderate(
            session,
            review_id,
            moderator_user_id=actor.user_id,
            decision=payload.decision,
            actor_role="admin",
            reason=payload.reason,
        )
    except TutoringError as exc:
        raise _typed(session, exc) from exc
    session.commit()
    _dispatch(session, mutation.intents)
    return _review_out(mutation)
