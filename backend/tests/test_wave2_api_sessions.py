"""SAATHI-127 P3 HTTP-boundary matrix — sessions, attendance, video, reviews.

Frozen matrix rows D1-D5 (list/detail, reschedule, cancel+refund, completion,
attendance lifecycle), E1-E2 (join credentials, video webhook) and F1-F3 (review
create/edit/delete, attendance gating, moderation + public aggregate).

Every policy EDGE is landed exactly, not approximately: the clock is pinned
(``wave2_helpers.freeze_clock``) so "exactly 24 hours before start", "exactly the
scheduled end" and "exactly seven days after the review" are the instants
asserted, rather than a few seconds either side of them.
"""
from __future__ import annotations

import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select

import tests.wave2_helpers as W
from app.core import rate_limit
from app.core.config import settings
from app.models.registration import User
from app.models.wave2 import (
    PaymentOrder,
    PaymentRefund,
    ReviewModeration,
    SessionAttendance,
    SessionCancellation,
    SessionReminderJob,
    SessionStatusHistory,
    TutorAvailabilitySlot,
    TutoringSession,
    TutorProfile,
    TutorReview,
    VideoSessionGrant,
)
from app.services.providers.video_provider import DeterministicVideoAdapter, hash_token
from app.services.tutoring import join_credentials
from app.services.tutoring.errors import GrantRevoked

T0 = W.T0
AMOUNT = W.AMOUNT_PAISE
VIDEO_SIG = "X-Video-Signature"


# --------------------------------------------------------------------------- #
# Fixture + flow helpers
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def rig():
    """One schema/app/client for the whole file; each test still gets an EMPTY db."""
    rig = W.ApiRig()
    yield rig
    rig.close()


@pytest.fixture()
def ctx(monkeypatch, rig):
    context = rig.context(monkeypatch, now=T0)
    with context.SessionLocal() as s:
        # A SECOND tutor with a slot, so "you may not reschedule onto another
        # tutor's calendar" is testable rather than assumed.
        user = User(role="lawyer", status="active")
        s.add(user)
        s.flush()
        other = TutorProfile(
            user_id=user.id,
            display_name="Adv. Other Tutor",
            experience_years=4,
            verified_identity=True,
            verified_credentials=True,
            status="active",
        )
        s.add(other)
        s.flush()
        slot = TutorAvailabilitySlot(
            tutor_id=other.id,
            start_utc=T0 + timedelta(days=15, hours=1),
            end_utc=T0 + timedelta(days=15, hours=2),
            iana_timezone="Asia/Kolkata",
            status="available",
        )
        s.add(slot)
        s.commit()
        context.other_tutor_slot_id = slot.id
        context.other_tutor_id = other.id
    yield context
    rate_limit.reset()


def _booked(ctx, *, slot=None, student=None):
    """A CONFIRMED session created the only legal way: verified paid webhook."""
    with ctx.SessionLocal() as s:
        booked = W.book_session(
            s,
            ctx.world,
            slot_id=slot,
            student_user_id=student,
            now=ctx.clock.at,
        )
        return booked.tutoring_session.id, booked.order.id


def _tutor(ctx):
    return {"user": ctx.world.tutor_user_id, "roles": ("tutor",)}


def _admin(ctx):
    return {"user": ctx.world.admin_id, "roles": ("admin",)}


def _start_of(ctx, session_id):
    with ctx.fresh() as s:
        return W.sessions._aware(s.get(TutoringSession, session_id).start_utc)


def _end_of(ctx, session_id):
    with ctx.fresh() as s:
        return W.sessions._aware(s.get(TutoringSession, session_id).end_utc)


# --------------------------------------------------------------------------- #
# D1 — list / detail
# --------------------------------------------------------------------------- #


def test_video_capability_reports_the_runtime_switch_without_secrets(ctx, monkeypatch):
    monkeypatch.setattr(settings, "video_calls_enabled", False)
    monkeypatch.setattr(settings, "video_provider", "livekit")
    monkeypatch.setattr(settings, "livekit_public_url", "wss://video.example.test")
    monkeypatch.setattr(settings, "livekit_api_secret", "must-not-escape")
    disabled = ctx.client.get("/api/v1/tutoring/capabilities")
    assert disabled.status_code == 200
    assert disabled.json() == {
        "video_calls_enabled": False,
        "video_transport": "none",
        "video_room_url": None,
        "join_credential_ttl_seconds": settings.join_credential_ttl_seconds,
        "recording_enabled": False,
    }
    assert "must-not-escape" not in disabled.text

    monkeypatch.setattr(settings, "video_calls_enabled", True)
    enabled = ctx.client.get("/api/v1/tutoring/capabilities")
    assert enabled.status_code == 200
    assert enabled.json()["video_transport"] == "livekit"
    assert enabled.json()["video_room_url"] == "wss://video.example.test"
    assert "must-not-escape" not in enabled.text


def test_disabled_video_refuses_before_lookup_and_writes_nothing(ctx, monkeypatch):
    monkeypatch.setattr(settings, "video_calls_enabled", False)
    session_id, _order = _booked(ctx)
    with ctx.fresh() as s:
        before_grants = s.scalar(select(func.count()).select_from(VideoSessionGrant))
    refused = ctx.post(f"/api/v1/tutoring/sessions/{session_id}/join-credentials")
    assert refused.status_code == 503
    assert refused.json()["detail"] == {
        "code": "VIDEO_CALLS_DISABLED",
        "message": "video calls are currently unavailable",
        "retryable": False,
    }
    unknown = ctx.post(f"/api/v1/tutoring/sessions/{uuid.uuid4()}/join-credentials")
    assert unknown.status_code == 503 and unknown.json() == refused.json()
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(VideoSessionGrant)) == before_grants


