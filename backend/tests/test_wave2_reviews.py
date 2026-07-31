"""Wave 2 review, moderation and aggregate proofs (SAATHI-127 P2, matrix F1-F3).

Sessions under test are always produced by the REAL flow
(hold -> order -> VERIFIED paid webhook -> attendance recorded -> confirmed),
never inserted by hand, so the gating decision is exercised end to end.

Frozen decisions proved here
---------------------------
* rating is an INTEGER 1..5 — 0/6 and non-integers are refused, both sides of
  each boundary asserted;
* optional text is 10..1000 characters after stripping — 0/9 refused, 10/1000
  accepted, 1001 refused, ``None`` accepted;
* ONE review per session (service refusal AND the DB UNIQUE constraint), even
  after a soft delete;
* editable for 7 days, boundary INCLUSIVE, asserted from both sides; the author
  may delete it; another user may do neither, and cannot tell "not yours" from
  "does not exist";
* reviews are BLOCKED while attendance is absent, merely recorded, or disputed,
  and allowed once confirmed or admin-resolved;
* moderation approve publishes, reject does not, and the role is enforced;
* the public aggregate counts PUBLISHED (moderation-approved) rows only and
  recomputes after a delete;
* review free text never reaches an audit row, an outbox payload or a log line.
"""
from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.audit import AuditEvent
from app.models.wave2 import ReviewModeration, TutorProfile, TutorReview
from app.services.tutoring import attendance as attendance_service
from app.services.tutoring import errors, outbox_relay
from app.services.tutoring import reviews as reviews_service
from app.services.tutoring import sessions as sessions_service
from tests.wave2_helpers import (
    T0,
    audit_rows,
    book_session,
    build_world,
    complete_and_confirm,
    outbox_rows,
)

pytestmark = pytest.mark.usefixtures("db_session")

BODY_10 = "ten chars!"
BODY_9 = "nine char"
BODY_1000 = "a" * 1000
BODY_1001 = "a" * 1001


@pytest.fixture()
def world(db_session: Session):
    return build_world(db_session, now=T0)


def _reviewable(db_session, world, *, slot_index: int = 0):
    """A confirmed-attendance session ready to be reviewed, plus the instant."""
    booked = book_session(
        db_session, world, slot_id=world.slots[slot_index], now=T0
    )
    sess = booked.tutoring_session
    after_end = complete_and_confirm(db_session, world, sess)
    return sess, after_end


# --------------------------------------------------------------------------- #
# F1 — rating and text validation, both sides of every boundary
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("rating", [1, 2, 3, 4, 5])
def test_rating_inside_1_to_5_is_accepted(rating):
    assert reviews_service.validate_rating(rating) == rating


@pytest.mark.parametrize(
    "rating", [0, 6, -1, 100, True, False, 4.5, Decimal("4"), "4", None]
)
def test_rating_outside_1_to_5_or_non_integer_is_rejected(rating):
    with pytest.raises(errors.ValidationError) as bad:
        reviews_service.validate_rating(rating)
    assert bad.value.code == "VALIDATION_ERROR"
    assert bad.value.extra["field"] == "rating"


def test_rating_boundaries_end_to_end(db_session, world):
    sess, now = _reviewable(db_session, world)
    for bad in (0, 6, 4.5, True, "4"):
        with pytest.raises(errors.ValidationError):
            reviews_service.create(
                db_session,
                session_id=sess.id,
                author_user_id=world.student_id,
                rating=bad,
                now=now,
            )
        db_session.rollback()
    assert db_session.scalars(select(TutorReview)).all() == []

    created = reviews_service.create(
        db_session,
        session_id=sess.id,
        author_user_id=world.student_id,
        rating=1,
        now=now,
    )
    db_session.commit()
    assert created.review.rating == 1


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (None, None),
        (BODY_10, BODY_10),
        (BODY_1000, BODY_1000),
        ("   " + BODY_10 + "   ", BODY_10),  # stripped, and the strip is stored
    ],
    ids=["none", "exactly_10", "exactly_1000", "stripped"],
)
def test_text_lengths_inside_10_to_1000_are_accepted(body, expected):
    assert reviews_service.validate_body(body) == expected


