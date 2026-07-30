"""SAATHI-123 P3 HTTP-boundary matrix — discovery, holds, payments, creation.

Frozen matrix rows A1-A3 (tutor search / detail / availability), B1-B2 (booking
holds), C1-C3 (payment order / verified webhook / session creation). Rows D-F are
in ``test_wave2_api_sessions.py``; rate limits, provider outages, the forced
commit failure and the 8-way race are in ``test_wave2_api_failures.py``.

Everything runs through the MOUNTED app (``api_router`` under ``/api/v1``) with a
production-style session dependency and the production exception handlers, so a
route that forgot to roll back, or that leaked an untyped 500, fails here.

Time is pinned with ``wave2_helpers.freeze_clock`` rather than approximated: the
routes take no ``now`` parameter (that would be a production-visible test hook),
so pinning each service's ``utcnow`` is what lets a boundary assertion land
exactly on a hold TTL edge instead of a few seconds either side of it.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import tests.wave2_helpers as W
from app.core import rate_limit
from app.db.models.audit import AuditEvent
from app.models.registration import User
from app.models.wave2 import (
    BookingEvent,
    BookingHold,
    PaymentEvent,
    PaymentOrder,
    TutorAvailabilitySlot,
    TutoringOutbox,
    TutoringSession,
    TutorProfile,
    TutorSubject,
)
from app.services.providers.payment_provider import (
    TOKEN_DECLINED,
    TOKEN_PENDING,
    TOKEN_SUCCESS,
    DeterministicPaymentAdapter,
)
from app.services.tutoring import payments as payments_service

T0 = W.T0
AMOUNT = W.AMOUNT_PAISE
PAY_SIG = "X-Payment-Signature"


# --------------------------------------------------------------------------- #
# Fixture
# --------------------------------------------------------------------------- #


def _seed_catalogue(session: Session, world) -> list[uuid.UUID]:
    """Subjects + provenance for the built tutor, plus tutors to discriminate on.

    ``build_world`` deliberately builds ONE tutor; search/sort/pagination need
    more than one row and a hidden (``draft``) row to prove invisibility.
    """
    tutor = session.get(TutorProfile, world.tutor_id)
    tutor.source = "verified_registry"
    tutor.source_url = "https://example.test/bci/registry"
    tutor.retrieved_at = T0 - timedelta(days=3)
    tutor.rating_avg = Decimal("4.80")
    tutor.rating_count = 12
    for subject, level in (
        ("Constitutional Law", "undergraduate"),
        ("Moot Court", "postgraduate"),
    ):
        session.add(TutorSubject(tutor_id=tutor.id, subject=subject, level=level))
    extra: list[uuid.UUID] = []
    for name, years, rating, count, verified, status in (
        ("Adv. Rohit Sharma", 3, Decimal("4.50"), 8, False, "active"),
        ("Adv. Kavya Nair", 20, Decimal("3.00"), 2, True, "active"),
        ("Adv. Draft Only", 5, None, 0, True, "draft"),
    ):
        user = User(role="lawyer", status="active")
        session.add(user)
        session.flush()
        row = TutorProfile(
            user_id=user.id,
            display_name=name,
            headline="Taxation and GST litigation",
            experience_years=years,
            rating_avg=rating,
            rating_count=count,
            verified_identity=verified,
            verified_credentials=verified,
            status=status,
        )
        session.add(row)
        session.flush()
        session.add(
            TutorSubject(tutor_id=row.id, subject="Tax Law", level="undergraduate")
        )
        extra.append(row.id)
    session.commit()
    return extra


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
        context.extra_tutors = _seed_catalogue(s, context.world)
    yield context
    rate_limit.reset()


# --------------------------------------------------------------------------- #
# Wiring: every P3 route is reachable through the MOUNTED app
# --------------------------------------------------------------------------- #

EXPECTED_ROUTES = {
    ("GET", "/api/v1/tutors"),
    ("GET", "/api/v1/tutors/{tutor_id}"),
    ("GET", "/api/v1/tutors/{tutor_id}/availability"),
    ("POST", "/api/v1/tutoring/booking-holds"),
    ("GET", "/api/v1/tutoring/booking-holds/{hold_id}"),
    ("POST", "/api/v1/payments/orders"),
    ("POST", "/api/v1/payments/webhook"),
    ("POST", "/api/v1/tutoring/sessions"),
    ("GET", "/api/v1/tutoring/sessions"),
    ("GET", "/api/v1/tutoring/sessions/{session_id}"),
    ("POST", "/api/v1/tutoring/sessions/{session_id}/reschedule"),
    ("POST", "/api/v1/tutoring/sessions/{session_id}/cancel"),
    ("POST", "/api/v1/tutoring/sessions/{session_id}/complete"),
    ("POST", "/api/v1/tutoring/sessions/{session_id}/attendance/confirm"),
    ("POST", "/api/v1/tutoring/sessions/{session_id}/attendance/dispute"),
    ("POST", "/api/v1/tutoring/sessions/{session_id}/attendance/resolve"),
    ("POST", "/api/v1/tutoring/sessions/{session_id}/join-credentials"),
    ("POST", "/api/v1/video/webhook"),
    ("POST", "/api/v1/tutoring/sessions/{session_id}/review"),
    ("PATCH", "/api/v1/tutoring/reviews/{review_id}"),
    ("DELETE", "/api/v1/tutoring/reviews/{review_id}"),
    ("POST", "/api/v1/tutoring/reviews/{review_id}/moderate"),
}


def test_every_wave2_route_is_reachable_through_the_mounted_app(ctx):
    """Asserted against the app's RESOLVED route table, not the router module.

    Importing ``app.api.v1.tutoring`` and looking at ``router.routes`` would pass
    even if ``api_router`` never included it; this reads what the deployed app
    would actually serve.
    """
    resolved = W.route_table(ctx.app)
    assert len(resolved) > len(EXPECTED_ROUTES)  # the pre-existing surface is intact
    missing = EXPECTED_ROUTES - resolved
    assert not missing, f"unmounted routes: {sorted(missing)}"
    # the Wave 1 surface this app also serves must still be mounted
    assert ("GET", "/api/v1/law-schools") in resolved


# --------------------------------------------------------------------------- #
# A1 — tutor search
# --------------------------------------------------------------------------- #


def test_tutor_search_filters_sort_and_pagination(ctx):
    r = ctx.get("/api/v1/tutors", params={"sort": "experience_desc", "limit": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3 and len(body["items"]) == 2 and body["has_more"] is True
    assert [i["experience_years"] for i in body["items"]] == [20, 11]
    # draft tutors are not discoverable at all
    assert "Adv. Draft Only" not in [i["display_name"] for i in body["items"]]
    page2 = ctx.get("/api/v1/tutors", params={"sort": "experience_desc", "limit": 2, "offset": 2})
    assert page2.json()["has_more"] is False and len(page2.json()["items"]) == 1

    subj = ctx.get("/api/v1/tutors", params={"subject": "constitutional law"})
    assert [i["id"] for i in subj.json()["items"]] == [str(ctx.world.tutor_id)]
    lvl = ctx.get("/api/v1/tutors", params={"subject": "Moot Court", "level": "postgraduate"})
    assert lvl.json()["total"] == 1
    vr = ctx.get("/api/v1/tutors", params={"verified_only": True})
    assert all(i["verified_identity"] and i["verified_credentials"] for i in vr.json()["items"])
    assert ctx.get("/api/v1/tutors", params={"min_rating": 4.6}).json()["total"] == 1
    assert ctx.get("/api/v1/tutors", params={"min_experience_years": 12}).json()["total"] == 1
    assert ctx.get("/api/v1/tutors", params={"q": "taxation"}).json()["total"] == 2


def test_tutor_search_empty_filters_are_ignored_not_matched(ctx):
    """An empty filter must mean "no filter", never "match the empty string"."""
    r = ctx.get("/api/v1/tutors", params={"q": "", "subject": "", "level": ""})
    assert r.status_code == 200 and r.json()["total"] == 3


def test_tutor_search_no_match_is_an_empty_page_not_an_error(ctx):
    r = ctx.get("/api/v1/tutors", params={"q": "zzz-no-such-tutor"})
    assert r.status_code == 200 and r.json()["items"] == [] and r.json()["total"] == 0


# Looped rather than parametrised: every case shares one fixture and one
# precondition, so a parametrised version would rebuild the world seven times to
# make the same seven assertions.
UNSUPPORTED_SEARCH_VALUES = [
    {"sort": "hackable"},
    {"limit": 0},
    {"limit": 101},
    {"offset": -1},
    {"min_rating": 5.5},
    {"min_rating": -1},
    {"min_experience_years": -1},
]
OVER_LENGTH_SEARCH_FILTERS = [
    {"q": "x" * 121},
    {"subject": "y" * 81},
    {"level": "z" * 41},
    {"sort": "s" * 33},
]


def test_tutor_search_unsupported_values_are_typed_422(ctx):
    for params in UNSUPPORTED_SEARCH_VALUES:
        r = ctx.get("/api/v1/tutors", params=params)
        assert r.status_code == 422, (params, r.text)
        assert r.json()["detail"]["code"] in ("VALIDATION_ERROR", "validation_error")


def test_tutor_search_over_length_filters_rejected_before_any_sql(ctx):
    for params in OVER_LENGTH_SEARCH_FILTERS:
        r = ctx.get("/api/v1/tutors", params=params)
        assert r.status_code == 422, params
        assert r.json()["detail"]["code"] == "validation_error"


def test_tutor_search_unauthenticated_and_wrong_role(ctx):
    assert ctx.client.get("/api/v1/tutors").status_code == 401
    assert ctx.client.get("/api/v1/tutors").json()["detail"]["code"] == "authentication_required"
    r = ctx.get("/api/v1/tutors", roles=("lawyer",))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "forbidden"


# --------------------------------------------------------------------------- #
# A2 — tutor detail
# --------------------------------------------------------------------------- #


def test_tutor_detail_carries_verified_claims_provenance_and_aggregate(ctx):
    r = ctx.get(f"/api/v1/tutors/{ctx.world.tutor_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verified_identity"] is True and body["verified_credentials"] is True
    assert body["source"] == "verified_registry"
    assert body["source_url"] and body["retrieved_at"]
    assert sorted(s["subject"] for s in body["subjects"]) == ["Constitutional Law", "Moot Court"]
    # F3: the PUBLIC aggregate is computed from published reviews only, so a
    # freshly seeded tutor reports zero regardless of the profile's cached avg.
    assert body["rating_aggregate"]["rating_count"] == 0
    assert body["rating_aggregate"]["rating_avg"] is None


def test_tutor_detail_unknown_and_hidden_ids_are_the_same_404(ctx):
    unknown = ctx.get(f"/api/v1/tutors/{uuid.uuid4()}")
    draft = ctx.get(f"/api/v1/tutors/{ctx.extra_tutors[-1]}")
    assert unknown.status_code == draft.status_code == 404
    assert unknown.json()["detail"] == draft.json()["detail"] | {
        k: v for k, v in unknown.json()["detail"].items() if k not in draft.json()["detail"]
    }
    assert unknown.json()["detail"]["code"] == "NOT_FOUND"


def test_tutor_detail_invalid_path_param_type_422(ctx):
    r = ctx.get("/api/v1/tutors/not-a-uuid")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "validation_error"


def test_tutor_detail_unauthenticated_and_wrong_role(ctx):
    path = f"/api/v1/tutors/{ctx.world.tutor_id}"
    assert ctx.client.get(path).status_code == 401
    assert ctx.get(path, roles=("admin",)).status_code == 403


# --------------------------------------------------------------------------- #
# A3 — availability + timezone + DST
# --------------------------------------------------------------------------- #


def test_availability_returns_slots_with_utc_and_local_projections(ctx):
    r = ctx.get(f"/api/v1/tutors/{ctx.world.tutor_id}/availability")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["iana_timezone"] == "Asia/Kolkata"
    assert len(body["slots"]) == len(ctx.world.slots)
    starts = [s["start_utc"] for s in body["slots"]]
    assert starts == sorted(starts)  # deterministic order
    first = body["slots"][0]
    assert first["duration_minutes"] == 60 and first["status"] == "available"
    assert first["start_local"].endswith("+05:30")


def test_availability_display_timezone_reprojects_the_same_instants(ctx):
    base = ctx.get(f"/api/v1/tutors/{ctx.world.tutor_id}/availability").json()
    other = ctx.get(
        f"/api/v1/tutors/{ctx.world.tutor_id}/availability",
        params={"timezone": "Europe/London"},
    ).json()
    assert [s["start_utc"] for s in base["slots"]] == [s["start_utc"] for s in other["slots"]]
    assert other["slots"][0]["iana_timezone"] == "Europe/London"
    assert other["slots"][0]["start_local"] != base["slots"][0]["start_local"]


def test_availability_invalid_timezone_is_typed_422(ctx):
    r = ctx.get(
        f"/api/v1/tutors/{ctx.world.tutor_id}/availability",
        params={"timezone": "Mars/Olympus_Mons"},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "VALIDATION_ERROR"
    assert r.json()["detail"]["field"] == "iana_timezone"


def test_availability_invalid_date_is_422(ctx):
    for bad in ("2026-13-40", "not-a-date", "2026-02-30"):
        r = ctx.get(
            f"/api/v1/tutors/{ctx.world.tutor_id}/availability", params={"date": bad}
        )
        assert r.status_code == 422, bad
        assert r.json()["detail"]["code"] == "validation_error"


def test_availability_dst_ambiguous_local_time_reports_the_earlier_occurrence(ctx):
    """01:30 on 2026-11-01 happens TWICE in America/New_York (fall back).

    The policy is "keep the earlier occurrence" and SAY SO; silently picking one
    is what makes a booking land an hour away from what the student read.
    """
    r = ctx.get(
        f"/api/v1/tutors/{ctx.world.tutor_id}/availability",
        params={
            "timezone": "America/New_York",
            "from_local": "2026-11-01T01:30:00",
            "to_local": "2026-11-01T03:00:00",
        },
    )
    assert r.status_code == 200, r.text
    resolved = r.json()["local_resolution"]["from_local"]
    assert resolved["classification"] == "ambiguous"
    assert resolved["dst_adjusted"] is True
    # EDT (-04:00) is the earlier of the two 01:30s; EST (-05:00) is the later.
    assert resolved["instant_utc"] == "2026-11-01T05:30:00+00:00"
    assert resolved["resolved_local"].startswith("2026-11-01T01:30:00-04:00")


def test_availability_dst_nonexistent_local_time_is_shifted_past_the_gap(ctx):
    """02:30 on 2027-03-14 does not exist in America/New_York (spring forward)."""
    r = ctx.get(
        f"/api/v1/tutors/{ctx.world.tutor_id}/availability",
        params={"timezone": "America/New_York", "from_local": "2027-03-14T02:30:00"},
    )
    assert r.status_code == 200, r.text
    resolved = r.json()["local_resolution"]["from_local"]
    assert resolved["classification"] == "nonexistent"
    assert resolved["dst_adjusted"] is True
    assert resolved["resolved_local"].startswith("2027-03-14T03:30:00-04:00")


def test_availability_local_date_window_resolves_both_edges(ctx):
    r = ctx.get(
        f"/api/v1/tutors/{ctx.world.tutor_id}/availability",
        params={"timezone": "Asia/Kolkata", "date": "2026-07-11"},
    )
    assert r.status_code == 200, r.text
    resolution = r.json()["local_resolution"]
    assert set(resolution) == {"from_local", "to_local"}
    assert all(v["classification"] == "unique" for v in resolution.values())
    # exactly the one slot that starts on that local day
    assert len(r.json()["slots"]) == 1


def test_availability_rejects_a_mixed_or_offset_bearing_window(ctx):
    path = f"/api/v1/tutors/{ctx.world.tutor_id}/availability"
    mixed = ctx.get(path, params={"from_local": "2026-07-11T00:00:00", "to_utc": "2026-07-12T00:00:00"})
    assert mixed.status_code == 422 and mixed.json()["detail"]["code"] == "VALIDATION_ERROR"
    both = ctx.get(path, params={"date": "2026-07-11", "from_local": "2026-07-11T00:00:00"})
    assert both.status_code == 422
    aware = ctx.get(path, params={"from_local": "2026-07-11T00:00:00+05:30"})
    assert aware.status_code == 422 and aware.json()["detail"]["field"] == "from_local"
    junk = ctx.get(path, params={"from_local": "yesterday"})
    assert junk.status_code == 422


def test_availability_unknown_tutor_404_and_auth_gates(ctx):
    assert ctx.get(f"/api/v1/tutors/{uuid.uuid4()}/availability").status_code == 404
    path = f"/api/v1/tutors/{ctx.world.tutor_id}/availability"
    assert ctx.client.get(path).status_code == 401
    assert ctx.get(path, roles=("lawyer",)).status_code == 403
    assert ctx.get("/api/v1/tutors/nope/availability").status_code == 422


# --------------------------------------------------------------------------- #
# B1/B2 — booking holds
# --------------------------------------------------------------------------- #


def _hold(ctx, *, slot=None, key="k-1", user=None):
    return ctx.post(
        "/api/v1/tutoring/booking-holds",
        user=user,
        json={"slot_id": str(slot or ctx.world.slot_id), "idempotency_key": key},
    )


def test_create_hold_happy_path_201_and_slot_becomes_held(ctx):
    r = _hold(ctx)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "active" and body["replayed"] is False
    assert body["hold_minutes"] == 10
    assert body["expires_at"] == (T0 + timedelta(minutes=10)).isoformat()
    with ctx.fresh() as s:
        assert s.get(TutorAvailabilitySlot, ctx.world.slot_id).status == "held"
        assert s.scalar(select(func.count()).select_from(BookingHold)) == 1


def test_create_hold_identical_replay_returns_the_same_row_and_200(ctx):
    first = _hold(ctx)
    again = _hold(ctx)
    assert first.status_code == 201 and again.status_code == 200
    assert again.json()["id"] == first.json()["id"]
    assert again.json()["replayed"] is True
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(BookingHold)) == 1


def test_create_hold_same_key_different_slot_is_typed_key_reuse(ctx):
    _hold(ctx)
    r = _hold(ctx, slot=ctx.world.slots[1], key="k-1")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REUSE"


def test_create_hold_different_key_loses_the_slot_race(ctx):
    assert _hold(ctx, key="a").status_code == 201
    r = _hold(ctx, key="b", user=ctx.world.other_student_id)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "HOLD_CONFLICT"
    with ctx.fresh() as s:  # the loser wrote nothing
        assert s.scalar(select(func.count()).select_from(BookingHold)) == 1


def test_create_hold_on_a_consumed_slot_is_typed_unavailable(ctx):
    """Once the slot is BOOKED a fresh key must not resurrect it."""
    _paid_flow(ctx)
    r = _hold(ctx, key="after-booking", user=ctx.world.other_student_id)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SLOT_UNAVAILABLE"


def test_expired_hold_replay_is_typed_and_a_new_key_self_heals(ctx):
    assert _hold(ctx, key="ttl").status_code == 201
    ctx.clock.shift(minutes=10, seconds=1)  # past the configured 10-minute TTL
    replay = _hold(ctx, key="ttl")
    assert replay.status_code == 409 and replay.json()["detail"]["code"] == "HOLD_EXPIRED"
    fresh = _hold(ctx, key="ttl-2", user=ctx.world.other_student_id)
    assert fresh.status_code == 201, fresh.text  # the sweeper freed the slot


def test_create_hold_rejects_malformed_and_extra_fields(ctx):
    for body in (
        {"slot_id": str(uuid.uuid4()), "idempotency_key": "k", "surprise": 1},
        {"slot_id": str(uuid.uuid4())},
        {"idempotency_key": "k"},
        {"slot_id": "not-a-uuid", "idempotency_key": "k"},
        {"slot_id": str(uuid.uuid4()), "idempotency_key": ""},
        {"slot_id": str(uuid.uuid4()), "idempotency_key": "x" * 201},
    ):
        r = ctx.post("/api/v1/tutoring/booking-holds", json=body)
        assert r.status_code == 422, (body, r.text)
        assert r.json()["detail"]["code"] == "validation_error"
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(BookingHold)) == 0


def test_create_hold_unknown_slot_404_and_auth_gates(ctx):
    assert _hold(ctx, slot=uuid.uuid4()).status_code == 404
    unauth = ctx.client.post(
        "/api/v1/tutoring/booking-holds",
        json={"slot_id": str(ctx.world.slot_id), "idempotency_key": "k"},
    )
    assert unauth.status_code == 401
    wrong = ctx.post(
        "/api/v1/tutoring/booking-holds",
        roles=("lawyer",),
        json={"slot_id": str(ctx.world.slot_id), "idempotency_key": "k"},
    )
    assert wrong.status_code == 403


def test_read_hold_is_owner_scoped_and_non_enumerating(ctx):
    hold_id = _hold(ctx).json()["id"]
    mine = ctx.get(f"/api/v1/tutoring/booking-holds/{hold_id}")
    assert mine.status_code == 200 and mine.json()["expired"] is False
    theirs = ctx.get(
        f"/api/v1/tutoring/booking-holds/{hold_id}", user=ctx.world.other_student_id
    )
    unknown = ctx.get(f"/api/v1/tutoring/booking-holds/{uuid.uuid4()}")
    assert theirs.status_code == unknown.status_code == 404
    assert theirs.json()["detail"] == unknown.json()["detail"]  # one shape, no oracle
    assert ctx.client.get(f"/api/v1/tutoring/booking-holds/{hold_id}").status_code == 401
    assert ctx.get(f"/api/v1/tutoring/booking-holds/{hold_id}", roles=("admin",)).status_code == 403
    assert ctx.get("/api/v1/tutoring/booking-holds/not-a-uuid").status_code == 422


# --------------------------------------------------------------------------- #
# C1 — payment orders
# --------------------------------------------------------------------------- #


def _order(ctx, hold_id, *, amount=AMOUNT, key="o-1", user=None, **extra):
    body = {
        "hold_id": hold_id,
        "amount_paise": amount,
        "idempotency_key": key,
        **extra,
    }
    return ctx.post("/api/v1/payments/orders", user=user, json=body)


def test_create_order_happy_path_201(ctx):
    hold_id = _hold(ctx).json()["id"]
    r = _order(ctx, hold_id, payment_token=TOKEN_SUCCESS)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["amount_paise"] == AMOUNT and body["currency"] == "INR"
    assert body["status"] == "created" and body["provider"] == "deterministic"
    assert body["provider_order_ref"].startswith("det_ord_")
    assert body["replayed"] is False


def test_create_order_identical_replay_returns_the_same_order_and_200(ctx):
    hold_id = _hold(ctx).json()["id"]
    first = _order(ctx, hold_id)
    again = _order(ctx, hold_id)
    assert first.status_code == 201 and again.status_code == 200
    assert again.json()["id"] == first.json()["id"] and again.json()["replayed"] is True
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(PaymentOrder)) == 1


def test_create_order_same_key_different_amount_is_typed_422(ctx):
    hold_id = _hold(ctx).json()["id"]
    _order(ctx, hold_id)
    r = _order(ctx, hold_id, amount=AMOUNT + 1)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "VALIDATION_ERROR"


def test_create_order_refuses_card_data_fields_without_echoing_them(ctx):
    """J1. ``extra="forbid"`` is the PCI guard, and the 422 must not echo it."""
    hold_id = _hold(ctx).json()["id"]
    for extra in (
        {"pan": "4111111111111111"},
        {"card_number": "4111111111111111"},
        {"cvv": "123"},
        {"otp": "654321"},
        {"payment_otp": "654321"},
        {"provider_secret": "rzp_live_secret"},
    ):
        r = _order(ctx, hold_id, **extra)
        assert r.status_code == 422, extra
        assert r.json()["detail"]["code"] == "validation_error"
        for value in extra.values():
            assert value not in r.text
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(PaymentOrder)) == 0


def test_create_order_payment_token_must_be_a_token_shape(ctx):
    hold_id = _hold(ctx).json()["id"]
    for token in (
        "4111111111111111",  # a PAN
        "4111 1111 1111 1111",  # a spaced PAN
        "4111-1111-1111-1111",
        "123",  # a CVV
        "654321",  # an OTP
        "tok_",  # too short to be a real token id
        "  ",
        "tok_with spaces",
    ):
        r = _order(ctx, hold_id, payment_token=token)
        assert r.status_code == 422, token
        assert r.json()["detail"]["code"] == "validation_error"
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(PaymentOrder)) == 0


def test_create_order_never_echoes_a_rejected_card_value(ctx):
    """J1. The 422 body carries type/loc/msg only — never the submitted value."""
    hold_id = _hold(ctx).json()["id"]
    for secret in ("4111111111111111", "654321", "4111-1111-1111-1111"):
        r = _order(ctx, hold_id, payment_token=secret)
        assert r.status_code == 422
        assert secret not in r.text
        for error in r.json()["detail"]["errors"]:
            assert set(error) == {"type", "loc", "msg"}


def test_create_order_never_persists_the_payment_token(ctx):
    """J1. The token is validated at the boundary and discarded."""
    hold_id = _hold(ctx).json()["id"]
    assert _order(ctx, hold_id, payment_token=TOKEN_SUCCESS).status_code == 201
    with ctx.fresh() as s:
        blobs = json.dumps(
            [
                {"a": e.action, "b": e.before_state, "c": e.after_state}
                for e in s.scalars(select(AuditEvent)).all()
            ]
        )
        order = s.scalar(select(PaymentOrder))
        assert TOKEN_SUCCESS not in blobs
        assert TOKEN_SUCCESS not in json.dumps(
            {c.name: str(getattr(order, c.name)) for c in PaymentOrder.__table__.columns}
        )


def test_create_order_against_an_expired_hold_is_refused(ctx):
    hold_id = _hold(ctx).json()["id"]
    ctx.clock.shift(minutes=11)
    r = _order(ctx, hold_id)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "HOLD_EXPIRED"
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(PaymentOrder)) == 0


def test_create_order_cross_user_hold_is_non_enumerating_404(ctx):
    hold_id = _hold(ctx).json()["id"]
    theirs = _order(ctx, hold_id, user=ctx.world.other_student_id, key="o-other")
    unknown = _order(ctx, str(uuid.uuid4()), key="o-unknown")
    assert theirs.status_code == unknown.status_code == 404
    assert theirs.json()["detail"] == unknown.json()["detail"]


def test_create_order_malformed_bodies_are_422(ctx):
    for body in (
        {"amount_paise": AMOUNT, "idempotency_key": "k"},
        {"hold_id": "not-a-uuid", "amount_paise": AMOUNT, "idempotency_key": "k"},
        {"hold_id": str(uuid.uuid4()), "amount_paise": -1, "idempotency_key": "k"},
        {"hold_id": str(uuid.uuid4()), "amount_paise": 1.5, "idempotency_key": "k"},
        {"hold_id": str(uuid.uuid4()), "amount_paise": True, "idempotency_key": "k"},
        {"hold_id": str(uuid.uuid4()), "amount_paise": AMOUNT, "idempotency_key": "k", "currency": "USD"},
    ):
        r = ctx.post("/api/v1/payments/orders", json=body)
        assert r.status_code == 422, (body, r.text)


def test_create_order_negative_amount_never_reaches_the_provider(ctx):
    hold_id = _hold(ctx).json()["id"]
    r = _order(ctx, hold_id, amount=-1)
    assert r.status_code == 422
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(PaymentOrder)) == 0


def test_create_order_auth_gates(ctx):
    hold_id = _hold(ctx).json()["id"]
    body = {"hold_id": hold_id, "amount_paise": AMOUNT, "idempotency_key": "z"}
    assert ctx.client.post("/api/v1/payments/orders", json=body).status_code == 401
    assert ctx.post("/api/v1/payments/orders", roles=("admin",), json=body).status_code == 403


# --------------------------------------------------------------------------- #
# C2 — verified webhook
# --------------------------------------------------------------------------- #


def _event(order_ref, *, amount=AMOUNT, token=TOKEN_SUCCESS, event_id=None):
    adapter = DeterministicPaymentAdapter()
    return adapter.make_event_body(
        provider_order_ref=order_ref, amount_paise=amount, token=token, event_id=event_id
    )


def _deliver(ctx, raw, signature):
    return ctx.client.post(
        "/api/v1/payments/webhook", content=raw, headers={PAY_SIG: signature}
    )


def _paid_flow(ctx, *, slot=None, amount=AMOUNT, key="flow"):
    """hold -> order -> VERIFIED paid webhook, all through HTTP."""
    hold = _hold(ctx, slot=slot, key=f"h-{key}").json()
    order = _order(ctx, hold["id"], amount=amount, key=f"o-{key}").json()
    raw, sig = _event(order["provider_order_ref"], amount=amount)
    return hold, order, _deliver(ctx, raw, sig)


def test_verified_paid_webhook_books_the_session(ctx):
    hold, order, r = _paid_flow(ctx)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["event_type"] == "paid" and body["applied"] is True
    assert body["order_status"] == "paid" and body["session_id"]
    with ctx.fresh() as s:
        sess = s.scalar(select(TutoringSession))
        assert sess is not None and sess.status == "confirmed"
        assert s.get(BookingHold, uuid.UUID(hold["id"])).status == "consumed"
        assert s.get(TutorAvailabilitySlot, ctx.world.slot_id).status == "booked"
        kinds = {row.kind for row in W.outbox_rows(s)}
        assert {"booking_confirmed", "payment_captured"} <= kinds


def test_webhook_invalid_signature_writes_nothing(ctx):
    order = _order(ctx, _hold(ctx, key="h").json()["id"], key="o").json()
    raw, _good = _event(order["provider_order_ref"])
    for signature in ("", "deadbeef", "0" * 64):
        r = _deliver(ctx, raw, signature)
        assert r.status_code == 400, signature
        assert r.json()["detail"]["code"] == "PAYMENT_UNVERIFIED"
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(PaymentEvent)) == 0
        assert s.scalar(select(func.count()).select_from(TutoringSession)) == 0


def test_webhook_malformed_body_is_a_typed_400_not_a_500(ctx):
    adapter = DeterministicPaymentAdapter()
    raw = b"{not json at all"
    r = _deliver(ctx, raw, adapter.sign(raw))
    assert r.status_code == 400 and r.json()["detail"]["code"] == "PAYMENT_UNVERIFIED"
    assert "not json at all" not in r.text  # the body is never echoed


def test_webhook_unsupported_event_type_is_refused(ctx):
    adapter = DeterministicPaymentAdapter()
    raw = json.dumps({"event_type": "chargeback", "event_id": "e1"}).encode()
    r = _deliver(ctx, raw, adapter.sign(raw))
    assert r.status_code == 400 and r.json()["detail"]["code"] == "PAYMENT_UNVERIFIED"


def test_webhook_unknown_order_is_404(ctx):
    raw, sig = _event("det_ord_nosuchorderref")
    r = _deliver(ctx, raw, sig)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "NOT_FOUND"


def test_webhook_duplicate_event_id_has_exactly_one_side_effect(ctx):
    hold = _hold(ctx, key="h").json()
    order = _order(ctx, hold["id"], key="o").json()
    raw, sig = _event(order["provider_order_ref"], event_id="evt-fixed")
    first = _deliver(ctx, raw, sig)
    again = _deliver(ctx, raw, sig)
    assert first.status_code == 200 and again.status_code == 409
    assert again.json()["detail"]["code"] == "DUPLICATE_EVENT"
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(PaymentEvent)) == 1
        assert s.scalar(select(func.count()).select_from(TutoringSession)) == 1
        assert len(W.outbox_rows(s, kind="payment_captured")) == 1


def test_webhook_amount_mismatch_is_422_and_leaves_no_ledger_row(ctx):
    hold = _hold(ctx, key="h").json()
    order = _order(ctx, hold["id"], key="o").json()
    raw, sig = _event(order["provider_order_ref"], amount=AMOUNT + 1)
    r = _deliver(ctx, raw, sig)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "AMOUNT_MISMATCH"
    assert r.json()["detail"]["expected_paise"] == AMOUNT
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(PaymentEvent)) == 0
        assert s.scalar(select(func.count()).select_from(TutoringSession)) == 0
        assert s.get(PaymentOrder, uuid.UUID(order["id"])).status == "created"


def test_webhook_currency_mismatch_is_422(ctx):
    hold = _hold(ctx, key="h").json()
    order = _order(ctx, hold["id"], key="o").json()
    adapter = DeterministicPaymentAdapter()
    # Forged by hand: make_event_body refuses to build a non-INR body at all,
    # which is precisely why a mismatched currency has to be constructed here.
    payload = {
        "provider": "deterministic",
        "event_id": "evt-usd",
        "token": TOKEN_SUCCESS,
        "event_type": "paid",
        "order_ref": order["provider_order_ref"],
        "amount_paise": AMOUNT,
        "currency": "USD",
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    r = _deliver(ctx, raw, adapter.sign(raw))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "AMOUNT_MISMATCH"
    assert r.json()["detail"]["observed"] == "USD"
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(PaymentEvent)) == 0


def test_webhook_user_mismatch_is_refused_at_the_service_seam(ctx):
    """The ROUTE cannot check this: a provider callback carries no end-user id.

    ``handle_event`` still enforces it for every other caller (worker, CLI,
    reconciliation job), so the rule is proven where it is actually reachable.
    """
    from app.services.tutoring.errors import Forbidden

    hold = _hold(ctx, key="h").json()
    order = _order(ctx, hold["id"], key="o").json()
    raw, sig = _event(order["provider_order_ref"])
    with ctx.fresh() as s:
        with pytest.raises(Forbidden) as excinfo:
            payments_service.handle_event(
                s,
                signature=sig,
                raw_body=raw,
                expected_student_user_id=ctx.world.other_student_id,
                now=T0,
            )
        assert excinfo.value.code == "FORBIDDEN"
        s.rollback()
        assert s.scalar(select(func.count()).select_from(TutoringSession)) == 0


def test_payment_arriving_after_hold_expiry_books_nothing(ctx):
    hold = _hold(ctx, key="h").json()
    order = _order(ctx, hold["id"], key="o").json()
    ctx.clock.shift(minutes=11)  # the hold TTL elapses before the provider calls
    raw, sig = _event(order["provider_order_ref"])
    r = _deliver(ctx, raw, sig)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "HOLD_EXPIRED"
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(TutoringSession)) == 0
        assert s.scalar(select(func.count()).select_from(PaymentEvent)) == 0
        assert s.get(PaymentOrder, uuid.UUID(order["id"])).status == "created"
        assert not W.outbox_rows(s)


def test_out_of_order_failure_after_capture_is_recorded_but_not_applied(ctx):
    """A late ``failed`` delivery must not contradict money we already took."""
    hold, order, paid = _paid_flow(ctx)
    assert paid.status_code == 200
    raw, sig = _event(order["provider_order_ref"], token=TOKEN_DECLINED)
    late = _deliver(ctx, raw, sig)
    assert late.status_code == 200, late.text
    assert late.json()["out_of_order"] is True and late.json()["applied"] is False
    assert late.json()["order_status"] == "paid"
    with ctx.fresh() as s:
        assert s.get(PaymentOrder, uuid.UUID(order["id"])).status == "paid"
        assert s.scalar(select(TutoringSession)).status == "confirmed"
        assert s.get(TutorAvailabilitySlot, ctx.world.slot_id).status == "booked"
        assert s.get(BookingHold, uuid.UUID(hold["id"])).status == "consumed"
        assert s.scalar(select(func.count()).select_from(PaymentEvent)) == 2
        assert W.audit_rows(s, "tutoring.payment.event_out_of_order")
        assert not W.audit_rows(s, "tutoring.payment.failed")
        kinds = [row.kind for row in W.outbox_rows(s)]
        assert kinds.count("payment_captured") == 1


def test_out_of_order_pending_after_capture_is_also_ignored(ctx):
    _hold_body, order, paid = _paid_flow(ctx)
    assert paid.status_code == 200
    raw, sig = _event(order["provider_order_ref"], token=TOKEN_PENDING)
    late = _deliver(ctx, raw, sig)
    assert late.status_code == 200 and late.json()["out_of_order"] is True
    with ctx.fresh() as s:
        assert s.get(PaymentOrder, uuid.UUID(order["id"])).status == "paid"


def test_failed_event_releases_the_slot_when_it_arrives_in_order(ctx):
    hold = _hold(ctx, key="h").json()
    order = _order(ctx, hold["id"], key="o").json()
    raw, sig = _event(order["provider_order_ref"], token=TOKEN_DECLINED)
    r = _deliver(ctx, raw, sig)
    assert r.status_code == 200 and r.json()["slot_released"] is True
    with ctx.fresh() as s:
        assert s.get(TutorAvailabilitySlot, ctx.world.slot_id).status == "available"
        assert s.get(PaymentOrder, uuid.UUID(order["id"])).status == "failed"


def test_webhook_body_over_the_ceiling_is_413(ctx):
    adapter = DeterministicPaymentAdapter()
    raw = b'{"event_type":"paid","pad":"' + b"x" * (64 * 1024) + b'"}'
    r = _deliver(ctx, raw, adapter.sign(raw))
    assert r.status_code == 413 and r.json()["detail"]["code"] == "payload_too_large"


# --------------------------------------------------------------------------- #
# C3 — session creation only on a verified payment
# --------------------------------------------------------------------------- #


def test_create_session_replays_the_webhook_created_session(ctx):
    hold, _order, paid = _paid_flow(ctx)
    r = ctx.post("/api/v1/tutoring/sessions", json={"hold_id": hold["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["replayed"] is True
    assert r.json()["id"] == paid.json()["session_id"]
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(TutoringSession)) == 1


def test_create_session_on_an_unpaid_hold_is_refused(ctx):
    hold = _hold(ctx, key="h").json()
    r = ctx.post("/api/v1/tutoring/sessions", json={"hold_id": hold["id"]})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "PAYMENT_UNVERIFIED"
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(TutoringSession)) == 0
        assert s.get(TutorAvailabilitySlot, ctx.world.slot_id).status == "held"


def test_create_session_on_an_order_with_no_verified_event_is_refused(ctx):
    """An order marked paid by hand, with no signed event, still books nothing."""
    hold = _hold(ctx, key="h").json()
    order = _order(ctx, hold["id"], key="o").json()
    with ctx.SessionLocal() as s:
        row = s.get(PaymentOrder, uuid.UUID(order["id"]))
        row.status = "paid"
        s.commit()
    r = ctx.post("/api/v1/tutoring/sessions", json={"hold_id": hold["id"]})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "PAYMENT_UNVERIFIED"
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(TutoringSession)) == 0
        assert not W.outbox_rows(s)


def test_create_session_cross_user_and_malformed(ctx):
    hold, _o, _paid = _paid_flow(ctx)
    theirs = ctx.post(
        "/api/v1/tutoring/sessions",
        user=ctx.world.other_student_id,
        json={"hold_id": hold["id"]},
    )
    unknown = ctx.post("/api/v1/tutoring/sessions", json={"hold_id": str(uuid.uuid4())})
    assert theirs.status_code == unknown.status_code == 404
    assert theirs.json()["detail"] == unknown.json()["detail"]
    assert ctx.post(
        "/api/v1/tutoring/sessions", json={"hold_id": hold["id"], "extra": 1}
    ).status_code == 422
    assert ctx.post("/api/v1/tutoring/sessions", json={"hold_id": "nope"}).status_code == 422
    assert ctx.client.post(
        "/api/v1/tutoring/sessions", json={"hold_id": hold["id"]}
    ).status_code == 401
    assert ctx.post(
        "/api/v1/tutoring/sessions", roles=("lawyer",), json={"hold_id": hold["id"]}
    ).status_code == 403


def test_booking_trail_and_audit_carry_ids_and_codes_only(ctx):
    """J1. The booking trail is forensic, not narrative."""
    _paid_flow(ctx)
    with ctx.fresh() as s:
        kinds = [row.kind for row in s.scalars(select(BookingEvent)).all()]
        assert {"hold_created", "payment_initiated", "payment_succeeded",
                "hold_consumed", "session_confirmed"} <= set(kinds)
        blob = json.dumps(
            [row.payload_json for row in s.scalars(select(BookingEvent)).all()]
            + [
                {"before": e.before_state, "after": e.after_state}
                for e in s.scalars(select(AuditEvent)).all()
            ]
            + [row.payload_json for row in s.scalars(select(TutoringOutbox)).all()]
        ).lower()
    for canary in ("pan", "cvv", "otp", "4111", "sdp", "ice_candidate", "device_label", "@"):
        assert canary not in blob, canary