def test_session_list_and_detail_are_scoped_to_the_caller(ctx):
    mine, _order = _booked(ctx)
    theirs, _o2 = _booked(
        ctx, slot=ctx.world.slots[1], student=ctx.world.other_student_id
    )
    student = ctx.get("/api/v1/tutoring/sessions")
    assert student.status_code == 200 and student.json()["role"] == "student"
    assert [i["id"] for i in student.json()["items"]] == [str(mine)]

    tutor = ctx.get("/api/v1/tutoring/sessions", **_tutor(ctx))
    assert tutor.json()["role"] == "tutor"
    assert {i["id"] for i in tutor.json()["items"]} == {str(mine), str(theirs)}

    admin = ctx.get("/api/v1/tutoring/sessions", **_admin(ctx))
    assert admin.json()["role"] == "admin" and len(admin.json()["items"]) == 2

    detail = ctx.get(f"/api/v1/tutoring/sessions/{mine}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "confirmed" and body["version"] == 1
    assert body["start_local"].endswith("+05:30")
    assert body["start_utc"].endswith("+00:00")
    assert body["attendance_state"] is None


def test_session_detail_cross_user_is_the_same_404_as_unknown(ctx):
    mine, _o = _booked(ctx)
    theirs = ctx.get(f"/api/v1/tutoring/sessions/{mine}", user=ctx.world.other_student_id)
    unknown = ctx.get(f"/api/v1/tutoring/sessions/{uuid.uuid4()}")
    assert theirs.status_code == unknown.status_code == 404
    assert theirs.json()["detail"] == unknown.json()["detail"]
    assert theirs.json()["detail"]["code"] == "NOT_FOUND"
    # a tutor who owns no profile for this session sees the same shape
    other_tutor_user = ctx.get(
        f"/api/v1/tutoring/sessions/{mine}",
        user=ctx.world.other_tutor_user_id,
        roles=("tutor",),
    )
    assert other_tutor_user.status_code == 404


def test_session_list_filters_and_bounds(ctx):
    mine, _o = _booked(ctx)
    ok = ctx.get("/api/v1/tutoring/sessions", params={"status": ["confirmed"]})
    assert ok.status_code == 200 and len(ok.json()["items"]) == 1
    none = ctx.get("/api/v1/tutoring/sessions", params={"status": ["cancelled"]})
    assert none.json()["items"] == []
    bad = ctx.get("/api/v1/tutoring/sessions", params={"status": ["nirvana"]})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "VALIDATION_ERROR"
    assert ctx.get("/api/v1/tutoring/sessions", params={"limit": 0}).status_code == 422
    assert ctx.get("/api/v1/tutoring/sessions", params={"limit": 201}).status_code == 422
    assert ctx.get("/api/v1/tutoring/sessions", params={"offset": -1}).status_code == 422
    window = ctx.get(
        "/api/v1/tutoring/sessions",
        params={"from_utc": (T0 + timedelta(days=30)).isoformat()},
    )
    assert window.json()["items"] == []


def test_session_reads_auth_and_role_gates(ctx):
    mine, _o = _booked(ctx)
    assert ctx.client.get("/api/v1/tutoring/sessions").status_code == 401
    assert ctx.client.get(f"/api/v1/tutoring/sessions/{mine}").status_code == 401
    for roles in (("moderator",), ("lawyer",)):
        assert ctx.get("/api/v1/tutoring/sessions", roles=roles).status_code == 403
        assert ctx.get(f"/api/v1/tutoring/sessions/{mine}", roles=roles).status_code == 403
    assert ctx.get("/api/v1/tutoring/sessions/not-a-uuid").status_code == 422


# --------------------------------------------------------------------------- #
# D2 — reschedule
# --------------------------------------------------------------------------- #


def _reschedule(ctx, session_id, slot_id, *, who=None, **body):
    who = who or {}
    return ctx.post(
        f"/api/v1/tutoring/sessions/{session_id}/reschedule",
        json={"new_slot_id": str(slot_id), **body},
        **who,
    )


def test_reschedule_outside_the_notice_window_is_free(ctx):
    session_id, _o = _booked(ctx)
    r = _reschedule(ctx, session_id, ctx.world.slots[1])
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rescheduled" and r.json()["version"] == 2
    assert r.json()["slot_id"] == str(ctx.world.slots[1])
    assert r.json()["reminders_revoked"] >= 1
    with ctx.fresh() as s:
        assert s.get(TutorAvailabilitySlot, ctx.world.slots[1]).status == "booked"
        assert s.get(TutorAvailabilitySlot, ctx.world.slots[0]).status == "available"
        assert s.scalar(
            select(func.count()).select_from(SessionReminderJob)
            .where(SessionReminderJob.status == "scheduled")
        ) >= 1


def test_reschedule_at_exactly_the_window_boundary_is_still_free(ctx):
    """``hours_before_start >= refund_free_cancel_hours`` is INCLUSIVE.

    Both sides of the edge are asserted: exactly 24h is free, and a minute
    inside it is refused. (The service quantises the hour count to two decimals
    for ``session_cancellations.hours_before_start`` — see
    ``test_the_notice_window_is_quantised_to_two_decimal_hours`` — so a minute is
    the smallest interval either side of the edge that is unambiguous.)
    """
    session_id, _o = _booked(ctx)
    start = _start_of(ctx, session_id)
    ctx.clock.set(start - timedelta(hours=settings.refund_free_cancel_hours))
    ok = _reschedule(ctx, session_id, ctx.world.slots[1])
    assert ok.status_code == 200, ok.text

    other, _o2 = _booked(ctx, slot=ctx.world.slots[2])
    start2 = _start_of(ctx, other)
    ctx.clock.set(
        start2 - timedelta(hours=settings.refund_free_cancel_hours) + timedelta(minutes=1)
    )
    refused = _reschedule(ctx, other, ctx.world.slots[3])
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "RESCHEDULE_WINDOW_CLOSED"
    assert refused.json()["detail"]["policy_window_hours"] == settings.refund_free_cancel_hours
    with ctx.fresh() as s:  # nothing moved
        assert s.get(TutoringSession, other).slot_id == ctx.world.slots[2]
        assert s.get(TutorAvailabilitySlot, ctx.world.slots[3]).status == "available"


def test_reschedule_inside_the_window_needs_an_authorised_admin(ctx):
    session_id, _o = _booked(ctx)
    ctx.clock.set(_start_of(ctx, session_id) - timedelta(hours=2))
    student_tries = _reschedule(
        ctx, session_id, ctx.world.slots[1], admin_exception=True
    )
    assert student_tries.status_code == 403
    assert student_tries.json()["detail"]["code"] == "ADMIN_EXCEPTION_UNAUTHORISED"
    granted = _reschedule(
        ctx, session_id, ctx.world.slots[1], who=_admin(ctx), admin_exception=True
    )
    assert granted.status_code == 200, granted.text
    with ctx.fresh() as s:
        assert W.audit_rows(s, "tutoring.session.reschedule_exception")


def test_reschedule_stale_version_is_typed_409(ctx):
    session_id, _o = _booked(ctx)
    r = _reschedule(ctx, session_id, ctx.world.slots[1], expected_version=99)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "SESSION_STALE_VERSION"
    with ctx.fresh() as s:
        assert s.get(TutoringSession, session_id).slot_id == ctx.world.slots[0]
        assert s.get(TutorAvailabilitySlot, ctx.world.slots[1]).status == "available"


def test_reschedule_slot_rules(ctx):
    session_id, _o = _booked(ctx)
    same = _reschedule(ctx, session_id, ctx.world.slots[0])
    assert same.status_code == 422 and same.json()["detail"]["field"] == "new_slot_id"
    unknown = _reschedule(ctx, session_id, uuid.uuid4())
    assert unknown.status_code == 404
    foreign = _reschedule(ctx, session_id, ctx.other_tutor_slot_id)
    assert foreign.status_code == 422
    assert foreign.json()["detail"]["code"] == "VALIDATION_ERROR"


def test_reschedule_cross_user_and_malformed_and_auth(ctx):
    session_id, _o = _booked(ctx)
    theirs = _reschedule(
        ctx, session_id, ctx.world.slots[1], who={"user": ctx.world.other_student_id}
    )
    unknown = _reschedule(ctx, uuid.uuid4(), ctx.world.slots[1])
    assert theirs.status_code == unknown.status_code == 404
    assert theirs.json()["detail"] == unknown.json()["detail"]
    extra = ctx.post(
        f"/api/v1/tutoring/sessions/{session_id}/reschedule",
        json={"new_slot_id": str(ctx.world.slots[1]), "sneaky": True},
    )
    assert extra.status_code == 422
    assert ctx.post(
        f"/api/v1/tutoring/sessions/{session_id}/reschedule", json={}
    ).status_code == 422
    assert ctx.post(
        f"/api/v1/tutoring/sessions/{session_id}/reschedule",
        json={"new_slot_id": "not-a-uuid"},
    ).status_code == 422
    assert ctx.client.post(
        f"/api/v1/tutoring/sessions/{session_id}/reschedule",
        json={"new_slot_id": str(ctx.world.slots[1])},
    ).status_code == 401
    assert _reschedule(
        ctx, session_id, ctx.world.slots[1], who={"roles": ("moderator",)}
    ).status_code == 403


def test_reschedule_a_cancelled_session_is_refused(ctx):
    session_id, _o = _booked(ctx)
    assert ctx.post(f"/api/v1/tutoring/sessions/{session_id}/cancel", json={}).status_code == 200
    r = _reschedule(ctx, session_id, ctx.world.slots[1])
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "SESSION_STATE_INVALID"


# --------------------------------------------------------------------------- #
# D3 — cancel + refund policy
# --------------------------------------------------------------------------- #


def _cancel(ctx, session_id, *, who=None, **body):
    return ctx.post(
        f"/api/v1/tutoring/sessions/{session_id}/cancel", json=body, **(who or {})
    )


def test_cancel_outside_the_window_refunds_in_full(ctx):
    session_id, order_id = _booked(ctx)
    r = _cancel(ctx, session_id)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "cancelled"
    assert body["refund"]["decision"] == "full_refund"
    assert body["refund"]["amount_paise"] == AMOUNT
    assert body["refund_id"]
    with ctx.fresh() as s:
        refund = s.scalar(select(PaymentRefund))
        assert refund.amount_paise == AMOUNT and refund.status == "succeeded"
        assert refund.reason == "cancel_ge_24h"
        assert s.get(TutorAvailabilitySlot, ctx.world.slots[0]).status == "cancelled"
        assert s.scalar(select(SessionCancellation)).audited is True
        assert {row.kind for row in W.outbox_rows(s)} >= {"booking_cancelled", "refund_issued"}


def test_cancel_at_exactly_the_window_boundary_still_refunds(ctx):
    session_id, _o = _booked(ctx)
    ctx.clock.set(
        _start_of(ctx, session_id) - timedelta(hours=settings.refund_free_cancel_hours)
    )
    r = _cancel(ctx, session_id)
    assert r.status_code == 200 and r.json()["refund"]["decision"] == "full_refund"


def test_cancel_one_minute_inside_the_window_earns_no_automatic_refund(ctx):
    session_id, _o = _booked(ctx)
    ctx.clock.set(
        _start_of(ctx, session_id)
        - timedelta(hours=settings.refund_free_cancel_hours)
        + timedelta(minutes=1)
    )
    r = _cancel(ctx, session_id)
    assert r.status_code == 200, r.text
    assert r.json()["refund"]["decision"] == "no_auto_refund"
    assert r.json()["refund"]["amount_paise"] == 0 and r.json()["refund_id"] is None
    assert r.json()["refund"]["hours_before_start"] == "23.98"
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(PaymentRefund)) == 0


