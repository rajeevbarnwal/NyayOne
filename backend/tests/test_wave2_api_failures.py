"""SAATHI-123/127 P3 — abuse limits, provider outages, commit failure, race.

The four failure modes an HTTP boundary is allowed to have, each proven at the
boundary rather than reasoned about:

* **rate limits (A1/B1/F1)** — config-driven, per identity, hash-only buckets,
  refusing at the CONFIGURED threshold and before any write;
* **provider outages (C1/E1)** — a payment or video provider that is missing,
  broken or slow must surface as the typed ``PROVIDER_UNAVAILABLE`` (503), never
  as a leaked 500;
* **forced commit failure** — a real ``commit()`` failure produces the typed 500
  envelope with NO partial row, NO outbox side effect and no internal detail;
* **the 8-way booking-hold race (B1)** — exactly one winner, seven typed
  conflicts, and an identical replay of the winner's key returning the winner's
  result.
"""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import tests.wave2_helpers as W
from app.core import rate_limit
from app.core.config import settings
from app.core.rate_limit import BOOKING, REVIEW, TUTOR_SEARCH
from app.db.base import Base
from app.models.wave2 import (
    BookingEvent,
    BookingHold,
    PaymentEvent,
    PaymentOrder,
    ReviewModeration,
    TutorAvailabilitySlot,
    TutoringSession,
    TutorReview,
    VideoSessionGrant,
)
from app.services.providers.payment_provider import (
    TOKEN_SUCCESS,
    DeterministicPaymentAdapter,
    FailingPaymentAdapter,
)
from app.services.providers.video_provider import FailingVideoAdapter
from app.services.tutoring import join_credentials, payments as payments_service

T0 = W.T0
AMOUNT = W.AMOUNT_PAISE
PAY_SIG = "X-Payment-Signature"


@pytest.fixture(scope="module")
def rig():
    rig = W.ApiRig()
    yield rig
    rig.close()


@pytest.fixture()
def ctx(monkeypatch, rig):
    context = rig.context(monkeypatch, now=T0)
    yield context
    rate_limit.reset()


def _hold(ctx, *, key="k", slot=None, user=None):
    return ctx.post(
        "/api/v1/tutoring/booking-holds",
        user=user,
        json={"slot_id": str(slot or ctx.world.slot_id), "idempotency_key": key},
    )


# --------------------------------------------------------------------------- #
# Rate limits
# --------------------------------------------------------------------------- #


def test_the_frozen_default_thresholds_are_what_the_matrix_says(ctx):
    """60/min tutor search, 10/min booking + payment, 5/hour review mutations."""
    assert settings.rate_limit_tutor_search_per_min == 60
    assert settings.rate_limit_booking_per_min == 10
    assert settings.rate_limit_review_per_hour == 5
    assert (TUTOR_SEARCH.setting, TUTOR_SEARCH.window_seconds) == (
        "rate_limit_tutor_search_per_min",
        60,
    )
    assert (BOOKING.setting, BOOKING.window_seconds) == ("rate_limit_booking_per_min", 60)
    assert (REVIEW.setting, REVIEW.window_seconds) == ("rate_limit_review_per_hour", 3600)


def test_tutor_search_refuses_at_the_configured_threshold(ctx, monkeypatch):
    """The threshold is read from settings on EVERY call, so retuning it works."""
    monkeypatch.setattr(settings, "rate_limit_tutor_search_per_min", 3)
    rate_limit.reset()
    for attempt in range(3):
        assert ctx.get("/api/v1/tutors").status_code == 200, attempt
    refused = ctx.get("/api/v1/tutors")
    assert refused.status_code == 429
    detail = refused.json()["detail"]
    assert detail["code"] == "rate_limit_exceeded"
    assert detail["limit"] == 3 and detail["window_seconds"] == 60
    assert 1 <= detail["retry_after_seconds"] <= 60
    # a DIFFERENT identity has its own bucket
    assert ctx.get("/api/v1/tutors", user=ctx.world.other_student_id).status_code == 200


