"""The ONE seam that decides what a tutoring session costs (SAATHI-123/127).

Wave 2 shipped with the price client-authoritative: ``POST /payments/orders``
read ``amount_paise`` out of the request body, so a malicious client could open
a zero-priced or under-priced order and a correctly signed provider callback
would then only ever prove payment of the attacker-chosen amount. The signature
was never the weak link. This module is the fix: the price is RESOLVED from the
database, snapshotted onto the booking hold, and copied from that snapshot into
the payment order. No request value reaches any of those three steps.

Frozen rules implemented here
-----------------------------
* **INR INTEGER PAISE only.** Not one float, ``Decimal`` or division exists in
  this module or in anything it hands a number to. ``assert_price_paise``
  rejects ``bool``, ``float``, ``Decimal`` and ``str`` outright — ``bool``
  first, because ``isinstance(True, int)`` is true in Python and ``True`` would
  otherwise price a session at one paisa.
* **Strictly positive.** 0 is NOT free tutoring. A free offering would need its
  own explicit product flag (``Product``-level, deliberately not modelled yet);
  inferring "free" from a 0 is exactly how a tampered order becomes
  indistinguishable from a legitimate one. Every seam that could WRITE a price
  refuses 0 and negatives with ``SESSION_PRICE_INVALID``, and the ``> 0`` CHECK
  constraints added by migration 0009 refuse them again at the database.
* **Resolution reads, it never writes.** :func:`resolve_for_slot` and
  :func:`resolve_for_tutor` are pure reads; the only writer is
  :func:`set_tutor_session_price`, which is the administrative seam and is
  audited.
* **The hold snapshot is immutable.** :func:`snapshot_of_hold` only reads
  ``booking_holds.price_paise`` / ``price_currency``; nothing in this package
  UPDATEs them after ``booking.create_hold`` INSERTs them. A re-price therefore
  cannot move the amount of a checkout already in flight, and an idempotent
  hold replay returns the original number.

Why the price lives on ``tutor_profiles`` and not on the slot: a price is a
property of the tutor's offering, while ``tutor_availability_slots`` rows are
generated in bulk from a calendar and carry no commercial data. Every caller
goes through :func:`resolve_for_slot`, so if a per-slot override is ever added
it is one column plus one branch here, and no other module changes.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.wave2 import (
    PAYMENT_CURRENCIES,
    BookingHold,
    TutorAvailabilitySlot,
    TutorProfile,
)
from app.services.audit_service import record_audit_event
from app.services.tutoring.errors import (
    NotFound,
    SessionPriceInvalid,
    ValidationError,
)

#: The only currency the product supports today. Kept as a name, not a literal
#: sprinkled through the module, so widening it is one edit plus a CHECK change.
DEFAULT_CURRENCY = "INR"

#: Deployment-wide fallback, in INTEGER PAISE, used when a tutor profile has not
#: published its own price. Mirrored by the ORM column default and by migration
#: 0009's ``DEFAULT_SESSION_PRICE_PAISE``; the three are pinned equal by
#: ``tests/test_wave2_pricing_authority.py`` so they can never drift apart.
FALLBACK_SESSION_PRICE_PAISE = 250_000

#: Where a resolved price came from. Reported to the caller (and to audit) so a
#: student-visible amount is always traceable to a row, never to a guess.
SOURCE_TUTOR_PROFILE = "tutor_profile"
SOURCE_HOLD_SNAPSHOT = "hold_snapshot"


@dataclass(frozen=True)
class SessionPrice:
    """A resolved, server-authoritative price. Amount is INTEGER PAISE."""

    amount_paise: int
    currency: str
    source: str
    tutor_id: uuid.UUID | None = None

    def as_dict(self) -> dict:
        return {
            "amount_paise": self.amount_paise,
            "currency": self.currency,
            "source": self.source,
        }


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def assert_price_paise(value: object, *, field_name: str = "session_price_paise") -> int:
    """A session price is a STRICTLY POSITIVE integer number of paise.

    ``bool`` is rejected before the ``int`` test on purpose: ``True`` is an
    ``int`` in Python and would otherwise be accepted as one paisa.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise SessionPriceInvalid(
            "session price must be an integer number of paise", field=field_name
        )
    if value <= 0:
        # Not "non-negative": see the module docstring — 0 is not free tutoring.
        raise SessionPriceInvalid(
            "session price must be strictly positive",
            field=field_name,
            offered_paise=value,
        )
    return value