def test_the_notice_window_is_quantised_to_two_decimal_hours(ctx):
    """A documented consequence, pinned so it cannot change silently.

    ``payments.hours_before`` quantises to 2dp because
    ``session_cancellations.hours_before_start`` is ``Numeric(8, 2)``. One second
    inside the 24h window therefore rounds to ``24.00`` and STILL earns the full
    refund: the effective edge is about 18 seconds wide, not instantaneous. That
    is a product-visible rounding rule, so it is asserted rather than left to be
    discovered by a student who cancelled ten seconds late.
    """
    session_id, _o = _booked(ctx)
    ctx.clock.set(
        _start_of(ctx, session_id)
        - timedelta(hours=settings.refund_free_cancel_hours)
        + timedelta(seconds=1)
    )
    r = _cancel(ctx, session_id)
    assert r.status_code == 200, r.text
    assert r.json()["refund"]["hours_before_start"] == "24.00"
    assert r.json()["refund"]["decision"] == "full_refund"


def test_tutor_cancellation_always_refunds_in_full(ctx):
    session_id, _o = _booked(ctx)
    ctx.clock.set(_start_of(ctx, session_id) - timedelta(minutes=30))
    r = _cancel(ctx, session_id, who=_tutor(ctx))
    assert r.status_code == 200, r.text
    assert r.json()["refund"]["decision"] == "full_refund"
    assert r.json()["refund"]["reason"] == "tutor_cancelled"


def test_admin_refund_exception_is_audited_and_role_gated(ctx):
    session_id, _o = _booked(ctx)
    ctx.clock.set(_start_of(ctx, session_id) - timedelta(minutes=30))
    student_tries = _cancel(ctx, session_id, admin_exception=True)
    assert student_tries.status_code == 403
    assert student_tries.json()["detail"]["code"] == "ADMIN_EXCEPTION_UNAUTHORISED"
    granted = _cancel(
        ctx,
        session_id,
        who=_admin(ctx),
        admin_exception=True,
        exception_amount_paise=100_000,
    )
    assert granted.status_code == 200, granted.text
    assert granted.json()["refund"]["decision"] == "admin_exception"
    assert granted.json()["refund"]["amount_paise"] == 100_000
    with ctx.fresh() as s:
        row = s.scalar(select(SessionCancellation))
        assert row.admin_actor_id == ctx.world.admin_id and row.audited is True
        assert W.audit_rows(s, "tutoring.session.cancel_exception")


def test_cancel_twice_is_refused_and_never_double_refunds(ctx):
    session_id, _o = _booked(ctx)
    assert _cancel(ctx, session_id).status_code == 200
    again = _cancel(ctx, session_id)
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "SESSION_STATE_INVALID"
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(PaymentRefund)) == 1


def test_cancel_cross_user_malformed_and_auth(ctx):
    session_id, _o = _booked(ctx)
    theirs = _cancel(ctx, session_id, who={"user": ctx.world.other_student_id})
    unknown = _cancel(ctx, uuid.uuid4())
    assert theirs.status_code == unknown.status_code == 404
    assert theirs.json()["detail"] == unknown.json()["detail"]
    assert ctx.post(
        f"/api/v1/tutoring/sessions/{session_id}/cancel", json={"nope": 1}
    ).status_code == 422
    assert ctx.post(
        f"/api/v1/tutoring/sessions/{session_id}/cancel",
        json={"expected_version": "one"},
    ).status_code == 422
    assert ctx.client.post(
        f"/api/v1/tutoring/sessions/{session_id}/cancel", json={}
    ).status_code == 401
    assert _cancel(ctx, session_id, who={"roles": ("moderator",)}).status_code == 403
    assert ctx.post("/api/v1/tutoring/sessions/nope/cancel", json={}).status_code == 422


# --------------------------------------------------------------------------- #
# D4 — completion after the scheduled end
# --------------------------------------------------------------------------- #


def test_early_completion_is_refused_and_records_nothing(ctx):
    session_id, _o = _booked(ctx)
    r = ctx.post(f"/api/v1/tutoring/sessions/{session_id}/complete", **_tutor(ctx))
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "ATTENDANCE_TOO_EARLY"
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(SessionAttendance)) == 0
        assert s.get(TutoringSession, session_id).status == "confirmed"
        assert not W.outbox_rows(s, kind="attendance_recorded")


def test_completion_at_exactly_the_scheduled_end_is_allowed(ctx):
    """The boundary is INCLUSIVE: end_utc itself counts as ended."""
    session_id, _o = _booked(ctx)
    ctx.clock.set(_end_of(ctx, session_id))
    r = ctx.post(f"/api/v1/tutoring/sessions/{session_id}/complete", **_tutor(ctx))
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "recorded" and r.json()["session_status"] == "completed"
    assert r.json()["recorded_by_role"] == "tutor"
    with ctx.fresh() as s:
        assert W.outbox_rows(s, kind="attendance_recorded")