@pytest.mark.parametrize(
    "body", ["", "   ", BODY_9, BODY_1001, "   " + BODY_9 + "   "],
    ids=["empty", "whitespace_only", "nine", "thousand_and_one", "nine_after_strip"],
)
def test_text_lengths_outside_10_to_1000_are_rejected(body):
    with pytest.raises(errors.ValidationError) as bad:
        reviews_service.validate_body(body)
    assert bad.value.extra["field"] == "body"
    assert bad.value.extra["length"] == len(body.strip())


def test_non_string_text_is_rejected():
    with pytest.raises(errors.ValidationError):
        reviews_service.validate_body(42)  # type: ignore[arg-type]


def test_text_boundaries_end_to_end(db_session, world):
    sess, now = _reviewable(db_session, world)
    for bad in ("", BODY_9, BODY_1001):
        with pytest.raises(errors.ValidationError):
            reviews_service.create(
                db_session,
                session_id=sess.id,
                author_user_id=world.student_id,
                rating=4,
                body=bad,
                now=now,
            )
        db_session.rollback()
    assert db_session.scalars(select(TutorReview)).all() == []

    created = reviews_service.create(
        db_session,
        session_id=sess.id,
        author_user_id=world.student_id,
        rating=4,
        body="  " + BODY_1000 + "  ",
        now=now,
    )
    db_session.commit()
    assert created.review.body == BODY_1000  # stripped value stored
    assert len(created.review.body) == 1000