def assert_currency(value: object, *, field_name: str = "currency") -> str:
    if not isinstance(value, str) or value not in PAYMENT_CURRENCIES:
        raise ValidationError(
            f"only {'/'.join(PAYMENT_CURRENCIES)} is supported", field=field_name
        )
    return value


def default_session_price_paise() -> int:
    """The configured deployment fallback, re-validated on every read.

    ``Settings`` already refuses to boot on a non-positive value; this second
    check exists because a test or an operator tool can mutate ``settings`` in
    process, and a mispriced fallback must fail loudly at the seam rather than
    quietly stamping a 0 onto a profile.
    """
    return assert_price_paise(
        getattr(
            settings,
            "tutoring_default_session_price_paise",
            FALLBACK_SESSION_PRICE_PAISE,
        ),
        field_name="tutoring_default_session_price_paise",
    )


# --------------------------------------------------------------------------- #
# Resolution (read-only)
# --------------------------------------------------------------------------- #


def _price_of(tutor: TutorProfile) -> SessionPrice:
    return SessionPrice(
        amount_paise=assert_price_paise(tutor.session_price_paise),
        currency=assert_currency(tutor.session_currency),
        source=SOURCE_TUTOR_PROFILE,
        tutor_id=tutor.id,
    )


def resolve_for_tutor(session: Session, tutor_id: uuid.UUID) -> SessionPrice:
    """The authoritative price for one tutor. Reads only; never writes."""
    tutor = session.get(TutorProfile, tutor_id)
    if tutor is None or tutor.deleted_at is not None:
        raise NotFound("tutor not found", resource="tutor")
    return _price_of(tutor)


def resolve_for_slot(
    session: Session, slot: TutorAvailabilitySlot | uuid.UUID
) -> SessionPrice:
    """The authoritative price for the session that would fill this slot.

    The single entry point every booking path uses, so "what does this cost"
    has exactly one answer and one place to change.
    """
    if isinstance(slot, uuid.UUID):
        row = session.get(TutorAvailabilitySlot, slot)
        if row is None or row.deleted_at is not None:
            raise NotFound("slot not found", resource="slot")
        slot = row
    return resolve_for_tutor(session, slot.tutor_id)


def snapshot_of_hold(hold: BookingHold) -> SessionPrice:
    """The IMMUTABLE price frozen onto a hold when it was created.

    This — not the tutor profile, and emphatically not the request — is what
    ``payments.create_order`` charges. Re-validated on read so a row that was
    somehow written past the CHECK constraints still cannot fund an order.
    """
    return SessionPrice(
        amount_paise=assert_price_paise(hold.price_paise, field_name="price_paise"),
        currency=assert_currency(hold.price_currency, field_name="price_currency"),
        source=SOURCE_HOLD_SNAPSHOT,
    )


# --------------------------------------------------------------------------- #
# The one writer
# --------------------------------------------------------------------------- #


def set_tutor_session_price(
    session: Session,
    tutor_id: uuid.UUID,
    *,
    amount_paise: int,
    currency: str = DEFAULT_CURRENCY,
    actor_role: str = "admin",
    actor_user_id: uuid.UUID | None = None,
) -> TutorProfile:
    """Publish a tutor's session price. Validated, audited, does not commit.

    The ONLY seam in the product that may create a session price, which is what
    makes "a zero or negative authoritative price is impossible" testable in one
    place instead of being a property nobody owns.
    """
    amount = assert_price_paise(amount_paise)
    money = assert_currency(currency)
    tutor = session.get(TutorProfile, tutor_id)
    if tutor is None or tutor.deleted_at is not None:
        raise NotFound("tutor not found", resource="tutor")
    before = {
        "session_price_paise": tutor.session_price_paise,
        "session_currency": tutor.session_currency,
    }
    tutor.session_price_paise = amount
    tutor.session_currency = money
    session.flush()
    record_audit_event(
        session,
        action="tutoring.pricing.session_price_set",
        resource_type="tutor_profile",
        resource_id=tutor.id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        before_state=before,
        after_state={"session_price_paise": amount, "session_currency": money},
    )
    session.flush()
    return tutor


def published_prices(
    session: Session, tutor_ids: tuple[uuid.UUID, ...]
) -> dict[uuid.UUID, SessionPrice]:
    """Batch read for list projections (search results, availability pages)."""
    if not tutor_ids:
        return {}
    rows = session.scalars(
        select(TutorProfile).where(TutorProfile.id.in_(tutor_ids))
    ).all()
    return {row.id: _price_of(row) for row in rows}