def test_completion_one_microsecond_early_is_refused(ctx):
    session_id, _o = _booked(ctx)
    ctx.clock.set(_end_of(ctx, session_id) - timedelta(microseconds=1))
    r = ctx.post(f"/api/v1/tutoring/sessions/{session_id}/complete", **_tutor(ctx))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ATTENDANCE_TOO_EARLY"


def test_completion_role_and_ownership(ctx):
    session_id, _o = _booked(ctx)
    ctx.clock.set(_end_of(ctx, session_id) + timedelta(minutes=1))
    student = ctx.post(f"/api/v1/tutoring/sessions/{session_id}/complete")
    assert student.status_code == 403 and student.json()["detail"]["code"] == "FORBIDDEN"
    foreign = ctx.post(
        f"/api/v1/tutoring/sessions/{session_id}/complete",
        user=ctx.world.other_tutor_user_id,
        roles=("tutor",),
    )
    assert foreign.status_code == 404
    assert ctx.client.post(f"/api/v1/tutoring/sessions/{session_id}/complete").status_code == 401
    assert ctx.post(
        f"/api/v1/tutoring/sessions/{session_id}/complete", roles=("moderator",)
    ).status_code == 403
    assert ctx.post("/api/v1/tutoring/sessions/nope/complete", **_tutor(ctx)).status_code == 422
    admin = ctx.post(f"/api/v1/tutoring/sessions/{session_id}/complete", **_admin(ctx))
    assert admin.status_code == 200  # an admin may record on the tutor's behalf
    again = ctx.post(f"/api/v1/tutoring/sessions/{session_id}/complete", **_tutor(ctx))
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "ATTENDANCE_STATE_INVALID"


def test_student_completion_is_forbidden_and_mutates_absolutely_nothing(ctx):
    """Independent-QA defect D2: recording completion is never a student's call.

    The student surface no longer renders or dispatches this action at all; this
    pins the server half of the same rule. A direct unauthorised call is refused
    with the typed FORBIDDEN and leaves the attendance row, the session status,
    the outbox and the audit trail exactly as they were — and the legitimate
    recorder can still act afterwards, proving no state was consumed.
    """
    session_id, _o = _booked(ctx)
    ctx.clock.set(_end_of(ctx, session_id) + timedelta(minutes=1))
    refused = ctx.post(f"/api/v1/tutoring/sessions/{session_id}/complete")
    assert refused.status_code == 403
    detail = refused.json()["detail"]
    assert detail["code"] == "FORBIDDEN"
    # No enumeration: the refusal names the caller's own role and nothing about
    # the session, its student, its tutor or its price.
    body = json.dumps(detail)
    assert str(session_id) not in body
    assert str(ctx.world.tutor_user_id) not in body
    assert str(ctx.world.student_id) not in body

    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(SessionAttendance)) == 0
        assert s.get(TutoringSession, session_id).status == "confirmed"
        assert not W.outbox_rows(s, kind="attendance_recorded")
        assert not W.audit_rows(s, "tutoring.attendance.recorded")
        assert not s.scalars(
            select(SessionStatusHistory).where(
                SessionStatusHistory.session_id == session_id,
                SessionStatusHistory.to_status == "completed",
            )
        ).all()

    # The authorised actor is unaffected by the refused attempt.
    tutor = ctx.post(f"/api/v1/tutoring/sessions/{session_id}/complete", **_tutor(ctx))
    assert tutor.status_code == 200, tutor.text
    assert tutor.json()["state"] == "recorded"
    assert tutor.json()["recorded_by_role"] == "tutor"


def test_non_owning_tutor_completion_is_non_enumerating_and_mutates_nothing(ctx):
    """A tutor who does not own the session gets the unknown-session shape."""
    session_id, _o = _booked(ctx)
    ctx.clock.set(_end_of(ctx, session_id) + timedelta(minutes=1))
    foreign = ctx.post(
        f"/api/v1/tutoring/sessions/{session_id}/complete",
        user=ctx.world.other_tutor_user_id,
        roles=("tutor",),
    )
    unknown = ctx.post(
        f"/api/v1/tutoring/sessions/{uuid.uuid4()}/complete", **_tutor(ctx)
    )
    assert foreign.status_code == unknown.status_code == 404
    # Byte-identical: "not yours" and "does not exist" are ONE answer.
    assert foreign.json()["detail"] == unknown.json()["detail"]
    assert foreign.json()["detail"]["code"] == "NOT_FOUND"
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(SessionAttendance)) == 0
        assert s.get(TutoringSession, session_id).status == "confirmed"
        assert not W.outbox_rows(s, kind="attendance_recorded")
        assert not W.audit_rows(s, "tutoring.attendance.recorded")


def test_admin_may_record_completion_and_the_provenance_says_admin(ctx):
    """An admin records on a session they do not own; the row remembers who did."""
    session_id, _o = _booked(ctx)
    ctx.clock.set(_end_of(ctx, session_id) + timedelta(minutes=1))
    r = ctx.post(f"/api/v1/tutoring/sessions/{session_id}/complete", **_admin(ctx))
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "recorded"
    assert r.json()["recorded_by_role"] == "admin"
    assert r.json()["session_status"] == "completed"
    with ctx.fresh() as s:
        row = s.scalar(select(SessionAttendance))
        assert row.recorded_by_role == "admin"
        assert W.audit_rows(s, "tutoring.attendance.recorded")
        assert W.outbox_rows(s, kind="attendance_recorded")


# --------------------------------------------------------------------------- #
# D5 — attendance confirm / dispute / resolve
# --------------------------------------------------------------------------- #


def test_attendance_confirm_lifecycle(ctx):
    session_id, _o = _booked(ctx)
    ctx.clock.set(_end_of(ctx, session_id) + timedelta(minutes=1))
    ctx.post(f"/api/v1/tutoring/sessions/{session_id}/complete", **_tutor(ctx))
    r = ctx.post(f"/api/v1/tutoring/sessions/{session_id}/attendance/confirm", json={})
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "confirmed" and r.json()["version"] == 2
    assert r.json()["confirmed_at"].endswith("+00:00")


def test_attendance_confirm_before_a_recording_is_refused(ctx):
    session_id, _o = _booked(ctx)
    r = ctx.post(f"/api/v1/tutoring/sessions/{session_id}/attendance/confirm", json={})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "ATTENDANCE_STATE_INVALID"