def test_the_discovery_limit_covers_detail_and_availability_too(ctx, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_tutor_search_per_min", 2)
    rate_limit.reset()
    assert ctx.get("/api/v1/tutors").status_code == 200
    assert ctx.get(f"/api/v1/tutors/{ctx.world.tutor_id}").status_code == 200
    over = ctx.get(f"/api/v1/tutors/{ctx.world.tutor_id}/availability")
    assert over.status_code == 429 and over.json()["detail"]["limit"] == 2


def test_booking_limit_refuses_before_any_write_happens(ctx, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_booking_per_min", 2)
    rate_limit.reset()
    assert _hold(ctx, key="a").status_code == 201
    assert _hold(ctx, key="a").status_code == 200  # a replay still costs budget
    refused = _hold(ctx, key="b", slot=ctx.world.slots[1])
    assert refused.status_code == 429
    with ctx.fresh() as s:  # the refused request wrote NOTHING
        assert s.scalar(select(func.count()).select_from(BookingHold)) == 1
        assert s.get(TutorAvailabilitySlot, ctx.world.slots[1]).status == "available"


def test_payment_mutations_share_the_booking_budget(ctx, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_booking_per_min", 1)
    rate_limit.reset()
    assert _hold(ctx, key="a").status_code == 201
    refused = ctx.post(
        "/api/v1/payments/orders",
        json={"hold_id": str(uuid.uuid4()), "amount_paise": AMOUNT, "idempotency_key": "o"},
    )
    assert refused.status_code == 429
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(PaymentOrder)) == 0


def test_review_mutations_use_the_hourly_budget(ctx, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_review_per_hour", 1)
    rate_limit.reset()
    # The first attempt is refused on its MERITS (no attendance) but still costs
    # budget: an abuser must not get unlimited free attempts by failing them.
    first = ctx.post(
        f"/api/v1/tutoring/sessions/{uuid.uuid4()}/review", json={"rating": 5}
    )
    assert first.status_code == 404
    second = ctx.post(
        f"/api/v1/tutoring/sessions/{uuid.uuid4()}/review", json={"rating": 5}
    )
    assert second.status_code == 429
    assert second.json()["detail"]["window_seconds"] == 3600


def test_moderation_is_deliberately_not_capped_by_the_review_budget(ctx, monkeypatch):
    """Five decisions an hour would be a broken moderation queue, not a limit."""
    monkeypatch.setattr(settings, "rate_limit_review_per_hour", 1)
    rate_limit.reset()
    for _ in range(3):
        r = ctx.post(
            f"/api/v1/tutoring/reviews/{uuid.uuid4()}/moderate",
            json={"decision": "approved"},
            user=ctx.world.admin_id,
            roles=("admin",),
        )
        assert r.status_code == 404  # refused on merits, never 429


def test_the_rate_limit_bucket_is_a_keyed_hash_of_the_identity(ctx):
    """J1. The limiter retains no user id, no IP and no request content."""
    identity = str(ctx.world.student_id)
    bucket = rate_limit.bucket_hash(BOOKING, identity)
    assert len(bucket) == 64 and identity not in bucket
    assert bucket != rate_limit.bucket_hash(REVIEW, identity)  # per-limit namespace
    assert bucket != rate_limit.bucket_hash(BOOKING, str(uuid.uuid4()))


def test_a_non_positive_configured_limit_fails_closed(ctx, monkeypatch):
    """A mis-set limit must not silently become "unlimited"."""
    monkeypatch.setattr(settings, "rate_limit_booking_per_min", 0)
    rate_limit.reset()
    with pytest.raises(ValueError):
        BOOKING.limit()


# --------------------------------------------------------------------------- #
# Provider outages
# --------------------------------------------------------------------------- #


def test_payment_provider_timeout_is_a_typed_503_not_a_500(ctx, monkeypatch):
    hold_id = _hold(ctx).json()["id"]
    monkeypatch.setattr(
        payments_service,
        "build_payment_provider",
        lambda: FailingPaymentAdapter(retryable=True, code="PROVIDER_TIMEOUT"),
    )
    r = ctx.post(
        "/api/v1/payments/orders",
        json={"hold_id": hold_id, "amount_paise": AMOUNT, "idempotency_key": "o"},
    )
    assert r.status_code == 503, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "PROVIDER_UNAVAILABLE"
    assert detail["provider_code"] == "PROVIDER_TIMEOUT"
    for leak in ("Traceback", "PaymentProviderError", "RuntimeError", "sqlalchemy"):
        assert leak not in r.text
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(PaymentOrder)) == 0
        assert s.get(TutorAvailabilitySlot, ctx.world.slot_id).status == "held"


def test_an_unconfigured_payment_provider_fails_closed(ctx, monkeypatch):
    hold_id = _hold(ctx).json()["id"]
    monkeypatch.setattr(payments_service, "build_payment_provider", lambda: None)
    r = ctx.post(
        "/api/v1/payments/orders",
        json={"hold_id": hold_id, "amount_paise": AMOUNT, "idempotency_key": "o"},
    )
    assert r.status_code == 503 and r.json()["detail"]["code"] == "PROVIDER_UNAVAILABLE"


def test_a_webhook_that_cannot_be_verified_by_a_sick_provider_is_503(ctx, monkeypatch):
    """A RETRYABLE verification failure is an outage, not a forged signature."""
    monkeypatch.setattr(
        payments_service,
        "build_payment_provider",
        lambda: FailingPaymentAdapter(retryable=True, code="PROVIDER_TIMEOUT"),
    )
    r = ctx.client.post(
        "/api/v1/payments/webhook", content=b"{}", headers={PAY_SIG: "whatever"}
    )
    assert r.status_code == 503 and r.json()["detail"]["code"] == "PROVIDER_UNAVAILABLE"
    # the envelope tells the provider whether redelivery can succeed
    assert r.json()["detail"]["retryable"] is True


def test_video_provider_outage_on_issue_is_a_typed_503(ctx, monkeypatch):
    with ctx.SessionLocal() as s:
        booked = W.book_session(s, ctx.world, now=ctx.clock.at)
        session_id = booked.tutoring_session.id
    monkeypatch.setattr(
        join_credentials,
        "build_video_provider",
        lambda: FailingVideoAdapter(retryable=True, code="PROVIDER_UNREACHABLE"),
    )
    r = ctx.post(f"/api/v1/tutoring/sessions/{session_id}/join-credentials")
    assert r.status_code == 503, r.text
    assert r.json()["detail"]["code"] == "PROVIDER_UNAVAILABLE"
    assert r.json()["detail"]["provider_code"] == "PROVIDER_UNREACHABLE"
    assert "VideoProviderError" not in r.text
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(VideoSessionGrant)) == 0


def test_an_unconfigured_video_provider_fails_closed(ctx, monkeypatch):
    with ctx.SessionLocal() as s:
        session_id = W.book_session(s, ctx.world, now=ctx.clock.at).tutoring_session.id
    monkeypatch.setattr(join_credentials, "build_video_provider", lambda: None)
    r = ctx.post(f"/api/v1/tutoring/sessions/{session_id}/join-credentials")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "PROVIDER_UNAVAILABLE"


def test_video_webhook_provider_outage_is_a_typed_503(ctx, monkeypatch):
    monkeypatch.setattr(
        join_credentials,
        "build_video_provider",
        lambda: FailingVideoAdapter(retryable=True, code="PROVIDER_UNREACHABLE"),
    )
    r = ctx.client.post(
        "/api/v1/video/webhook", content=b"{}", headers={"X-Video-Signature": "x"}
    )
    assert r.status_code == 503 and r.json()["detail"]["code"] == "PROVIDER_UNAVAILABLE"


# --------------------------------------------------------------------------- #
# Forced commit failure
# --------------------------------------------------------------------------- #


class _CommitFailOnce(Session):
    """A session whose ``commit()`` raises once while armed.

    A REAL commit failure (not a mocked service) is the only honest way to prove
    "no partial row and no outbox side effect": everything the request wrote has
    already been flushed when the failure lands.

    The flag is read and cleared through the CLASS NAME, never through
    ``type(self)``. SQLAlchemy 2.0's ``sessionmaker(class_=X)`` instantiates a
    dynamically generated SUBCLASS of ``X`` (so per-sessionmaker events can be
    attached), so ``type(self).arm = False`` would write to that subclass and
    permanently shadow the attribute a later test sets on ``X`` — the fault would
    fire exactly once per process and every subsequent arming would be silently
    ignored. Measured against
    ``test_commit_failure_on_the_paid_webhook_...``, which returned 200 instead
    of the expected 500 as soon as the rig became module-scoped.
    """

    arm = False

    def commit(self):  # type: ignore[override]
        if _CommitFailOnce.arm:
            _CommitFailOnce.arm = False
            raise RuntimeError("forced commit failure (injected)")
        return super().commit()


@pytest.fixture(scope="module")
def failing_rig():
    """A separate rig: this app must NOT re-raise, so the 500 handler is exercised."""
    rig = W.ApiRig(session_class=_CommitFailOnce, raise_server_exceptions=False)
    yield rig
    rig.close()


@pytest.fixture()
def failing(monkeypatch, failing_rig):
    _CommitFailOnce.arm = False
    context = failing_rig.context(monkeypatch, now=T0)
    yield context
    _CommitFailOnce.arm = False
    rate_limit.reset()


def _assert_typed_500(response) -> None:
    assert response.status_code == 500, response.text
    assert response.json()["detail"]["code"] == "internal_error"
    assert response.json()["detail"]["message"] == "An unexpected error occurred"
    for leak in ("RuntimeError", "forced commit failure", "Traceback", "sqlalchemy"):
        assert leak not in response.text


def test_commit_failure_on_a_booking_hold_leaves_nothing_behind(failing):
    ctx = failing
    _CommitFailOnce.arm = True
    r = _hold(ctx, key="boom")
    _assert_typed_500(r)
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(BookingHold)) == 0
        assert s.scalar(select(func.count()).select_from(BookingEvent)) == 0
        assert not W.audit_rows(s, "tutoring.hold.created")
        assert s.get(TutorAvailabilitySlot, ctx.world.slot_id).status == "available"
    retry = _hold(ctx, key="boom")  # the same request is safe to retry
    assert retry.status_code == 201, retry.text
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(BookingHold)) == 1
        assert len(W.audit_rows(s, "tutoring.hold.created")) == 1


