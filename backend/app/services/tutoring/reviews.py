"""Reviews, moderation and the public aggregate (SAATHI-127 P2, matrix F1-F3).

Frozen decisions implemented here
---------------------------------
* **Rating is an INTEGER 1..5.** ``True``/``4.5``/``"4"`` are rejected before the
  database is touched (``bool`` is a subclass of ``int``, so it is excluded
  explicitly); the ``ck_tutor_reviews_rating_range`` CHECK is the second line of
  defence.
* **Optional text of 10..1000 characters.** 0 and 9 are rejected, 10 and 1000 are
  accepted, 1001 is rejected. Whitespace is stripped before measuring, and the
  stripped value is what gets stored.
* **ONE review per session** (``uq_tutor_reviews_session_id``); a duplicate —
  including one whose predecessor was soft-deleted — is ``REVIEW_DUPLICATE``.
* **Editable for 7 days** (:data:`EDIT_WINDOW_DAYS`), recorded on the row as
  ``edit_deadline_at`` so the window is data, not a re-derived guess. The
  boundary is inclusive: exactly at the deadline is still editable.
* **User-deletable** at any time (soft delete), which immediately removes the
  review from the public aggregate.
* **Reviews are BLOCKED while attendance is absent or disputed**
  (:func:`assert_reviewable`): a review may only be written once the student has
  CONFIRMED the recorded attendance, or an admin has RESOLVED a dispute.
* **Public aggregates count PUBLISHED reviews only.** ``published`` is set by
  moderation, so an unmoderated or rejected review contributes nothing to
  ``tutor_profiles.rating_avg`` / ``rating_count``.
* **Written reviews require moderation before contributing publicly.** A
  rating-only review carries no free text to moderate, so it is auto-approved on
  creation (``review_moderation.state='approved'`` with no ``moderator_user_id``)
  and is published immediately; the moment free text is added — at creation or by
  a later edit — the review returns to ``pending`` and is unpublished until a
  moderator approves it. Both halves of the frozen decision therefore hold: the
  aggregate only ever counts published rows, and no free text is ever public
  before a human decision.

Privacy: review text is user content, not PII we manufacture, and it never
reaches an audit row, an outbox payload or a log line — only ids, the rating and
the length/moderation state do.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

import sqlalchemy as sa
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.wave2 import (
    ReviewModeration,
    SessionAttendance,
    TutorProfile,
    TutorReview,
)
from app.services.audit_service import record_audit_event
from app.services.tutoring import attendance as attendance_service
from app.services.tutoring import outbox_relay, sessions as sessions_service
from app.services.tutoring.errors import (
    Forbidden,
    NotFound,
    ReviewBlocked,
    ReviewDuplicate,
    ReviewEditWindowClosed,
    ReviewNotModeratable,
    ValidationError,
)
from app.services.tutoring.outbox_relay import OutboxIntent

#: Frozen edit window.
EDIT_WINDOW_DAYS = 7
MIN_RATING, MAX_RATING = 1, 5
MIN_BODY, MAX_BODY = 10, 1000
MODERATION_DECISIONS = ("approved", "rejected")

#: Sentinel so ``edit(body=None)`` (clear the text) differs from ``edit()``.
_UNSET = object()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def validate_rating(rating: object) -> int:
    """Integer 1..5. ``bool`` and ``float`` are NOT integers for this purpose."""
    if isinstance(rating, bool) or not isinstance(rating, int):
        raise ValidationError(
            "rating must be an integer between 1 and 5", field="rating"
        )
    if rating < MIN_RATING or rating > MAX_RATING:
        raise ValidationError(
            f"rating must be between {MIN_RATING} and {MAX_RATING}", field="rating"
        )
    return int(rating)


def validate_body(body: str | None) -> str | None:
    """Optional text; when present it must be 10..1000 characters after strip."""
    if body is None:
        return None
    if not isinstance(body, str):
        raise ValidationError("review text must be a string", field="body")
    text = body.strip()
    if len(text) < MIN_BODY or len(text) > MAX_BODY:
        raise ValidationError(
            f"review text must be {MIN_BODY}..{MAX_BODY} characters",
            field="body",
            length=len(text),
        )
    return text


# --------------------------------------------------------------------------- #
# Gating (matrix F2)
# --------------------------------------------------------------------------- #


def assert_reviewable(
    session: Session,
    session_id: uuid.UUID,
    *,
    author_user_id: uuid.UUID,
    now: datetime | None = None,
):
    """Raise unless this student may review this session; return the session.

    Blocked while attendance is ABSENT (no row, ``pending``, or merely
    ``recorded`` and not yet confirmed by the student) or DISPUTED. Cross-user
    isolation is inherited from ``sessions.get_session``, so another student's
    session is reported as ``NOT_FOUND`` rather than ``REVIEW_BLOCKED``.
    """
    now = now or utcnow()
    sess = sessions_service.get_session(
        session, session_id, user_id=author_user_id, role="student"
    )
    row = session.scalars(
        select(SessionAttendance).where(SessionAttendance.session_id == sess.id)
    ).first()
    if row is None:
        raise ReviewBlocked(
            "attendance has not been recorded for this session",
            session_id=str(sess.id),
            attendance_state=None,
        )
    if row.state not in attendance_service.REVIEWABLE_STATES:
        raise ReviewBlocked(
            "attendance is not confirmed",
            session_id=str(sess.id),
            attendance_state=row.state,
        )
    return sess


# --------------------------------------------------------------------------- #
# Aggregate maintenance
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PublicAggregate:
    """Public rating summary. PUBLISHED, non-deleted reviews only."""

    tutor_id: uuid.UUID
    rating_count: int
    rating_avg: Decimal | None
    distribution: dict[int, int]

    def as_dict(self) -> dict:
        return {
            "tutor_id": str(self.tutor_id),
            "rating_count": self.rating_count,
            "rating_avg": (str(self.rating_avg) if self.rating_avg is not None else None),
            "distribution": {str(k): v for k, v in sorted(self.distribution.items())},
        }


def _published_filter(tutor_id: uuid.UUID):
    return (
        TutorReview.tutor_id == tutor_id,
        TutorReview.published.is_(True),
        TutorReview.deleted_at.is_(None),
    )


def public_aggregate(session: Session, tutor_id: uuid.UUID) -> PublicAggregate:
    """Compute the public aggregate from PUBLISHED reviews only."""
    count, total = session.execute(
        select(
            func.count(TutorReview.id),
            func.coalesce(func.sum(TutorReview.rating), 0),
        ).where(*_published_filter(tutor_id))
    ).one()
    count = int(count or 0)
    distribution = {
        int(rating): int(n)
        for rating, n in session.execute(
            select(TutorReview.rating, func.count(TutorReview.id))
            .where(*_published_filter(tutor_id))
            .group_by(TutorReview.rating)
        ).all()
    }
    avg: Decimal | None = None
    if count:
        # Integer arithmetic then a single quantise: no float ever touches money
        # or ratings, and the value always fits Numeric(3,2).
        avg = (Decimal(int(total)) / Decimal(count)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    return PublicAggregate(
        tutor_id=tutor_id,
        rating_count=count,
        rating_avg=avg,
        distribution=distribution,
    )


def recompute_tutor_aggregate(
    session: Session, tutor_id: uuid.UUID, *, now: datetime | None = None
) -> PublicAggregate:
    """Refresh ``tutor_profiles.rating_avg`` / ``rating_count`` from published rows."""
    now = now or utcnow()
    aggregate = public_aggregate(session, tutor_id)
    session.execute(
        sa.update(TutorProfile)
        .where(TutorProfile.id == tutor_id)
        .values(
            rating_avg=aggregate.rating_avg,
            rating_count=aggregate.rating_count,
            updated_at=now,
        )
    )
    session.flush()
    return aggregate


def list_public_reviews(
    session: Session, tutor_id: uuid.UUID, *, limit: int = 20, offset: int = 0
) -> tuple[TutorReview, ...]:
    """Published, non-deleted reviews, newest first with a total order."""
    if limit <= 0 or limit > 100:
        raise ValidationError("limit must be between 1 and 100", field="limit")
    if offset < 0:
        raise ValidationError("offset must not be negative", field="offset")
    return tuple(
        session.scalars(
            select(TutorReview)
            .where(*_published_filter(tutor_id))
            .order_by(TutorReview.created_at.desc(), TutorReview.id.asc())
            .limit(limit)
            .offset(offset)
        ).all()
    )


# --------------------------------------------------------------------------- #
# Create / edit / delete (matrix F1)
# --------------------------------------------------------------------------- #


@dataclass
class ReviewMutation:
    """Result of a review mutation. ``intents`` dispatch AFTER the commit."""

    review: TutorReview
    moderation: ReviewModeration | None = None
    aggregate: PublicAggregate | None = None
    intents: list[OutboxIntent] = field(default_factory=list)


def _moderation_row(session: Session, review_id: uuid.UUID) -> ReviewModeration | None:
    return session.scalars(
        select(ReviewModeration).where(ReviewModeration.review_id == review_id)
    ).first()


def _publish_intent(
    session: Session, review: TutorReview, *, reason: str
) -> OutboxIntent:
    return outbox_relay.enqueue(
        session,
        kind="review_published",
        aggregate_id=review.id,
        payload={
            "review_id": str(review.id),
            "tutor_id": str(review.tutor_id),
            "session_id": str(review.session_id),
            "rating": int(review.rating),
            # The TEXT never leaves the row; only its length is observable.
            "has_text": review.body is not None,
            "text_length": len(review.body or ""),
            "reason": reason,
        },
    )


def create(
    session: Session,
    *,
    session_id: uuid.UUID,
    author_user_id: uuid.UUID,
    rating: object,
    body: str | None = None,
    now: datetime | None = None,
) -> ReviewMutation:
    """Write the one allowed review for a session. Does not commit."""
    now = now or utcnow()
    value = validate_rating(rating)
    text = validate_body(body)
    sess = assert_reviewable(session, session_id, author_user_id=author_user_id, now=now)

    existing = session.scalars(
        select(TutorReview).where(TutorReview.session_id == sess.id)
    ).first()
    if existing is not None:
        raise ReviewDuplicate(
            "this session already has a review", review_id=str(existing.id)
        )

    review = TutorReview(
        session_id=sess.id,
        tutor_id=sess.tutor_id,
        author_user_id=author_user_id,
        rating=value,
        body=text,
        # Free text must be moderated first; a rating-only review has nothing to
        # moderate and is published straight away (see the module docstring).
        published=text is None,
        edit_deadline_at=now + timedelta(days=EDIT_WINDOW_DAYS),
    )
    session.add(review)
    try:
        session.flush()
    except IntegrityError as exc:  # uq_tutor_reviews_session_id
        session.rollback()
        raise ReviewDuplicate(
            "this session already has a review", session_id=str(session_id)
        ) from exc

    moderation = ReviewModeration(
        review_id=review.id,
        state="approved" if text is None else "pending",
        moderator_user_id=None,
        decided_at=now if text is None else None,
        reason="auto_approved_rating_only" if text is None else None,
    )
    session.add(moderation)
    session.flush()

    intents: list[OutboxIntent] = []
    if review.published:
        intents.append(_publish_intent(session, review, reason="created"))
    aggregate = recompute_tutor_aggregate(session, sess.tutor_id, now=now)
    record_audit_event(
        session,
        action="tutoring.review.created",
        resource_type="tutor_review",
        resource_id=review.id,
        actor_user_id=author_user_id,
        actor_role="student",
        after_state={
            "session_id": str(sess.id),
            "tutor_id": str(sess.tutor_id),
            "rating": value,
            "has_text": text is not None,
            "text_length": len(text or ""),
            "published": bool(review.published),
            "moderation_state": moderation.state,
        },
    )
    session.flush()
    return ReviewMutation(
        review=review, moderation=moderation, aggregate=aggregate, intents=intents
    )


def get_review(
    session: Session,
    review_id: uuid.UUID,
    *,
    author_user_id: uuid.UUID | None = None,
    include_deleted: bool = False,
) -> TutorReview:
    """Fetch a review; owner-scoped reads are non-enumerating."""
    review = session.get(TutorReview, review_id)
    if review is None or (review.deleted_at is not None and not include_deleted):
        raise NotFound("review not found", resource="tutor_review")
    if author_user_id is not None and review.author_user_id != author_user_id:
        raise NotFound("review not found", resource="tutor_review")
    return review


def edit(
    session: Session,
    review_id: uuid.UUID,
    *,
    author_user_id: uuid.UUID,
    rating: object | None = None,
    body: object = _UNSET,
    now: datetime | None = None,
) -> ReviewMutation:
    """Edit the author's own review inside the 7-day window. Does not commit.

    Changing the free text sends the review BACK to moderation and unpublishes it
    until a moderator approves the new text.
    """
    now = now or utcnow()
    review = get_review(session, review_id, author_user_id=author_user_id)
    deadline = _aware(review.edit_deadline_at)
    if deadline is not None and now > deadline:
        raise ReviewEditWindowClosed(
            "the 7-day edit window has closed",
            review_id=str(review.id),
            edit_deadline_at=deadline.isoformat(),
        )
    values: dict = {"updated_at": now}
    if rating is not None:
        values["rating"] = validate_rating(rating)
    text_changed = False
    if body is not _UNSET:
        new_text = validate_body(body)  # type: ignore[arg-type]
        text_changed = new_text != review.body
        values["body"] = new_text
    if len(values) == 1:
        raise ValidationError("nothing to edit", field="body")

    moderation = _moderation_row(session, review.id)
    new_text_present = values.get("body", review.body) is not None
    if text_changed and new_text_present:
        # New free text -> unpublish and re-moderate.
        values["published"] = False
        if moderation is not None:
            session.execute(
                sa.update(ReviewModeration)
                .where(ReviewModeration.id == moderation.id)
                .values(
                    state="pending",
                    decided_at=None,
                    moderator_user_id=None,
                    reason="edited_pending_remoderation",
                    updated_at=now,
                )
            )
    elif text_changed and not new_text_present:
        # Text removed -> nothing left to moderate; a rating-only review may be
        # published immediately, exactly as at creation time.
        values["published"] = True
        if moderation is not None:
            session.execute(
                sa.update(ReviewModeration)
                .where(ReviewModeration.id == moderation.id)
                .values(
                    state="approved",
                    decided_at=now,
                    reason="auto_approved_rating_only",
                    updated_at=now,
                )
            )
    session.execute(
        sa.update(TutorReview).where(TutorReview.id == review.id).values(**values)
    )
    session.flush()
    session.refresh(review)
    moderation = _moderation_row(session, review.id)

    intents: list[OutboxIntent] = []
    if review.published and text_changed and not new_text_present:
        intents.append(_publish_intent(session, review, reason="edited"))
    aggregate = recompute_tutor_aggregate(session, review.tutor_id, now=now)
    record_audit_event(
        session,
        action="tutoring.review.edited",
        resource_type="tutor_review",
        resource_id=review.id,
        actor_user_id=author_user_id,
        actor_role="student",
        after_state={
            "rating": int(review.rating),
            "has_text": review.body is not None,
            "text_length": len(review.body or ""),
            "published": bool(review.published),
            "moderation_state": (moderation.state if moderation else None),
        },
    )
    session.flush()
    return ReviewMutation(
        review=review, moderation=moderation, aggregate=aggregate, intents=intents
    )


def delete(
    session: Session,
    review_id: uuid.UUID,
    *,
    author_user_id: uuid.UUID,
    now: datetime | None = None,
) -> ReviewMutation:
    """User-initiated soft delete. Drops out of the public aggregate at once."""
    now = now or utcnow()
    review = get_review(session, review_id, author_user_id=author_user_id)
    session.execute(
        sa.update(TutorReview)
        .where(TutorReview.id == review.id, TutorReview.deleted_at.is_(None))
        .values(deleted_at=now, published=False, updated_at=now)
    )
    session.flush()
    session.refresh(review)
    aggregate = recompute_tutor_aggregate(session, review.tutor_id, now=now)
    record_audit_event(
        session,
        action="tutoring.review.deleted",
        resource_type="tutor_review",
        resource_id=review.id,
        actor_user_id=author_user_id,
        actor_role="student",
        after_state={
            "deleted": True,
            "published": False,
            "tutor_rating_count": aggregate.rating_count,
        },
    )
    session.flush()
    return ReviewMutation(
        review=review,
        moderation=_moderation_row(session, review.id),
        aggregate=aggregate,
    )


# --------------------------------------------------------------------------- #
# Moderation (matrix F3)
# --------------------------------------------------------------------------- #


def moderate(
    session: Session,
    review_id: uuid.UUID,
    *,
    moderator_user_id: uuid.UUID,
    decision: str,
    actor_role: str = "admin",
    reason: str | None = None,
    now: datetime | None = None,
) -> ReviewMutation:
    """Approve or reject a pending review. ADMIN only. Does not commit.

    The decision is a single conditional ``UPDATE ... WHERE state='pending'``
    and its ``rowcount`` is CHECKED, so two moderators cannot both win: the
    loser gets ``REVIEW_NOT_MODERATABLE`` rather than publishing a review the
    other moderator rejected.
    """
    now = now or utcnow()
    if actor_role != "admin":
        raise Forbidden("only an admin may moderate reviews", actor_role=actor_role)
    if moderator_user_id is None:
        raise Forbidden("a moderation decision must name the moderator")
    if decision not in MODERATION_DECISIONS:
        raise ValidationError(
            f"unknown moderation decision: {decision}",
            field="decision",
            allowed=list(MODERATION_DECISIONS),
        )
    review = get_review(session, review_id)
    moderation = _moderation_row(session, review.id)
    if moderation is None:  # pragma: no cover - created alongside every review
        raise NotFound("moderation record not found", resource="review_moderation")
    if moderation.state != "pending":
        raise ReviewNotModeratable(
            "this review has already been moderated",
            review_id=str(review.id),
            state=moderation.state,
        )
    decided = session.execute(
        sa.update(ReviewModeration)
        .where(ReviewModeration.id == moderation.id, ReviewModeration.state == "pending")
        .values(
            state=decision,
            moderator_user_id=moderator_user_id,
            decided_at=now,
            # VARCHAR(200), operator-visible: codes only.
            reason=(reason[:200] if reason else None),
            updated_at=now,
        )
    )
    if (decided.rowcount or 0) != 1:
        # LOST the compare-and-swap: another moderator decided this review
        # between our read and our write (the read above can be stale for a
        # long-lived worker session). Falling through would set `published`
        # from OUR decision while the moderation record carries THEIRS — i.e. a
        # REJECTED review could become public and enter the aggregate. Refuse
        # instead of overwriting someone else's decision.
        raise ReviewNotModeratable(
            "this review has already been moderated",
            review_id=str(review.id),
            moderation_id=str(moderation.id),
        )
    session.execute(
        sa.update(TutorReview)
        .where(TutorReview.id == review.id)
        .values(published=(decision == "approved"), updated_at=now)
    )
    session.flush()
    session.refresh(review)
    session.refresh(moderation)

    intents: list[OutboxIntent] = []
    if decision == "approved":
        intents.append(_publish_intent(session, review, reason="moderated"))
    aggregate = recompute_tutor_aggregate(session, review.tutor_id, now=now)
    record_audit_event(
        session,
        action=f"tutoring.review.{decision}",
        resource_type="review_moderation",
        resource_id=moderation.id,
        actor_user_id=moderator_user_id,
        actor_role="admin",
        before_state={"state": "pending"},
        after_state={
            "state": decision,
            "review_id": str(review.id),
            "published": bool(review.published),
            "tutor_rating_count": aggregate.rating_count,
            "reason": reason,
        },
    )
    session.flush()
    return ReviewMutation(
        review=review, moderation=moderation, aggregate=aggregate, intents=intents
    )


def pending_moderation(
    session: Session, *, limit: int = 50
) -> tuple[ReviewModeration, ...]:
    """Moderation queue, oldest first with a total order."""
    if limit <= 0 or limit > 200:
        raise ValidationError("limit must be between 1 and 200", field="limit")
    return tuple(
        session.scalars(
            select(ReviewModeration)
            .where(ReviewModeration.state == "pending")
            .order_by(ReviewModeration.created_at.asc(), ReviewModeration.id.asc())
            .limit(limit)
        ).all()
    )