def test_attendance_confirm_stale_version_is_typed(ctx):
    session_id, _o = _booked(ctx)
    ctx.clock.set(_end_of(ctx, session_id) + timedelta(minutes=1))
    ctx.post(f"/api/v1/tutoring/sessions/{session_id}/complete", **_tutor(ctx))
    r = ctx.post(
        f"/api/v1/tutoring/sessions/{session_id}/attendance/confirm",
        json={"expected_version": 99},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "ATTENDANCE_STALE_VERSION"
    with ctx.fresh() as s:
        assert s.scalar(select(SessionAttendance)).state == "recorded"


def test_attendance_dispute_then_admin_resolution(ctx):
    session_id, _o = _booked(ctx)
    ctx.clock.set(_end_of(ctx, session_id) + timedelta(minutes=1))
    ctx.post(f"/api/v1/tutoring/sessions/{session_id}/complete", **_tutor(ctx))
    disputed = ctx.post(
        f"/api/v1/tutoring/sessions/{session_id}/attendance/dispute",
        json={"reason_code": "tutor_absent"},
    )
    assert disputed.status_code == 200, disputed.text
    assert disputed.json()["state"] == "disputed"
    assert disputed.json()["session_status"] == "disputed"
    resolved = ctx.post(
        f"/api/v1/tutoring/sessions/{session_id}/attendance/resolve",
        json={"resolution": "no_show_tutor"},
        **_admin(ctx),
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["resolution"] == "no_show_tutor"
    assert resolved.json()["session_status"] == "completed"


def test_attendance_role_gates_and_validation(ctx):
    session_id, _o = _booked(ctx)
    ctx.clock.set(_end_of(ctx, session_id) + timedelta(minutes=1))
    ctx.post(f"/api/v1/tutoring/sessions/{session_id}/complete", **_tutor(ctx))
    base = f"/api/v1/tutoring/sessions/{session_id}/attendance"
    # confirm/dispute are the STUDENT's; resolve is the ADMIN's
    assert ctx.post(f"{base}/confirm", json={}, **_tutor(ctx)).status_code == 403
    assert ctx.post(f"{base}/dispute", json={}, **_tutor(ctx)).status_code == 403
    assert ctx.post(f"{base}/resolve", json={"resolution": "attended"}).status_code == 403
    assert ctx.client.post(f"{base}/confirm", json={}).status_code == 401
    assert ctx.client.post(f"{base}/resolve", json={"resolution": "attended"}).status_code == 401
    # cross-user confirm is non-enumerating
    theirs = ctx.post(f"{base}/confirm", json={}, user=ctx.world.other_student_id)
    assert theirs.status_code == 404 and theirs.json()["detail"]["code"] == "NOT_FOUND"
    # malformed / extra / narrative-shaped inputs
    assert ctx.post(f"{base}/confirm", json={"nope": 1}).status_code == 422
    assert ctx.post(f"{base}/dispute", json={"reason_code": "He never showed up!"}).status_code == 422
    assert ctx.post(f"{base}/resolve", json={"nope": 1}, **_admin(ctx)).status_code == 422
    bad = ctx.post(f"{base}/resolve", json={"resolution": "vibes"}, **_admin(ctx))
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "VALIDATION_ERROR"
    assert "attended" in bad.json()["detail"]["allowed"]
    assert ctx.post("/api/v1/tutoring/sessions/nope/attendance/confirm", json={}).status_code == 422
    # an illegal transition (confirm after resolve) is refused
    ctx.post(f"{base}/dispute", json={})
    ctx.post(f"{base}/resolve", json={"resolution": "attended"}, **_admin(ctx))
    assert ctx.post(f"{base}/confirm", json={}).status_code == 409


def test_attendance_resolve_on_an_unknown_session_is_404(ctx):
    r = ctx.post(
        f"/api/v1/tutoring/sessions/{uuid.uuid4()}/attendance/resolve",
        json={"resolution": "attended"},
        **_admin(ctx),
    )
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# E1 — join credentials
# --------------------------------------------------------------------------- #


def _issue(ctx, session_id, *, who=None):
    return ctx.post(
        f"/api/v1/tutoring/sessions/{session_id}/join-credentials", **(who or {})
    )


def test_join_credential_is_issued_to_the_paid_student_and_only_hashed(ctx):
    session_id, _o = _booked(ctx)
    r = _issue(ctx, session_id)
    assert r.status_code == 201, r.text
    body = r.json()
    token = body["join_token"]
    assert token.startswith("join_") and len(token) > 30
    assert body["permissions"] == "publish,subscribe"
    assert body["ttl_seconds"] == settings.join_credential_ttl_seconds
    assert body["expires_at"] == (
        ctx.clock.at + timedelta(seconds=settings.join_credential_ttl_seconds)
    ).isoformat()
    assert body["superseded"] == 0
    with ctx.fresh() as s:
        grant = s.scalar(select(VideoSessionGrant))
        assert grant.token_hash == hash_token(token)
        assert grant.token_hash != token and token not in grant.token_hash
        assert grant.revoked_at is None
        assert grant.participant_ref == body["participant_ref"]
        assert "@" not in grant.participant_ref
        # the audit trail records the grant WITHOUT the token or its hash
        blob = json.dumps([e.after_state for e in W.audit_rows(s, "tutoring.video.credential_issued")])
        assert token not in blob and grant.token_hash not in blob


def test_join_credential_permissions_differ_for_the_tutor(ctx):
    session_id, _o = _booked(ctx)
    r = _issue(ctx, session_id, who=_tutor(ctx))
    assert r.status_code == 201, r.text
    assert r.json()["permissions"] == "manage,publish,subscribe"


def test_join_credential_reissue_supersedes_and_defeats_replay(ctx):
    session_id, _o = _booked(ctx)
    first = _issue(ctx, session_id).json()
    second = _issue(ctx, session_id).json()
    assert second["superseded"] == 1
    assert second["join_token"] != first["join_token"]
    with ctx.fresh() as s:
        # The replayed (older) token now resolves to a REVOKED grant.
        with pytest.raises(GrantRevoked):
            join_credentials.validate(s, raw_token=first["join_token"], now=ctx.clock.at)
        live = join_credentials.validate(
            s, raw_token=second["join_token"], now=ctx.clock.at
        )
        assert live.revoked_at is None
        assert s.scalar(select(func.count()).select_from(VideoSessionGrant)) == 2


def test_join_credential_unauthorised_requests(ctx):
    session_id, _o = _booked(ctx)
    theirs = _issue(ctx, session_id, who={"user": ctx.world.other_student_id})
    unknown = _issue(ctx, uuid.uuid4())
    assert theirs.status_code == unknown.status_code == 404
    assert theirs.json()["detail"] == unknown.json()["detail"]
    foreign_tutor = _issue(
        ctx, session_id, who={"user": ctx.world.other_tutor_user_id, "roles": ("tutor",)}
    )
    assert foreign_tutor.status_code == 404
    admin = _issue(ctx, session_id, who=_admin(ctx))
    assert admin.status_code == 403 and admin.json()["detail"]["code"] == "FORBIDDEN"
    assert ctx.client.post(
        f"/api/v1/tutoring/sessions/{session_id}/join-credentials"
    ).status_code == 401
    assert _issue(ctx, session_id, who={"roles": ("moderator",)}).status_code == 403
    assert ctx.post("/api/v1/tutoring/sessions/nope/join-credentials").status_code == 422
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(VideoSessionGrant)) == 0


def test_join_credential_requires_a_captured_payment(ctx):
    session_id, order_id = _booked(ctx)
    with ctx.SessionLocal() as s:  # the capture is reversed out from under us
        s.get(PaymentOrder, order_id).status = "failed"
        s.commit()
    r = _issue(ctx, session_id)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "PAYMENT_UNVERIFIED"
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(VideoSessionGrant)) == 0


def test_join_credential_refused_for_a_cancelled_session(ctx):
    session_id, _o = _booked(ctx)
    assert _cancel(ctx, session_id).status_code == 200
    r = _issue(ctx, session_id)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SESSION_STATE_INVALID"


# --------------------------------------------------------------------------- #
# E2 — video webhook
# --------------------------------------------------------------------------- #


def _video_event(room_ref, *, event_type="participant_joined", participant_ref=None, event_id=None):
    return DeterministicVideoAdapter().make_event_body(
        room_ref=room_ref,
        event_type=event_type,
        participant_ref=participant_ref,
        event_id=event_id,
    )


def _video(ctx, raw, signature):
    return ctx.client.post(
        "/api/v1/video/webhook", content=raw, headers={VIDEO_SIG: signature}
    )