def test_commit_failure_on_the_paid_webhook_books_nothing_and_dispatches_nothing(failing):
    ctx = failing
    hold = _hold(ctx, key="h").json()
    order = ctx.post(
        "/api/v1/payments/orders",
        json={"hold_id": hold["id"], "amount_paise": AMOUNT, "idempotency_key": "o"},
    ).json()
    adapter = DeterministicPaymentAdapter()
    raw, sig = adapter.make_event_body(
        provider_order_ref=order["provider_order_ref"],
        amount_paise=AMOUNT,
        token=TOKEN_SUCCESS,
        event_id="evt-commit-fail",
    )
    _CommitFailOnce.arm = True
    r = ctx.client.post("/api/v1/payments/webhook", content=raw, headers={PAY_SIG: sig})
    _assert_typed_500(r)
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(TutoringSession)) == 0
        assert s.scalar(select(func.count()).select_from(PaymentEvent)) == 0
        # THE point of the outbox: nothing can be dispatched for a rolled-back change
        assert W.outbox_rows(s) == []
        assert s.get(PaymentOrder, uuid.UUID(order["id"])).status == "created"
        assert s.get(TutorAvailabilitySlot, ctx.world.slot_id).status == "held"
    retry = ctx.client.post("/api/v1/payments/webhook", content=raw, headers={PAY_SIG: sig})
    assert retry.status_code == 200, retry.text
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(TutoringSession)) == 1
        assert len(W.outbox_rows(s, kind="payment_captured")) == 1


