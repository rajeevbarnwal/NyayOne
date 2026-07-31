"""Tutor discovery + availability (SAATHI-123 / SAATHI-127 P2).

Read-only surface: search, profile fetch, slot listing. No mutation, therefore
no audit rows and no outbox rows are written here.

Time model (frozen decision: "instants UTC + retain IANA tz")
-------------------------------------------------------------
Every instant is stored and compared in UTC (``start_utc`` / ``end_utc``); the
slot additionally retains the IANA zone (``iana_timezone``) that the wall-clock
label must be rendered in. Rendering UTC -> local is always unambiguous, so
:func:`to_local` needs no DST policy.

The DST hazard is the OTHER direction: turning a tutor's *local wall time* into
an instant. :func:`resolve_local_instant` handles both pathological cases with
:mod:`zoneinfo` (PEP 495 ``fold``) and REPORTS which one it hit, so callers can
warn the tutor instead of silently mis-scheduling:

* **ambiguous** (autumn fall-back, e.g. 2026-11-01 01:30 America/New_York
  happens twice): the two folds have different UTC offsets and BOTH map back to
  the requested wall time. Policy: choose the FIRST/earlier occurrence
  (``fold=0``, still on DST). Deterministic, never later than the tutor meant.
* **nonexistent** (spring forward, e.g. 2026-03-08 02:30 America/New_York never
  happens): the two folds have different offsets and NEITHER maps back. Policy:
  keep the ``fold=0`` instant, which is exactly the requested wall time pushed
  FORWARD by the length of the gap (02:30 -> 03:30 local). The slot therefore
  lands immediately after the transition rather than before it, and never
  vanishes or silently shifts a day.
* **unique**: the ordinary case; both folds agree.

Asia/Kolkata (the product's default zone) has no DST at all, so the frozen
fixture slot is always in the ``unique`` branch — the policy exists for tutors
in DST zones and is unit-tested with America/New_York.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.wave2 import TutorAvailabilitySlot, TutorProfile, TutorSubject
from app.services.tutoring import pricing
from app.services.tutoring.errors import NotFound, ValidationError

DEFAULT_TIMEZONE = "Asia/Kolkata"

SORTS = (
    "rating_desc",
    "rating_asc",
    "experience_desc",
    "experience_asc",
    "name_asc",
    "newest",
)
MAX_PAGE_SIZE = 100


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Timezone helpers
# --------------------------------------------------------------------------- #

UNIQUE = "unique"
AMBIGUOUS = "ambiguous"
NONEXISTENT = "nonexistent"


def zone(tz_name: str | None) -> ZoneInfo:
    """Load an IANA zone, raising a typed validation error for a bad name."""
    name = (tz_name or DEFAULT_TIMEZONE).strip()
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        raise ValidationError(
            f"unknown IANA timezone: {name}", field="iana_timezone"
        ) from exc


@dataclass(frozen=True)
class LocalInstant:
    """The UTC instant a local wall time resolves to, plus how it resolved."""

    instant_utc: datetime
    classification: str  # unique | ambiguous | nonexistent
    iana_timezone: str
    requested_local: datetime
    resolved_local: datetime

    @property
    def dst_adjusted(self) -> bool:
        return self.classification != UNIQUE


def resolve_local_instant(local_naive: datetime, tz_name: str) -> LocalInstant:
    """Convert a NAIVE local wall time to UTC, DST-safely and reproducibly.

    See the module docstring for the ambiguous / nonexistent policy. Passing an
    aware datetime is a programming error (the whole point is to resolve a wall
    time), so it is rejected with a typed validation error.
    """
    if local_naive.tzinfo is not None:
        raise ValidationError(
            "resolve_local_instant expects a naive local wall time",
            field="local_naive",
        )
    tz = zone(tz_name)
    fold0 = local_naive.replace(tzinfo=tz, fold=0)
    fold1 = local_naive.replace(tzinfo=tz, fold=1)
    instant = fold0.astimezone(timezone.utc)
    resolved_local = instant.astimezone(tz)
    if fold0.utcoffset() == fold1.utcoffset():
        classification = UNIQUE
    elif resolved_local.replace(tzinfo=None) == local_naive:
        # Both folds are valid wall times -> fall-back overlap. We keep fold=0,
        # the EARLIER of the two occurrences.
        classification = AMBIGUOUS
    else:
        # Neither fold maps back -> spring-forward gap. The fold=0 instant is the
        # requested time shifted FORWARD past the gap (02:30 -> 03:30).
        classification = NONEXISTENT
    return LocalInstant(
        instant_utc=instant,
        classification=classification,
        iana_timezone=tz.key,
        requested_local=local_naive,
        resolved_local=resolved_local,
    )


def to_local(instant_utc: datetime, tz_name: str) -> datetime:
    """Render a stored instant in an IANA zone. Always unambiguous."""
    if instant_utc.tzinfo is None:
        instant_utc = instant_utc.replace(tzinfo=timezone.utc)
    return instant_utc.astimezone(zone(tz_name))


# --------------------------------------------------------------------------- #
# Tutor search
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TutorSearchPage:
    items: tuple[TutorProfile, ...]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


def _paging(limit: int, offset: int) -> tuple[int, int]:
    if limit is None or limit <= 0 or limit > MAX_PAGE_SIZE:
        raise ValidationError(
            f"limit must be between 1 and {MAX_PAGE_SIZE}", field="limit"
        )
    if offset is None or offset < 0:
        raise ValidationError("offset must not be negative", field="offset")
    return limit, offset


def _apply_sort(stmt: Select, sort: str) -> Select:
    """Apply the sort PLUS a total tie-break so pagination is deterministic.

    Two tutors with the same rating must always come back in the same order for
    page 1 and page 2 of the same query; ``display_name`` then ``id`` guarantees
    a total order on every dialect.
    """
    if sort not in SORTS:
        raise ValidationError(f"unknown sort: {sort}", field="sort")
    rating = func.coalesce(TutorProfile.rating_avg, 0)
    primary = {
        "rating_desc": (rating.desc(), TutorProfile.rating_count.desc()),
        "rating_asc": (rating.asc(), TutorProfile.rating_count.asc()),
        "experience_desc": (TutorProfile.experience_years.desc(),),
        "experience_asc": (TutorProfile.experience_years.asc(),),
        "name_asc": (),
        "newest": (TutorProfile.created_at.desc(),),
    }[sort]
    return stmt.order_by(*primary, TutorProfile.display_name.asc(), TutorProfile.id.asc())


def search_tutors(
    session: Session,
    *,
    subject: str | None = None,
    level: str | None = None,
    min_rating: float | None = None,
    min_experience_years: int | None = None,
    verified_only: bool = False,
    query: str | None = None,
    sort: str = "rating_desc",
    limit: int = 20,
    offset: int = 0,
) -> TutorSearchPage:
    """Filtered, sorted, deterministically paginated tutor search.

    Only ``active`` and non-soft-deleted profiles are ever visible — a draft,
    suspended or retired tutor is not discoverable. Returns the page plus the
    unpaginated total so P3 can render "showing 1-20 of N".
    """
    limit, offset = _paging(limit, offset)
    filters = [TutorProfile.status == "active", TutorProfile.deleted_at.is_(None)]
    if subject:
        subject_exists = (
            select(TutorSubject.id)
            .where(
                TutorSubject.tutor_id == TutorProfile.id,
                func.lower(TutorSubject.subject) == subject.strip().lower(),
            )
            .exists()
        )
        if level:
            subject_exists = (
                select(TutorSubject.id)
                .where(
                    TutorSubject.tutor_id == TutorProfile.id,
                    func.lower(TutorSubject.subject) == subject.strip().lower(),
                    func.lower(TutorSubject.level) == level.strip().lower(),
                )
                .exists()
            )
        filters.append(subject_exists)
    elif level:
        filters.append(
            select(TutorSubject.id)
            .where(
                TutorSubject.tutor_id == TutorProfile.id,
                func.lower(TutorSubject.level) == level.strip().lower(),
            )
            .exists()
        )
    if min_rating is not None:
        if min_rating < 0 or min_rating > 5:
            raise ValidationError("min_rating must be 0..5", field="min_rating")
        filters.append(func.coalesce(TutorProfile.rating_avg, 0) >= min_rating)
    if min_experience_years is not None:
        if min_experience_years < 0:
            raise ValidationError(
                "min_experience_years must not be negative",
                field="min_experience_years",
            )
        filters.append(TutorProfile.experience_years >= min_experience_years)
    if verified_only:
        filters.append(TutorProfile.verified_identity.is_(True))
        filters.append(TutorProfile.verified_credentials.is_(True))
    if query:
        needle = f"%{query.strip().lower()}%"
        filters.append(
            func.lower(TutorProfile.display_name).like(needle)
            | func.lower(func.coalesce(TutorProfile.headline, "")).like(needle)
        )

    total = session.scalar(
        select(func.count()).select_from(TutorProfile).where(*filters)
    ) or 0
    stmt = _apply_sort(select(TutorProfile).where(*filters), sort)
    items = session.scalars(stmt.limit(limit).offset(offset)).all()
    return TutorSearchPage(items=tuple(items), total=total, limit=limit, offset=offset)


def get_tutor(session: Session, tutor_id: uuid.UUID, *, include_inactive: bool = False) -> TutorProfile:
    """Fetch one visible tutor profile or raise NOT_FOUND."""
    stmt = select(TutorProfile).where(
        TutorProfile.id == tutor_id, TutorProfile.deleted_at.is_(None)
    )
    if not include_inactive:
        stmt = stmt.where(TutorProfile.status == "active")
    tutor = session.scalars(stmt).first()
    if tutor is None:
        raise NotFound("tutor not found", resource="tutor")
    return tutor


def list_subjects(session: Session, tutor_id: uuid.UUID) -> tuple[TutorSubject, ...]:
    return tuple(
        session.scalars(
            select(TutorSubject)
            .where(TutorSubject.tutor_id == tutor_id)
            .order_by(TutorSubject.subject, TutorSubject.level, TutorSubject.id)
        ).all()
    )


# --------------------------------------------------------------------------- #
# Slot listing
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SlotView:
    """A slot rendered for display: UTC instants + an IANA-local projection."""

    slot_id: uuid.UUID
    tutor_id: uuid.UUID
    start_utc: datetime
    end_utc: datetime
    iana_timezone: str
    status: str
    start_local: datetime
    end_local: datetime
    duration_minutes: int
    #: The SERVER-AUTHORITATIVE price of booking this slot, in INTEGER PAISE.
    #: Published so a checkout screen can RENDER the amount instead of reading a
    #: deployment env var and guessing; it is never accepted back as an input.
    price_paise: int = 0
    currency: str = "INR"

    def as_dict(self) -> dict:
        return {
            "slot_id": str(self.slot_id),
            "tutor_id": str(self.tutor_id),
            "start_utc": self.start_utc.isoformat(),
            "end_utc": self.end_utc.isoformat(),
            "iana_timezone": self.iana_timezone,
            "status": self.status,
            "start_local": self.start_local.isoformat(),
            "end_local": self.end_local.isoformat(),
            "duration_minutes": self.duration_minutes,
            "price_paise": self.price_paise,
            "currency": self.currency,
        }


def list_slots(
    session: Session,
    tutor_id: uuid.UUID,
    *,
    from_utc: datetime | None = None,
    to_utc: datetime | None = None,
    statuses: tuple[str, ...] = ("available",),
    display_timezone: str | None = None,
    limit: int = 50,
    offset: int = 0,
    now: datetime | None = None,
) -> tuple[SlotView, ...]:
    """List a tutor's slots as UTC instants plus an IANA-local projection.

    ``display_timezone`` overrides the slot's stored zone (a student in another
    zone viewing an Indian tutor); when omitted each slot renders in its own
    retained ``iana_timezone``. Past slots are excluded by default so a student
    can never be shown an unbookable time.
    """
    limit, offset = _paging(limit, offset)
    now = now or utcnow()
    lower = from_utc or now
    filters = [
        TutorAvailabilitySlot.tutor_id == tutor_id,
        TutorAvailabilitySlot.deleted_at.is_(None),
        TutorAvailabilitySlot.start_utc >= lower,
    ]
    if to_utc is not None:
        filters.append(TutorAvailabilitySlot.start_utc <= to_utc)
    if statuses:
        filters.append(TutorAvailabilitySlot.status.in_(statuses))
    if display_timezone:
        zone(display_timezone)  # validate early, typed error
    rows = session.scalars(
        select(TutorAvailabilitySlot)
        .where(*filters)
        # Deterministic: start then id, so equal starts never reorder.
        .order_by(TutorAvailabilitySlot.start_utc.asc(), TutorAvailabilitySlot.id.asc())
        .limit(limit)
        .offset(offset)
    ).all()
    # One batched price read for the whole page (never per row), so the amount a
    # student is shown comes from the same authority the hold will snapshot.
    prices = pricing.published_prices(session, tuple({row.tutor_id for row in rows}))
    views: list[SlotView] = []
    for row in rows:
        tz_name = display_timezone or row.iana_timezone
        price = prices.get(row.tutor_id)
        start_utc = row.start_utc if row.start_utc.tzinfo else row.start_utc.replace(tzinfo=timezone.utc)
        end_utc = row.end_utc if row.end_utc.tzinfo else row.end_utc.replace(tzinfo=timezone.utc)
        views.append(
            SlotView(
                slot_id=row.id,
                tutor_id=row.tutor_id,
                start_utc=start_utc,
                end_utc=end_utc,
                iana_timezone=tz_name,
                status=row.status,
                start_local=to_local(start_utc, tz_name),
                end_local=to_local(end_utc, tz_name),
                duration_minutes=int((end_utc - start_utc).total_seconds() // 60),
                price_paise=(price.amount_paise if price else 0),
                currency=(price.currency if price else "INR"),
            )
        )
    return tuple(views)


def get_slot(session: Session, slot_id: uuid.UUID) -> TutorAvailabilitySlot:
    slot = session.get(TutorAvailabilitySlot, slot_id)
    if slot is None or slot.deleted_at is not None:
        raise NotFound("slot not found", resource="slot")
    return slot