def test_video_webhook_records_a_verified_join_without_changing_status(ctx):
    session_id, _o = _booked(ctx)
    grant = _issue(ctx, session_id).json()
    raw, sig = _video_event(grant["room_ref"], participant_ref=grant["participant_ref"])
    r = _video(ctx, raw, sig)
    assert r.status_code == 200, r.text
    assert r.json()["session_id"] == str(session_id)
    assert r.json()["session_status"] == "confirmed"
    assert r.json()["grants_revoked"] == 0
    with ctx.fresh() as s:
        assert s.get(TutoringSession, session_id).status == "confirmed"
        trail = [
            row.reason
            for row in s.scalars(
                select(SessionStatusHistory).where(
                    SessionStatusHistory.session_id == session_id
                )
            ).all()
        ]
        assert any(str(reason).startswith("video:participant_joined:") for reason in trail)


def test_video_webhook_invalid_signature_writes_nothing(ctx):
    session_id, _o = _booked(ctx)
    grant = _issue(ctx, session_id).json()
    raw, _good = _video_event(grant["room_ref"], participant_ref=grant["participant_ref"])
    for signature in ("", "deadbeef", "0" * 64):
        r = _video(ctx, raw, signature)
        assert r.status_code == 400, signature
        assert r.json()["detail"]["code"] == "VIDEO_UNVERIFIED"
    with ctx.fresh() as s:
        assert not [
            row
            for row in s.scalars(select(SessionStatusHistory)).all()
            if str(row.reason or "").startswith("video:")
        ]


def test_video_webhook_malformed_and_unsupported_bodies(ctx):
    adapter = DeterministicVideoAdapter()
    raw = b"{definitely not json"
    r = _video(ctx, raw, adapter.sign(raw))
    assert r.status_code == 400 and r.json()["detail"]["code"] == "VIDEO_UNVERIFIED"
    assert "definitely not json" not in r.text
    body = json.dumps({"event_id": "e", "event_type": "sdp_exchange", "room_ref": "r"}).encode()
    r2 = _video(ctx, body, adapter.sign(body))
    assert r2.status_code == 400


def test_video_webhook_refuses_media_plane_payloads(ctx):
    """J1. SDP/ICE/device labels are rejected at the provider seam."""
    session_id, _o = _booked(ctx)
    grant = _issue(ctx, session_id).json()
    adapter = DeterministicVideoAdapter()
    for key, value in (
        ("sdp", "v=0\r\no=- 1 1 IN IP4 127.0.0.1"),
        ("ice_candidate", "candidate:1 1 udp 2130706431 10.0.0.1 54321 typ host"),
        ("device_label", "MacBook Pro Microphone"),
    ):
        payload = {
            "event_id": f"e-{key}",
            "event_type": "participant_joined",
            "room_ref": grant["room_ref"],
            "participant_ref": grant["participant_ref"],
            key: value,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        r = _video(ctx, raw, adapter.sign(raw))
        assert r.status_code == 400, (key, r.text)
        assert r.json()["detail"]["code"] == "VIDEO_UNVERIFIED"
        assert value not in r.text


def test_video_webhook_duplicate_event_is_refused_once_applied(ctx):
    session_id, _o = _booked(ctx)
    grant = _issue(ctx, session_id).json()
    raw, sig = _video_event(
        grant["room_ref"], participant_ref=grant["participant_ref"], event_id="vevt-1"
    )
    assert _video(ctx, raw, sig).status_code == 200
    again = _video(ctx, raw, sig)
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "DUPLICATE_EVENT"
    with ctx.fresh() as s:
        rows = [
            row
            for row in s.scalars(select(SessionStatusHistory)).all()
            if str(row.reason or "").endswith("vevt-1")
        ]
        assert len(rows) == 1


def test_video_webhook_unknown_room_is_404(ctx):
    raw, sig = _video_event("det_room_thisroomneverexisted")
    r = _video(ctx, raw, sig)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "NOT_FOUND"


def test_video_webhook_join_with_an_expired_credential_is_410(ctx):
    session_id, _o = _booked(ctx)
    settings_ttl = settings.join_credential_ttl_seconds
    try:
        object.__setattr__(settings, "join_credential_ttl_seconds", 60)
        grant = _issue(ctx, session_id).json()
    finally:
        object.__setattr__(settings, "join_credential_ttl_seconds", settings_ttl)
    ctx.clock.shift(seconds=61)  # the short TTL elapses before the room event
    raw, sig = _video_event(grant["room_ref"], participant_ref=grant["participant_ref"])
    r = _video(ctx, raw, sig)
    assert r.status_code == 410 and r.json()["detail"]["code"] == "GRANT_EXPIRED"


def test_video_webhook_room_finished_revokes_every_grant(ctx):
    session_id, _o = _booked(ctx)
    student_grant = _issue(ctx, session_id).json()
    tutor_grant = _issue(ctx, session_id, who=_tutor(ctx)).json()
    raw, sig = _video_event(student_grant["room_ref"], event_type="room_finished")
    r = _video(ctx, raw, sig)
    assert r.status_code == 200 and r.json()["grants_revoked"] == 2
    # a join announced afterwards is refused with the REVOKED reason
    raw2, sig2 = _video_event(
        student_grant["room_ref"], participant_ref=student_grant["participant_ref"]
    )
    late = _video(ctx, raw2, sig2)
    assert late.status_code == 410 and late.json()["detail"]["code"] == "GRANT_REVOKED"
    with ctx.fresh() as s:
        for token in (student_grant["join_token"], tutor_grant["join_token"]):
            with pytest.raises(GrantRevoked):
                join_credentials.validate(s, raw_token=token, now=ctx.clock.at)


def test_video_webhook_participant_left_revokes_only_that_participant(ctx):
    session_id, _o = _booked(ctx)
    student_grant = _issue(ctx, session_id).json()
    tutor_grant = _issue(ctx, session_id, who=_tutor(ctx)).json()
    raw, sig = _video_event(
        student_grant["room_ref"],
        event_type="participant_left",
        participant_ref=student_grant["participant_ref"],
    )
    r = _video(ctx, raw, sig)
    assert r.status_code == 200 and r.json()["grants_revoked"] == 1
    with ctx.fresh() as s:
        with pytest.raises(GrantRevoked):
            join_credentials.validate(
                s, raw_token=student_grant["join_token"], now=ctx.clock.at
            )
        assert join_credentials.validate(
            s, raw_token=tutor_grant["join_token"], now=ctx.clock.at
        )


def test_video_webhook_out_of_order_leave_before_join_is_safe(ctx):
    session_id, _o = _booked(ctx)
    grant = _issue(ctx, session_id).json()
    left, sig = _video_event(
        grant["room_ref"],
        event_type="participant_left",
        participant_ref=grant["participant_ref"],
        event_id="v-left",
    )
    assert _video(ctx, left, sig).status_code == 200
    joined, sig2 = _video_event(
        grant["room_ref"], participant_ref=grant["participant_ref"], event_id="v-join"
    )
    # the join is now stale: its grant was revoked by the leave that raced ahead
    late = _video(ctx, joined, sig2)
    assert late.status_code == 410 and late.json()["detail"]["code"] == "GRANT_REVOKED"
    with ctx.fresh() as s:
        assert s.get(TutoringSession, session_id).status == "confirmed"


def test_video_webhook_join_without_a_participant_or_grant(ctx):
    session_id, _o = _booked(ctx)
    grant = _issue(ctx, session_id).json()
    anon, sig = _video_event(grant["room_ref"], event_id="v-anon")
    assert _video(ctx, anon, sig).status_code == 400
    stranger, sig2 = _video_event(
        grant["room_ref"], participant_ref="deadbeef" * 4, event_id="v-stranger"
    )
    r = _video(ctx, stranger, sig2)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "NOT_FOUND"


def test_video_webhook_body_over_the_ceiling_is_413(ctx):
    adapter = DeterministicVideoAdapter()
    raw = b'{"event_type":"room_started","pad":"' + b"x" * (64 * 1024) + b'"}'
    r = _video(ctx, raw, adapter.sign(raw))
    assert r.status_code == 413


# --------------------------------------------------------------------------- #
# F1/F2 — review create / edit / delete and attendance gating
# --------------------------------------------------------------------------- #

BODY_10 = "a" * 10
BODY_1000 = "b" * 1000


def _review(ctx, session_id, *, who=None, **body):
    return ctx.post(
        f"/api/v1/tutoring/sessions/{session_id}/review", json=body, **(who or {})
    )


def _reviewable(ctx, *, slot=None, student=None):
    """A session with CONFIRMED attendance, established through the services.

    The D4/D5 routes are proven at the HTTP boundary by their own tests above;
    re-driving them over HTTP as a mere precondition for every F-row test would
    only re-measure the same two endpoints. ``wave2_helpers.complete_and_confirm``
    is the shared P2 helper for exactly this, and it goes through the real
    ``attendance`` service, so the state under test is not fabricated.
    """
    with ctx.SessionLocal() as s:
        booked = W.book_session(
            s, ctx.world, slot_id=slot, student_user_id=student, now=ctx.clock.at
        )
        after_end = W.complete_and_confirm(s, ctx.world, booked.tutoring_session)
    ctx.clock.set(after_end)
    return booked.tutoring_session.id


def test_review_rating_only_is_published_immediately(ctx):
    session_id = _reviewable(ctx)
    r = _review(ctx, session_id, rating=5)
    assert r.status_code == 201, r.text
    assert r.json()["published"] is True
    assert r.json()["moderation_state"] == "approved"
    assert r.json()["rating_aggregate"]["rating_count"] == 1


def test_review_with_text_waits_for_moderation(ctx):
    session_id = _reviewable(ctx)
    r = _review(ctx, session_id, rating=4, body=BODY_10)
    assert r.status_code == 201, r.text
    assert r.json()["published"] is False
    assert r.json()["moderation_state"] == "pending"
    # F3: an unmoderated review is invisible in the PUBLIC aggregate
    detail = ctx.get(f"/api/v1/tutors/{ctx.world.tutor_id}")
    assert detail.json()["rating_aggregate"]["rating_count"] == 0
    assert detail.json()["rating_aggregate"]["rating_avg"] is None


def test_review_rating_out_of_range_is_typed_422(ctx):
    session_id = _reviewable(ctx)
    for rating in (0, 6, -1, 100):
        r = _review(ctx, session_id, rating=rating)
        assert r.status_code == 422, rating
        assert r.json()["detail"]["code"] == "VALIDATION_ERROR"
        assert r.json()["detail"]["field"] == "rating"
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(TutorReview)) == 0