def test_commit_failure_on_a_review_leaves_no_row_and_no_outbox_row(failing):
    ctx = failing
    with ctx.SessionLocal() as s:
        booked = W.book_session(s, ctx.world, now=ctx.clock.at)
        session_id = booked.tutoring_session.id
    ctx.clock.set(
        W.sessions._aware(booked.tutoring_session.end_utc) + timedelta(minutes=5)
    )
    assert ctx.post(
        f"/api/v1/tutoring/sessions/{session_id}/complete",
        user=ctx.world.tutor_user_id,
        roles=("tutor",),
    ).status_code == 200
    assert ctx.post(
        f"/api/v1/tutoring/sessions/{session_id}/attendance/confirm", json={}
    ).status_code == 200
    before = None
    with ctx.fresh() as s:
        before = len(W.outbox_rows(s))
    _CommitFailOnce.arm = True
    r = ctx.post(f"/api/v1/tutoring/sessions/{session_id}/review", json={"rating": 5})
    _assert_typed_500(r)
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(TutorReview)) == 0
        assert s.scalar(select(func.count()).select_from(ReviewModeration)) == 0
        assert not W.audit_rows(s, "tutoring.review.created")
        assert len(W.outbox_rows(s)) == before
        assert not W.outbox_rows(s, kind="review_published")
    retry = ctx.post(f"/api/v1/tutoring/sessions/{session_id}/review", json={"rating": 5})
    assert retry.status_code == 201, retry.text