def test_one_review_per_session(db_session, world):
    sess, now = _reviewable(db_session, world)
    first = reviews_service.create(
        db_session,
        session_id=sess.id,
        author_user_id=world.student_id,
        rating=5,
        now=now,
    )
    db_session.commit()

    # (a) the service refuses a second review...
    with pytest.raises(errors.ReviewDuplicate) as dup:
        reviews_service.create(
            db_session,
            session_id=sess.id,
            author_user_id=world.student_id,
            rating=3,
            now=now,
        )
    assert dup.value.code == "REVIEW_DUPLICATE"
    assert dup.value.extra["review_id"] == str(first.review.id)
    db_session.rollback()

    # (b) ...including after a soft delete (the frozen "one per session" rule is
    #     about the SESSION, not about the surviving row)...
    reviews_service.delete(
        db_session, first.review.id, author_user_id=world.student_id, now=now
    )
    db_session.commit()
    with pytest.raises(errors.ReviewDuplicate):
        reviews_service.create(
            db_session,
            session_id=sess.id,
            author_user_id=world.student_id,
            rating=3,
            now=now,
        )
    db_session.rollback()

    # (c) ...and the database refuses a second ROW outright.
    db_session.add(
        TutorReview(
            session_id=sess.id,
            tutor_id=sess.tutor_id,
            author_user_id=world.student_id,
            rating=2,
            edit_deadline_at=now,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
    assert len(db_session.scalars(select(TutorReview)).all()) == 1


def test_edit_window_boundary_is_inclusive_on_both_sides(db_session, world):
    sess, now = _reviewable(db_session, world)
    created = reviews_service.create(
        db_session,
        session_id=sess.id,
        author_user_id=world.student_id,
        rating=3,
        now=now,
    )
    db_session.commit()
    deadline = now + timedelta(days=reviews_service.EDIT_WINDOW_DAYS)
    assert reviews_service.EDIT_WINDOW_DAYS == 7
    assert reviews_service._aware(created.review.edit_deadline_at) == deadline

    # EXACTLY at the deadline: still editable.
    edited = reviews_service.edit(
        db_session,
        created.review.id,
        author_user_id=world.student_id,
        rating=5,
        now=deadline,
    )
    db_session.commit()
    assert edited.review.rating == 5

    # One second later: closed.
    with pytest.raises(errors.ReviewEditWindowClosed) as closed:
        reviews_service.edit(
            db_session,
            created.review.id,
            author_user_id=world.student_id,
            rating=2,
            now=deadline + timedelta(seconds=1),
        )
    assert closed.value.code == "REVIEW_EDIT_WINDOW_CLOSED"
    assert closed.value.extra["edit_deadline_at"] == deadline.isoformat()
    db_session.rollback()
    assert db_session.get(TutorReview, created.review.id).rating == 5

    # An edit that changes nothing is a validation error, not a silent no-op.
    with pytest.raises(errors.ValidationError):
        reviews_service.edit(
            db_session, created.review.id, author_user_id=world.student_id, now=now
        )
    db_session.rollback()


def test_author_can_delete_their_review(db_session, world):
    sess, now = _reviewable(db_session, world)
    created = reviews_service.create(
        db_session,
        session_id=sess.id,
        author_user_id=world.student_id,
        rating=5,
        now=now,
    )
    db_session.commit()
    assert reviews_service.public_aggregate(db_session, sess.tutor_id).rating_count == 1

    deleted = reviews_service.delete(
        db_session, created.review.id, author_user_id=world.student_id, now=now
    )
    db_session.commit()
    assert deleted.review.deleted_at is not None
    assert deleted.review.published is False
    assert deleted.aggregate.rating_count == 0
    assert deleted.aggregate.rating_avg is None
    # A soft-deleted review is invisible to owner reads and to the public list.
    with pytest.raises(errors.NotFound):
        reviews_service.get_review(
            db_session, created.review.id, author_user_id=world.student_id
        )
    assert reviews_service.list_public_reviews(db_session, sess.tutor_id) == ()
    assert audit_rows(db_session, "tutoring.review.deleted")[0].after_state[
        "deleted"
    ] is True


def test_cross_user_edit_and_delete_are_refused_without_enumeration(db_session, world):
    sess, now = _reviewable(db_session, world)
    created = reviews_service.create(
        db_session,
        session_id=sess.id,
        author_user_id=world.student_id,
        rating=5,
        now=now,
    )
    db_session.commit()

    with pytest.raises(errors.NotFound) as absent:
        reviews_service.get_review(
            db_session, uuid.uuid4(), author_user_id=world.other_student_id
        )
    for actor in (world.other_student_id, world.tutor_user_id, world.admin_id):
        with pytest.raises(errors.NotFound) as foreign_edit:
            reviews_service.edit(
                db_session,
                created.review.id,
                author_user_id=actor,
                rating=1,
                now=now,
            )
        assert foreign_edit.value.to_dict() == absent.value.to_dict()
        db_session.rollback()
        with pytest.raises(errors.NotFound) as foreign_delete:
            reviews_service.delete(
                db_session, created.review.id, author_user_id=actor, now=now
            )
        assert foreign_delete.value.to_dict() == absent.value.to_dict()
        db_session.rollback()

    row = db_session.get(TutorReview, created.review.id)
    assert (row.rating, row.deleted_at) == (5, None)


# --------------------------------------------------------------------------- #
# F2 — gating on attendance
# --------------------------------------------------------------------------- #


def test_review_is_blocked_until_attendance_is_confirmed_or_resolved(
    db_session, world
):
    booked = book_session(db_session, world, slot_id=world.slots[0], now=T0)
    sess = booked.tutoring_session
    after_end = sessions_service._aware(sess.end_utc) + timedelta(minutes=5)

    def attempt():
        return reviews_service.create(
            db_session,
            session_id=sess.id,
            author_user_id=world.student_id,
            rating=5,
            now=after_end,
        )

    # (1) attendance ABSENT.
    with pytest.raises(errors.ReviewBlocked) as absent:
        attempt()
    assert absent.value.code == "REVIEW_BLOCKED"
    assert absent.value.extra["attendance_state"] is None
    db_session.rollback()

    # (2) attendance merely RECORDED — the student has not confirmed yet.
    attendance_service.record(
        db_session, sess.id, actor_user_id=world.tutor_user_id,
        actor_role="tutor", now=after_end,
    )
    db_session.commit()
    with pytest.raises(errors.ReviewBlocked) as recorded:
        attempt()
    assert recorded.value.extra["attendance_state"] == "recorded"
    db_session.rollback()

    # (3) attendance DISPUTED.
    attendance_service.dispute(
        db_session, sess.id, actor_user_id=world.student_id, now=after_end
    )
    db_session.commit()
    with pytest.raises(errors.ReviewBlocked) as disputed:
        attempt()
    assert disputed.value.extra["attendance_state"] == "disputed"
    db_session.rollback()
    assert db_session.scalars(select(TutorReview)).all() == []

    # (4) an admin RESOLUTION unblocks it.
    attendance_service.resolve(
        db_session, sess.id, admin_user_id=world.admin_id,
        resolution="attended", now=after_end,
    )
    db_session.commit()
    created = attempt()
    db_session.commit()
    assert created.review.rating == 5

    # (5) and a plain CONFIRMED attendance unblocks a different session.
    other, other_now = _reviewable(db_session, world, slot_index=1)
    confirmed = reviews_service.create(
        db_session,
        session_id=other.id,
        author_user_id=world.student_id,
        rating=4,
        now=other_now,
    )
    db_session.commit()
    assert confirmed.review.session_id == other.id


def test_gating_reports_a_foreign_session_as_not_found_not_as_blocked(
    db_session, world
):
    sess, now = _reviewable(db_session, world)
    with pytest.raises(errors.NotFound) as absent:
        reviews_service.assert_reviewable(
            db_session, uuid.uuid4(), author_user_id=world.other_student_id, now=now
        )
    with pytest.raises(errors.NotFound) as foreign:
        reviews_service.create(
            db_session,
            session_id=sess.id,
            author_user_id=world.other_student_id,
            rating=5,
            now=now,
        )
    assert foreign.value.to_dict() == absent.value.to_dict()
    db_session.rollback()
    assert db_session.scalars(select(TutorReview)).all() == []


# --------------------------------------------------------------------------- #
# F3 — moderation and the public aggregate
# --------------------------------------------------------------------------- #


def test_rating_only_review_is_auto_approved_and_published(db_session, world):
    sess, now = _reviewable(db_session, world)
    created = reviews_service.create(
        db_session,
        session_id=sess.id,
        author_user_id=world.student_id,
        rating=5,
        now=now,
    )
    assert created.review.published is True
    assert created.moderation.state == "approved"
    assert created.moderation.moderator_user_id is None
    assert created.moderation.reason == "auto_approved_rating_only"
    assert [i.kind for i in created.intents] == ["review_published"]
    # The publish notification is written in the SAME transaction, still pending.
    assert ("review_published", "pending") in {
        (r.kind, r.status) for r in outbox_rows(db_session)
    }
    db_session.commit()
    assert reviews_service.pending_moderation(db_session) == ()


def test_written_review_needs_moderation_before_it_is_public(db_session, world):
    sess, now = _reviewable(db_session, world)
    created = reviews_service.create(
        db_session,
        session_id=sess.id,
        author_user_id=world.student_id,
        rating=5,
        body="A genuinely helpful constitutional law session.",
        now=now,
    )
    db_session.commit()
    assert created.review.published is False
    assert created.moderation.state == "pending"
    assert created.intents == []  # nothing to publish yet
    assert created.aggregate.rating_count == 0
    assert [m.review_id for m in reviews_service.pending_moderation(db_session)] == [
        created.review.id
    ]
    assert reviews_service.list_public_reviews(db_session, sess.tutor_id) == ()

    approved = reviews_service.moderate(
        db_session,
        created.review.id,
        moderator_user_id=world.admin_id,
        decision="approved",
        reason="policy_ok",
        now=now,
    )
    db_session.commit()
    assert approved.review.published is True
    assert approved.moderation.state == "approved"
    assert approved.moderation.moderator_user_id == world.admin_id
    assert approved.aggregate.rating_count == 1
    assert [i.kind for i in approved.intents] == ["review_published"]
    assert [r.id for r in reviews_service.list_public_reviews(db_session, sess.tutor_id)] == [
        created.review.id
    ]
    assert audit_rows(db_session, "tutoring.review.approved")[0].actor_role == "admin"
    # Already decided: it cannot be moderated twice.
    with pytest.raises(errors.ReviewNotModeratable) as again:
        reviews_service.moderate(
            db_session,
            created.review.id,
            moderator_user_id=world.admin_id,
            decision="rejected",
            now=now,
        )
    assert again.value.extra["state"] == "approved"
    db_session.rollback()


def test_rejected_review_is_never_published(db_session, world):
    sess, now = _reviewable(db_session, world)
    created = reviews_service.create(
        db_session,
        session_id=sess.id,
        author_user_id=world.student_id,
        rating=1,
        body="This text was rejected by a moderator.",
        now=now,
    )
    db_session.commit()
    rejected = reviews_service.moderate(
        db_session,
        created.review.id,
        moderator_user_id=world.admin_id,
        decision="rejected",
        reason="abusive_language",
        now=now,
    )
    db_session.commit()
    assert rejected.review.published is False
    assert rejected.moderation.state == "rejected"
    assert rejected.intents == []  # no publish notification for a rejection
    assert rejected.aggregate.rating_count == 0
    assert reviews_service.list_public_reviews(db_session, sess.tutor_id) == ()
    assert audit_rows(db_session, "tutoring.review.rejected")


def test_moderation_role_is_enforced(db_session, world):
    sess, now = _reviewable(db_session, world)
    created = reviews_service.create(
        db_session,
        session_id=sess.id,
        author_user_id=world.student_id,
        rating=5,
        body="Needs a human decision before it goes public.",
        now=now,
    )
    db_session.commit()

    for role in ("student", "tutor", "system", "moderator"):
        with pytest.raises(errors.Forbidden) as refused:
            reviews_service.moderate(
                db_session,
                created.review.id,
                moderator_user_id=world.admin_id,
                decision="approved",
                actor_role=role,
                now=now,
            )
        assert refused.value.extra["actor_role"] == role
        db_session.rollback()

    # A decision must name the moderator...
    with pytest.raises(errors.Forbidden):
        reviews_service.moderate(
            db_session,
            created.review.id,
            moderator_user_id=None,
            decision="approved",
            now=now,
        )
    db_session.rollback()
    # ...and be one of the two allowed decisions.
    with pytest.raises(errors.ValidationError) as bad:
        reviews_service.moderate(
            db_session,
            created.review.id,
            moderator_user_id=world.admin_id,
            decision="maybe",
            now=now,
        )
    assert bad.value.extra["allowed"] == list(reviews_service.MODERATION_DECISIONS)
    db_session.rollback()

    row = db_session.get(TutorReview, created.review.id)
    assert row.published is False
    assert reviews_service._moderation_row(db_session, row.id).state == "pending"


def test_a_lost_moderation_race_never_publishes_a_rejected_review(db_session, world):
    """Regression: the moderation compare-and-swap must be CHECKED.

    ``moderate`` reads the moderation row, then decides it with a conditional
    ``UPDATE ... WHERE state='pending'``. A long-lived worker session can hold a
    STALE read (simulated here with raw SQL, which performs no ORM
    synchronisation, exactly as a second connection would not). When the
    rowcount was discarded, the loser of the race still set ``published`` from
    its OWN decision — publishing a review the other moderator had REJECTED and
    letting it into the public aggregate.
    """
    sess, now = _reviewable(db_session, world)
    created = reviews_service.create(
        db_session,
        session_id=sess.id,
        author_user_id=world.student_id,
        rating=1,
        body="Text that a moderator is about to reject.",
        now=now,
    )
    db_session.commit()
    moderation_id = created.moderation.id

    # Another moderator rejects it first, invisibly to this session.
    db_session.execute(
        text(
            "UPDATE review_moderation SET state='rejected', decided_at=:at "
            "WHERE id=:id"
        ),
        {"at": now.isoformat(), "id": str(moderation_id).replace("-", "")},
    )
    db_session.commit()
    assert reviews_service._moderation_row(db_session, created.review.id).state == (
        "pending"
    )  # the stale read this session would act on

    with pytest.raises(errors.ReviewNotModeratable) as lost:
        reviews_service.moderate(
            db_session,
            created.review.id,
            moderator_user_id=world.admin_id,
            decision="approved",
            now=now,
        )
    assert lost.value.code == "REVIEW_NOT_MODERATABLE"
    db_session.rollback()

    assert db_session.execute(
        text("SELECT state FROM review_moderation")
    ).scalar() == "rejected"
    assert db_session.get(TutorReview, created.review.id).published is False
    assert reviews_service.public_aggregate(db_session, sess.tutor_id).rating_count == 0
    assert reviews_service.list_public_reviews(db_session, sess.tutor_id) == ()


def test_editing_the_text_returns_the_review_to_moderation(db_session, world):
    sess, now = _reviewable(db_session, world)
    created = reviews_service.create(
        db_session,
        session_id=sess.id,
        author_user_id=world.student_id,
        rating=5,
        now=now,
    )
    db_session.commit()
    assert created.review.published is True

    # Adding free text unpublishes and re-queues for moderation.
    with_text = reviews_service.edit(
        db_session,
        created.review.id,
        author_user_id=world.student_id,
        body="Adding a written note after the fact.",
        now=now,
    )
    db_session.commit()
    assert with_text.review.published is False
    assert with_text.moderation.state == "pending"
    assert with_text.moderation.reason == "edited_pending_remoderation"
    assert with_text.aggregate.rating_count == 0

    # Removing the text again leaves nothing to moderate: publishable at once.
    cleared = reviews_service.edit(
        db_session,
        created.review.id,
        author_user_id=world.student_id,
        body=None,
        now=now,
    )
    db_session.commit()
    assert cleared.review.body is None
    assert cleared.review.published is True
    assert cleared.moderation.state == "approved"
    assert cleared.aggregate.rating_count == 1
    assert [i.kind for i in cleared.intents] == ["review_published"]


def test_public_aggregate_counts_published_rows_only_and_recomputes(db_session):
    starts = tuple(T0 + timedelta(days=10 + index, hours=1) for index in range(5))
    world = build_world(db_session, now=T0, slot_starts=starts)
    created = []
    for index, (rating, body) in enumerate(
        [
            (5, None),
            (4, None),
            (4, None),
            (1, "Rejected written review, must never count."),
            (5, "Approved written review, counts once published."),
        ]
    ):
        sess, now = _reviewable(db_session, world, slot_index=index)
        created.append(
            (
                reviews_service.create(
                    db_session,
                    session_id=sess.id,
                    author_user_id=world.student_id,
                    rating=rating,
                    body=body,
                    now=now,
                ).review,
                now,
            )
        )
        db_session.commit()
    tutor_id = world.tutor_id

    # Only the three rating-only reviews are published so far.
    aggregate = reviews_service.public_aggregate(db_session, tutor_id)
    assert aggregate.rating_count == 3
    assert aggregate.rating_avg == Decimal("4.33")  # 13/3, ROUND_HALF_UP
    assert aggregate.distribution == {4: 2, 5: 1}
    assert aggregate.as_dict()["rating_avg"] == "4.33"

    # A rejected written review never contributes.
    reviews_service.moderate(
        db_session, created[3][0].id, moderator_user_id=world.admin_id,
        decision="rejected", now=created[3][1],
    )
    db_session.commit()
    assert reviews_service.public_aggregate(db_session, tutor_id).rating_count == 3

    # An approved written review does.
    reviews_service.moderate(
        db_session, created[4][0].id, moderator_user_id=world.admin_id,
        decision="approved", now=created[4][1],
    )
    db_session.commit()
    aggregate = reviews_service.public_aggregate(db_session, tutor_id)
    assert aggregate.rating_count == 4
    assert aggregate.rating_avg == Decimal("4.50")  # 18/4
    profile = db_session.get(TutorProfile, tutor_id)
    assert (profile.rating_count, profile.rating_avg) == (4, Decimal("4.50"))

    # Deleting the 5-star rating-only review recomputes the aggregate.
    reviews_service.delete(
        db_session, created[0][0].id, author_user_id=world.student_id,
        now=created[0][1],
    )
    db_session.commit()
    aggregate = reviews_service.public_aggregate(db_session, tutor_id)
    assert aggregate.rating_count == 3
    assert aggregate.rating_avg == Decimal("4.33")  # 13/3 again
    assert aggregate.distribution == {4: 2, 5: 1}
    profile = db_session.get(TutorProfile, tutor_id)
    assert (profile.rating_count, profile.rating_avg) == (3, Decimal("4.33"))
    assert len(reviews_service.list_public_reviews(db_session, tutor_id)) == 3


def test_public_and_queue_paging_are_validated(db_session, world):
    tutor_id = world.tutor_id
    for limit in (0, -1, 101):
        with pytest.raises(errors.ValidationError):
            reviews_service.list_public_reviews(db_session, tutor_id, limit=limit)
    with pytest.raises(errors.ValidationError):
        reviews_service.list_public_reviews(db_session, tutor_id, offset=-1)
    for limit in (0, -1, 201):
        with pytest.raises(errors.ValidationError):
            reviews_service.pending_moderation(db_session, limit=limit)


# --------------------------------------------------------------------------- #
# J1 — review free text is user content, and it stays in its own column
# --------------------------------------------------------------------------- #


def test_review_text_never_reaches_an_audit_row_outbox_payload_or_log(
    db_session, world, caplog
):
    caplog.set_level(logging.DEBUG)
    canary = "PRIVATE-NARRATIVE-CANARY the tutor said something confidential"
    sess, now = _reviewable(db_session, world)
    created = reviews_service.create(
        db_session,
        session_id=sess.id,
        author_user_id=world.student_id,
        rating=2,
        body=canary,
        now=now,
    )
    reviews_service.moderate(
        db_session,
        created.review.id,
        moderator_user_id=world.admin_id,
        decision="approved",
        now=now,
    )
    db_session.commit()
    dispatcher = outbox_relay.CapturingDispatcher()
    outbox_relay.relay_pending(db_session, dispatcher)

    # The text lives in exactly one place: tutor_reviews.body.
    assert db_session.get(TutorReview, created.review.id).body == canary
    for event in db_session.scalars(select(AuditEvent)).all():
        assert canary not in f"{event.before_state}{event.after_state}"
    for row in outbox_rows(db_session):
        assert canary not in repr(row.payload_json)
    published = [
        payload for kind, _agg, payload in dispatcher.delivered
        if kind == "review_published"
    ]
    assert published and all(canary not in repr(p) for p in published)
    # Only the shape of the text is observable.
    assert published[-1]["has_text"] is True
    assert published[-1]["text_length"] == len(canary)
    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert canary not in logs
    for row in db_session.scalars(select(ReviewModeration)).all():
        assert canary not in str(row.reason)