def test_review_non_integer_rating_is_rejected_at_the_boundary(ctx):
    session_id = _reviewable(ctx)
    for rating in (4.5, "5", True, None, [5]):
        r = _review(ctx, session_id, rating=rating)
        assert r.status_code == 422, rating
        assert r.json()["detail"]["code"] == "validation_error"
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(TutorReview)) == 0


def test_review_text_length_rejects_zero_nine_and_1001_characters(ctx):
    session_id = _reviewable(ctx)
    for body in ("", "c" * 9, "d" * 1001):
        r = _review(ctx, session_id, rating=3, body=body)
        assert r.status_code == 422, len(body)
        assert r.json()["detail"]["code"] == "VALIDATION_ERROR"
        assert r.json()["detail"]["field"] == "body"
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(TutorReview)) == 0


def test_review_text_accepts_exactly_ten_and_exactly_1000_characters(ctx):
    """The two inclusive edges, each on its OWN session (one review per session)."""
    for slot, body in ((ctx.world.slots[0], BODY_10), (ctx.world.slots[1], BODY_1000)):
        session_id = _reviewable(ctx, slot=slot)
        r = _review(ctx, session_id, rating=3, body=body)
        assert r.status_code == 201, (len(body), r.text)
        assert r.json()["body"] == body


def test_review_duplicate_per_session_is_refused(ctx):
    session_id = _reviewable(ctx)
    assert _review(ctx, session_id, rating=5).status_code == 201
    again = _review(ctx, session_id, rating=1)
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "REVIEW_DUPLICATE"
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(TutorReview)) == 1


def test_review_blocked_while_attendance_is_absent_or_disputed(ctx):
    absent, _o = _booked(ctx)
    r = _review(ctx, absent, rating=5)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "REVIEW_BLOCKED"
    assert r.json()["detail"]["attendance_state"] is None

    ctx.clock.set(_end_of(ctx, absent) + timedelta(minutes=1))
    ctx.post(f"/api/v1/tutoring/sessions/{absent}/complete", **_tutor(ctx))
    recorded = _review(ctx, absent, rating=5)
    assert recorded.status_code == 409
    assert recorded.json()["detail"]["attendance_state"] == "recorded"

    ctx.post(f"/api/v1/tutoring/sessions/{absent}/attendance/dispute", json={})
    disputed = _review(ctx, absent, rating=5)
    assert disputed.status_code == 409
    assert disputed.json()["detail"]["attendance_state"] == "disputed"
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(TutorReview)) == 0


def test_review_cross_user_malformed_and_auth(ctx):
    session_id = _reviewable(ctx)
    theirs = _review(ctx, session_id, who={"user": ctx.world.other_student_id}, rating=5)
    unknown = _review(ctx, uuid.uuid4(), rating=5)
    assert theirs.status_code == unknown.status_code == 404
    assert theirs.json()["detail"] == unknown.json()["detail"]
    assert _review(ctx, session_id, rating=5, sneaky=1).status_code == 422
    assert _review(ctx, session_id).status_code == 422
    assert ctx.client.post(
        f"/api/v1/tutoring/sessions/{session_id}/review", json={"rating": 5}
    ).status_code == 401
    assert _review(ctx, session_id, who=_tutor(ctx), rating=5).status_code == 403
    assert ctx.post(
        "/api/v1/tutoring/sessions/nope/review", json={"rating": 5}
    ).status_code == 422


def test_review_edit_inside_the_window_and_text_re_enters_moderation(ctx):
    session_id = _reviewable(ctx)
    review_id = _review(ctx, session_id, rating=5).json()["id"]
    bumped = ctx.patch(f"/api/v1/tutoring/reviews/{review_id}", json={"rating": 3})
    assert bumped.status_code == 200, bumped.text
    assert bumped.json()["rating"] == 3 and bumped.json()["published"] is True
    texted = ctx.patch(f"/api/v1/tutoring/reviews/{review_id}", json={"body": BODY_10})
    assert texted.status_code == 200
    assert texted.json()["published"] is False
    assert texted.json()["moderation_state"] == "pending"


def test_review_edit_after_seven_days_is_refused(ctx):
    session_id = _reviewable(ctx)
    created = _review(ctx, session_id, rating=5)
    review_id = created.json()["id"]
    ctx.clock.shift(days=7, seconds=1)
    r = ctx.patch(f"/api/v1/tutoring/reviews/{review_id}", json={"rating": 1})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "REVIEW_EDIT_WINDOW_CLOSED"
    with ctx.fresh() as s:
        assert s.scalar(select(TutorReview)).rating == 5