def test_commit_failure_on_a_join_credential_persists_no_grant(failing):
    ctx = failing
    with ctx.SessionLocal() as s:
        session_id = W.book_session(s, ctx.world, now=ctx.clock.at).tutoring_session.id
    _CommitFailOnce.arm = True
    r = ctx.post(f"/api/v1/tutoring/sessions/{session_id}/join-credentials")
    _assert_typed_500(r)
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(VideoSessionGrant)) == 0
        assert not W.audit_rows(s, "tutoring.video.credential_issued")


# --------------------------------------------------------------------------- #
# B1 — the 8-way booking-hold race, at the HTTP boundary
# --------------------------------------------------------------------------- #


def test_eight_concurrent_booking_holds_yield_exactly_one_winner(tmp_path, monkeypatch):
    """B1's frozen concurrency requirement, driven through the mounted app.

    Eight callers with DISTINCT idempotency keys race for one slot. The eight are
    released by a ``threading.Barrier`` (with a timeout, so a lost racer fails the
    test instead of hanging) so the overlap is guaranteed rather than dependent on
    thread scheduling, and the route table is resolved in the MAIN thread first —
    otherwise the race would partly measure FastAPI's lazy first-request route
    construction instead of the database boundary.

    The rate limit is raised for this test on purpose: the subject is the
    atomicity of the hold, and a 429 would be a different (already tested)
    refusal wearing the same clothes.
    """
    engine = W.serialized_file_engine(tmp_path, "wave2_hold_race")
    ctx = W.api_context(monkeypatch, now=T0, engine=engine)
    monkeypatch.setattr(settings, "rate_limit_booking_per_min", 100)
    rate_limit.reset()
    assert W.materialise_routes(ctx.app) > 0  # resolved ONCE, in this thread
    slot_id = str(ctx.world.slot_id)
    students = [ctx.world.student_id, ctx.world.other_student_id]
    gate = threading.Barrier(8, timeout=20)

    def _attempt(index: int):
        gate.wait()  # all eight enter the endpoint together
        return ctx.post(
            "/api/v1/tutoring/booking-holds",
            user=students[index % 2],
            json={"slot_id": slot_id, "idempotency_key": f"race-{index}"},
        )

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(_attempt, range(8)))
        codes = [r.status_code for r in results]
        assert codes.count(201) == 1, [(c, r.text[:160]) for c, r in zip(codes, results)]
        losers = [r for r in results if r.status_code != 201]
        assert len(losers) == 7
        assert all(r.status_code == 409 for r in losers), [r.status_code for r in losers]
        assert {r.json()["detail"]["code"] for r in losers} <= {
            "HOLD_CONFLICT",
            "SLOT_UNAVAILABLE",
        }
        winner_index = codes.index(201)
        winner = results[winner_index]
        with ctx.fresh() as s:  # exactly one row, exactly one audit event
            assert s.scalar(select(func.count()).select_from(BookingHold)) == 1
            assert s.get(TutorAvailabilitySlot, ctx.world.slot_id).status == "held"
            assert len(W.audit_rows(s, "tutoring.hold.created")) == 1
            assert len(
                [row for row in s.scalars(select(BookingEvent)).all() if row.kind == "hold_created"]
            ) == 1
        replay = ctx.post(
            "/api/v1/tutoring/booking-holds",
            user=students[winner_index % 2],
            json={"slot_id": slot_id, "idempotency_key": f"race-{winner_index}"},
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["id"] == winner.json()["id"]
        assert replay.json()["replayed"] is True
        with ctx.fresh() as s:
            assert s.scalar(select(func.count()).select_from(BookingHold)) == 1
    finally:
        rate_limit.reset()
        Base.metadata.drop_all(engine)


# --------------------------------------------------------------------------- #
# J1 — exhaustive persistence scan
# --------------------------------------------------------------------------- #

#: Values a Wave 2 request may plausibly carry that must NEVER be persisted.
CANARY_PAN = "4111111111111111"
CANARY_CVV = "321"
CANARY_OTP = "998877"
CANARY_SDP = "v=0 o=- 1 1 IN IP4 127.0.0.1"


def _every_stored_value(session) -> str:
    """Every column of every table, stringified. No table is exempt."""
    chunks: list[str] = []
    for table in Base.metadata.sorted_tables:
        for row in session.execute(select(table)).all():
            chunks.append("|".join("" if v is None else str(v) for v in row))
    return "\n".join(chunks)


def test_no_canary_and_no_raw_join_token_ever_reaches_storage(ctx):
    """J1. A full happy path, then an exhaustive scan of the whole database."""
    hold = _hold(ctx, key="j1").json()
    order = ctx.post(
        "/api/v1/payments/orders",
        json={
            "hold_id": hold["id"],
            "amount_paise": AMOUNT,
            "idempotency_key": "o-j1",
            "payment_token": TOKEN_SUCCESS,
        },
    ).json()
    adapter = DeterministicPaymentAdapter()
    raw, sig = adapter.make_event_body(
        provider_order_ref=order["provider_order_ref"], amount_paise=AMOUNT
    )
    paid = ctx.client.post("/api/v1/payments/webhook", content=raw, headers={PAY_SIG: sig})
    assert paid.status_code == 200, paid.text
    session_id = paid.json()["session_id"]

    credential = ctx.post(f"/api/v1/tutoring/sessions/{session_id}/join-credentials")
    assert credential.status_code == 201, credential.text
    token = credential.json()["join_token"]

    # requests that MUST be refused, and must leave no trace either
    for bad in (
        {"pan": CANARY_PAN},
        {"cvv": CANARY_CVV},
        {"otp": CANARY_OTP},
        {"payment_token": CANARY_PAN},
    ):
        assert ctx.post(
            "/api/v1/payments/orders",
            json={
                "hold_id": hold["id"],
                "amount_paise": AMOUNT,
                "idempotency_key": "o-bad",
                **bad,
            },
        ).status_code == 422

    with ctx.fresh() as s:
        stored = _every_stored_value(s)
    # Only canaries LONG enough to be unambiguous are substring-scanned. A
    # 3-digit CVV cannot be told apart from three digits of a uuid or a
    # microsecond field, so scanning for it would generate false positives
    # instead of evidence; those short values are proven absent by being
    # REFUSED above (nothing was written to look for) and by the forbidden-key
    # scan below.
    for canary in (token, CANARY_PAN, CANARY_SDP, TOKEN_SUCCESS):
        assert canary not in stored, canary
    # the HASH is what is stored, and it is not the token
    with ctx.fresh() as s:
        grant = s.scalar(select(VideoSessionGrant))
        assert grant is not None and grant.token_hash in stored
    # no forbidden KEY name leaked into any JSON payload column either
    lowered = stored.lower()
    for key in ("\"pan\"", "\"cvv\"", "\"otp\"", "\"sdp\"", "\"ice_candidate\"",
                "\"device_label\"", "\"raw_token\"", "\"join_token\"", "\"access_token\""):
        assert key not in lowered, key


def test_outbox_payloads_carry_ids_codes_and_counts_only(ctx):
    """G1/J1. Anything an outbox row could dispatch is already privacy-safe."""
    from app.services.tutoring import outbox_relay

    hold = _hold(ctx, key="ob").json()
    order = ctx.post(
        "/api/v1/payments/orders",
        json={"hold_id": hold["id"], "amount_paise": AMOUNT, "idempotency_key": "o-ob"},
    ).json()
    adapter = DeterministicPaymentAdapter()
    raw, sig = adapter.make_event_body(
        provider_order_ref=order["provider_order_ref"], amount_paise=AMOUNT
    )
    assert ctx.client.post(
        "/api/v1/payments/webhook", content=raw, headers={PAY_SIG: sig}
    ).status_code == 200
    with ctx.fresh() as s:
        rows = W.outbox_rows(s)
        assert rows
        for row in rows:
            # the SAME guard the services enqueue through, re-run on stored rows
            outbox_relay.assert_payload_safe(row.payload_json, where="stored outbox row")
            assert row.status in ("pending", "sent")