def test_review_edit_exactly_on_the_deadline_is_still_allowed(ctx):
    session_id = _reviewable(ctx)
    review_id = _review(ctx, session_id, rating=5).json()["id"]
    ctx.clock.shift(days=7)  # ``now > deadline`` is the refusal, not ``>=``
    assert ctx.patch(f"/api/v1/tutoring/reviews/{review_id}", json={"rating": 2}).status_code == 200


def test_review_edit_and_delete_are_author_only(ctx):
    session_id = _reviewable(ctx)
    review_id = _review(ctx, session_id, rating=5).json()["id"]
    other = {"user": ctx.world.other_student_id}
    theirs = ctx.patch(f"/api/v1/tutoring/reviews/{review_id}", json={"rating": 1}, **other)
    unknown = ctx.patch(f"/api/v1/tutoring/reviews/{uuid.uuid4()}", json={"rating": 1})
    assert theirs.status_code == unknown.status_code == 404
    assert theirs.json()["detail"] == unknown.json()["detail"]
    assert ctx.delete(f"/api/v1/tutoring/reviews/{review_id}", **other).status_code == 404
    assert ctx.patch(
        f"/api/v1/tutoring/reviews/{review_id}", json={"rating": 1, "extra": True}
    ).status_code == 422
    assert ctx.patch(f"/api/v1/tutoring/reviews/{review_id}", json={}).status_code == 422
    assert ctx.client.patch(
        f"/api/v1/tutoring/reviews/{review_id}", json={"rating": 1}
    ).status_code == 401
    assert ctx.client.delete(f"/api/v1/tutoring/reviews/{review_id}").status_code == 401
    assert ctx.delete(f"/api/v1/tutoring/reviews/{review_id}", roles=("admin",)).status_code == 403
    assert ctx.patch("/api/v1/tutoring/reviews/nope", json={"rating": 1}).status_code == 422


def test_review_delete_drops_out_of_the_public_aggregate_at_once(ctx):
    session_id = _reviewable(ctx)
    review_id = _review(ctx, session_id, rating=5).json()["id"]
    assert ctx.get(f"/api/v1/tutors/{ctx.world.tutor_id}").json()["rating_aggregate"][
        "rating_count"
    ] == 1
    r = ctx.delete(f"/api/v1/tutoring/reviews/{review_id}")
    assert r.status_code == 200 and r.json()["deleted"] is True
    assert r.json()["rating_aggregate"]["rating_count"] == 0
    assert ctx.get(f"/api/v1/tutors/{ctx.world.tutor_id}").json()["rating_aggregate"][
        "rating_count"
    ] == 0
    with ctx.fresh() as s:  # soft delete: the row survives for audit
        assert s.scalar(select(func.count()).select_from(TutorReview)) == 1


# --------------------------------------------------------------------------- #
# F3 — moderation + public aggregate
# --------------------------------------------------------------------------- #


def test_moderation_approval_publishes_and_enters_the_aggregate(ctx):
    session_id = _reviewable(ctx)
    review_id = _review(ctx, session_id, rating=5, body=BODY_10).json()["id"]
    assert ctx.get(f"/api/v1/tutors/{ctx.world.tutor_id}").json()["rating_aggregate"][
        "rating_count"
    ] == 0
    r = ctx.post(
        f"/api/v1/tutoring/reviews/{review_id}/moderate",
        json={"decision": "approved", "reason": "policy_ok"},
        **_admin(ctx),
    )
    assert r.status_code == 200, r.text
    assert r.json()["published"] is True and r.json()["moderation_state"] == "approved"
    aggregate = ctx.get(f"/api/v1/tutors/{ctx.world.tutor_id}").json()["rating_aggregate"]
    assert aggregate["rating_count"] == 1 and aggregate["rating_avg"] is not None
    with ctx.fresh() as s:
        assert W.outbox_rows(s, kind="review_published")


def test_moderation_rejection_keeps_it_out_of_the_aggregate(ctx):
    session_id = _reviewable(ctx)
    review_id = _review(ctx, session_id, rating=1, body=BODY_10).json()["id"]
    r = ctx.post(
        f"/api/v1/tutoring/reviews/{review_id}/moderate",
        json={"decision": "rejected"},
        **_admin(ctx),
    )
    assert r.status_code == 200 and r.json()["published"] is False
    assert ctx.get(f"/api/v1/tutors/{ctx.world.tutor_id}").json()["rating_aggregate"][
        "rating_count"
    ] == 0
    with ctx.fresh() as s:
        assert not W.outbox_rows(s, kind="review_published")
        assert s.scalar(select(ReviewModeration)).state == "rejected"


def test_moderation_is_role_gated_and_decided_once(ctx):
    session_id = _reviewable(ctx)
    review_id = _review(ctx, session_id, rating=5, body=BODY_10).json()["id"]
    path = f"/api/v1/tutoring/reviews/{review_id}/moderate"
    assert ctx.post(path, json={"decision": "approved"}).status_code == 403
    assert ctx.post(path, json={"decision": "approved"}, **_tutor(ctx)).status_code == 403
    assert ctx.post(path, json={"decision": "approved"}, roles=("moderator",)).status_code == 403
    assert ctx.client.post(path, json={"decision": "approved"}).status_code == 401
    with ctx.fresh() as s:
        assert s.scalar(select(ReviewModeration)).state == "pending"
    bad = ctx.post(path, json={"decision": "maybe"}, **_admin(ctx))
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "VALIDATION_ERROR"
    assert bad.json()["detail"]["allowed"] == ["approved", "rejected"]
    assert ctx.post(path, json={"decision": "approved", "nope": 1}, **_admin(ctx)).status_code == 422
    assert ctx.post(path, json={}, **_admin(ctx)).status_code == 422
    assert ctx.post(
        f"/api/v1/tutoring/reviews/{uuid.uuid4()}/moderate",
        json={"decision": "approved"},
        **_admin(ctx),
    ).status_code == 404
    assert ctx.post(
        "/api/v1/tutoring/reviews/nope/moderate", json={"decision": "approved"}, **_admin(ctx)
    ).status_code == 422
    assert ctx.post(path, json={"decision": "approved"}, **_admin(ctx)).status_code == 200
    again = ctx.post(path, json={"decision": "rejected"}, **_admin(ctx))
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "REVIEW_NOT_MODERATABLE"
    with ctx.fresh() as s:
        assert s.scalar(select(TutorReview)).published is True


def test_review_bodies_never_reach_audit_or_outbox_payloads(ctx):
    """J1. Free text stays in its column; only its LENGTH is observable."""
    session_id = _reviewable(ctx)
    secret = "The tutor mentioned my email raj@example.test during the call"
    review_id = _review(ctx, session_id, rating=2, body=secret).json()["id"]
    ctx.post(
        f"/api/v1/tutoring/reviews/{review_id}/moderate",
        json={"decision": "approved"},
        **_admin(ctx),
    )
    with ctx.fresh() as s:
        blob = json.dumps(
            [{"b": e.before_state, "a": e.after_state} for e in s.scalars(select(W.AuditEvent)).all()]
            + [row.payload_json for row in W.outbox_rows(s)]
        )
        assert secret not in blob and "raj@example.test" not in blob
        assert '"text_length": 61' in blob or '"text_length":61' in blob
