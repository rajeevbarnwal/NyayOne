"""The session price is the SERVER's (SAATHI-123 / SAATHI-127 remediation).

Independent QA reproduced the defect this file closes: ``POST /payments/orders``
took ``amount_paise`` from the request body, so a malicious client could open a
zero-priced or under-priced order — and a *correctly signed* provider callback
would then only ever prove payment of the attacker-chosen amount. The signature
was never the weak link. The price was.

What is proven here, and where:

* **tampering** — 0, 1, one paisa under, one paisa over, and a currency that is
  not this session's, at the HTTP boundary AND at the service seam, each refused
  with a typed code and **zero rows written** (orders, sessions, payment events,
  audit rows and outbox rows are all counted before and after);
* **the exact authoritative amount succeeds**, and so does omitting the amount
  entirely — which is now the correct way to call the endpoint;
* **idempotent replay** returns the SAME order and writes no second row;
* **concurrency** — eight callers racing one hold produce exactly ONE logical
  order, through the mounted app, on a serialised file-backed database;
* **failure atomicity** — a forced commit failure and a provider failure each
  leave no partial session / payment / audit / outbox state;
* **a signed callback carrying the wrong amount is refused**, and so is a
  correctly signed callback for an order whose amount no longer matches the
  hold snapshot it was derived from;
* **positivity** — a zero or negative authoritative price is refused at
  ``pricing.set_tutor_session_price``, the one seam that could create one, and
  by the ``> 0`` CHECK constraints underneath it;
* **immutability** — re-pricing a tutor mid-checkout cannot move the amount of a
  hold that is already in flight, and a hold replay returns the original number.

Everything goes through the REAL services and the REAL mounted app (see
``tests/wave2_helpers.py``); nothing here fabricates a priced row by hand.
"""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import tests.wave2_helpers as W
from app.core import rate_limit
from app.core.config import settings
from app.db.models.audit import AuditEvent
from app.models.wave2 import (
    BookingEvent,
    BookingHold,
    PaymentEvent,
    PaymentOrder,
    TutorAvailabilitySlot,
    TutoringOutbox,
    TutoringSession,
    TutorProfile,
)
from app.services.providers.payment_provider import (
    TOKEN_SUCCESS,
    DeterministicPaymentAdapter,
    FailingPaymentAdapter,
)
from app.services.tutoring import booking, errors, payments, pricing
from app.services.tutoring import seed as tutoring_seed

T0 = W.T0
#: The authoritative price every fixture tutor publishes, in INTEGER PAISE.
AUTHORITATIVE = W.AMOUNT_PAISE
PAY_SIG = "X-Payment-Signature"


# --------------------------------------------------------------------------- #
# Rigs
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def rig():
    built = W.ApiRig()
    yield built
    built.close()


@pytest.fixture()
def ctx(monkeypatch, rig):
    context = rig.context(monkeypatch, now=T0)
    yield context
    rate_limit.reset()


@pytest.fixture()
def world(db_session: Session):
    return W.build_world(db_session, now=T0)


def _hold(ctx, *, key="h", slot=None, user=None):
    return ctx.post(
        "/api/v1/tutoring/booking-holds",
        user=user,
        json={"slot_id": str(slot or ctx.world.slot_id), "idempotency_key": key},
    )


def _order_body(hold_id, *, amount=None, currency=None, key="o"):
    body: dict = {"hold_id": hold_id, "idempotency_key": key}
    if amount is not None:
        body["amount_paise"] = amount
    if currency is not None:
        body["currency"] = currency
    return body


class Ledger:
    """Every table a refused payment request must not touch, counted."""

    TABLES = {
        "orders": PaymentOrder,
        "sessions": TutoringSession,
        "payment_events": PaymentEvent,
        "booking_events": BookingEvent,
        "audit": AuditEvent,
        "outbox": TutoringOutbox,
    }

    @staticmethod
    def counts(session: Session) -> dict[str, int]:
        return {
            name: int(
                session.scalar(select(func.count()).select_from(model)) or 0
            )
            for name, model in Ledger.TABLES.items()
        }


def _counts(ctx) -> dict[str, int]:
    with ctx.fresh() as s:
        return Ledger.counts(s)


# --------------------------------------------------------------------------- #
# 0. the constants that must never drift apart
# --------------------------------------------------------------------------- #


def test_the_authoritative_default_price_is_one_number_in_five_places():
    """Settings, the ORM default, the seed fixture and migration 0009 agree.

    Independent copies of 250000 exist by necessity: a migration must not import
    runtime settings, and the seed fixture must be stable whatever a deployment
    configures. Pinning them equal HERE is what stops the fixture quoting one
    price while the schema defaults to another.
    """
    assert settings.tutoring_default_session_price_paise == 250_000
    assert pricing.FALLBACK_SESSION_PRICE_PAISE == 250_000
    assert tutoring_seed.SEED_SESSION_PRICE_PAISE == 250_000
    assert W.AMOUNT_PAISE == 250_000
    orm_default = TutorProfile.__table__.c.session_price_paise
    assert orm_default.server_default.arg == "250000"
    assert str(TutorProfile.__table__.c.session_currency.server_default.arg) == "INR"
    assert _migration_default() == 250_000
    # Integer paise, never a float or a Decimal, anywhere on the money path.
    assert isinstance(settings.tutoring_default_session_price_paise, int)
    assert not isinstance(settings.tutoring_default_session_price_paise, bool)


def _migration_default() -> int:
    """Read 0009's literal without importing a module whose name starts 0-9."""
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[1]
        / "app" / "db" / "migrations" / "versions" / "0009_wave2_session_pricing.py"
    )
    spec = importlib.util.spec_from_file_location("m0009", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module.down_revision == "0008_wave2_tutoring"
    return int(module.DEFAULT_SESSION_PRICE_PAISE)


def test_the_deterministic_seed_publishes_exactly_250000_paise(db_session: Session):
    tutoring_seed.provision(db_session, now=T0, days=1, per_day=1)
    db_session.commit()
    profiles = db_session.scalars(select(TutorProfile)).all()
    assert profiles, "the seed created no tutor to price"
    for profile in profiles:
        assert profile.session_price_paise == 250_000
        assert profile.session_currency == "INR"
        assert isinstance(profile.session_price_paise, int)
    # And every seeded slot resolves to that same number through the ONE seam.
    slots = db_session.scalars(select(TutorAvailabilitySlot)).all()
    assert slots
    for slot in slots:
        resolved = pricing.resolve_for_slot(db_session, slot)
        assert resolved.amount_paise == 250_000 and resolved.currency == "INR"
        assert resolved.source == pricing.SOURCE_TUTOR_PROFILE


# --------------------------------------------------------------------------- #
# 1. positivity: refused at the seam that would create it
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bad", [0, -1, -250_000])
def test_a_zero_or_negative_authoritative_price_is_refused(db_session, world, bad):
    """0 is NOT free tutoring; it is a mispriced product. Refused, unchanged."""
    before = db_session.get(TutorProfile, world.tutor_id).session_price_paise
    with pytest.raises(errors.SessionPriceInvalid) as refused:
        pricing.set_tutor_session_price(
            db_session, world.tutor_id, amount_paise=bad, actor_role="admin"
        )
    assert refused.value.code == "SESSION_PRICE_INVALID"
    db_session.rollback()
    assert db_session.get(TutorProfile, world.tutor_id).session_price_paise == before
    assert not W.audit_rows(db_session, "tutoring.pricing.session_price_set")


@pytest.mark.parametrize("bad", [2500.0, Decimal("2500"), True, "2500", None])
def test_a_non_integer_paise_price_is_refused(db_session, world, bad):
    """No float, Decimal, bool or string may ever become a price.

    ``True`` matters: ``isinstance(True, int)`` is true in Python, so a bool
    would otherwise be accepted and price a session at one paisa.
    """
    with pytest.raises(errors.SessionPriceInvalid):
        pricing.set_tutor_session_price(
            db_session, world.tutor_id, amount_paise=bad  # type: ignore[arg-type]
        )
    db_session.rollback()


def test_the_database_refuses_a_non_positive_price_too(db_session, world):
    """Defence in depth: the ``> 0`` CHECK, not just the service."""
    profile = db_session.get(TutorProfile, world.tutor_id)
    profile.session_price_paise = 0
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_a_hold_snapshot_of_zero_is_unrepresentable(db_session, world):
    hold = W.place_hold(db_session, world, now=T0)
    db_session.commit()
    hold.price_paise = 0
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


# --------------------------------------------------------------------------- #
# 2. the hold snapshot: taken from the server, immutable afterwards
# --------------------------------------------------------------------------- #


def test_creating_a_hold_snapshots_the_authoritative_price(db_session, world):
    hold = W.place_hold(db_session, world, now=T0)
    db_session.commit()
    assert hold.price_paise == AUTHORITATIVE and hold.price_currency == "INR"
    snapshot = pricing.snapshot_of_hold(hold)
    assert snapshot.amount_paise == AUTHORITATIVE
    assert snapshot.source == pricing.SOURCE_HOLD_SNAPSHOT
    # create_hold has NO price parameter, so a caller could not propose one.
    import inspect as _inspect

    assert "price" not in _inspect.signature(booking.create_hold).parameters
    assert "amount_paise" not in _inspect.signature(booking.create_hold).parameters


def test_repricing_the_tutor_cannot_move_a_hold_already_in_flight(db_session, world):
    hold = W.place_hold(db_session, world, now=T0, key="k-immutable")
    db_session.commit()
    pricing.set_tutor_session_price(
        db_session, world.tutor_id, amount_paise=999_900, actor_role="admin"
    )
    db_session.commit()

    db_session.refresh(hold)
    assert hold.price_paise == AUTHORITATIVE, "the snapshot moved"
    # An idempotent replay returns the SAME row with the SAME frozen price...
    replay = booking.create_hold(
        db_session,
        slot_id=world.slot_id,
        student_user_id=world.student_id,
        idempotency_key="k-immutable",
        now=T0,
    )
    assert replay.id == hold.id and replay.price_paise == AUTHORITATIVE
    # ...and the order charges the SNAPSHOT, not the new published price.
    _adapter, order = W.open_order(db_session, world, hold, amount_paise=None, now=T0)
    assert order.amount_paise == AUTHORITATIVE
    # A hold taken AFTER the re-price gets the new number — the price is live,
    # it is just frozen per hold.
    later = booking.create_hold(
        db_session,
        slot_id=world.slots[1],
        student_user_id=world.student_id,
        idempotency_key="k-after",
        now=T0,
    )
    assert later.price_paise == 999_900


# --------------------------------------------------------------------------- #
# 3. tampering at the HTTP boundary — typed refusal, ZERO rows written
# --------------------------------------------------------------------------- #

#: (label, amount, currency, HTTP code, service code). Every row is a real
#: attack shape: free, near-free, a haggle, an overpay, and the wrong money.
#:
#: The two codes differ for ONE row on purpose. A non-INR currency is a request
#: SHAPE violation (``currency: Literal["INR"]``), so FastAPI refuses it at the
#: boundary with the house-wide lowercase ``validation_error`` envelope before
#: any service is reached; the same value handed straight to the service is the
#: domain's own upper-case ``VALIDATION_ERROR``. Both are typed, both refuse,
#: both write nothing — asserting the real code at each seam is the point.
TAMPERING = (
    ("zero", 0, None, "PAYMENT_AMOUNT_MISMATCH", "PAYMENT_AMOUNT_MISMATCH"),
    ("one_paisa", 1, None, "PAYMENT_AMOUNT_MISMATCH", "PAYMENT_AMOUNT_MISMATCH"),
    (
        "one_paisa_under", AUTHORITATIVE - 1, None,
        "PAYMENT_AMOUNT_MISMATCH", "PAYMENT_AMOUNT_MISMATCH",
    ),
    (
        "one_paisa_over", AUTHORITATIVE + 1, None,
        "PAYMENT_AMOUNT_MISMATCH", "PAYMENT_AMOUNT_MISMATCH",
    ),
    (
        "half_price", AUTHORITATIVE // 2, None,
        "PAYMENT_AMOUNT_MISMATCH", "PAYMENT_AMOUNT_MISMATCH",
    ),
    ("wrong_currency", AUTHORITATIVE, "USD", "validation_error", "VALIDATION_ERROR"),
)


@pytest.mark.parametrize("label, amount, currency, code, _service_code", TAMPERING)
def test_tampered_order_is_refused_with_zero_rows_written(
    ctx, label, amount, currency, code, _service_code
):
    hold_id = _hold(ctx, key=f"h-{label}").json()["id"]
    before = _counts(ctx)

    refused = ctx.post(
        "/api/v1/payments/orders",
        json=_order_body(hold_id, amount=amount, currency=currency, key=f"o-{label}"),
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["code"] == code, refused.text

    after = _counts(ctx)
    assert after == before, f"{label} mutated the database: {before} -> {after}"
    assert after["orders"] == 0 and after["sessions"] == 0
    with ctx.fresh() as s:
        # The hold itself is untouched and still carries the true price.
        hold = s.get(BookingHold, uuid.UUID(hold_id))
        assert hold.status == "active"
        assert hold.price_paise == AUTHORITATIVE and hold.price_currency == "INR"
        assert not W.audit_rows(s, "tutoring.payment.order_created")


@pytest.mark.parametrize("label, amount, currency, _http_code, code", TAMPERING)
def test_a_tampered_amount_never_reaches_the_payment_provider(
    db_session, world, label, amount, currency, _http_code, code
):
    """The provider is called only AFTER the amount is proven to be the server's.

    A ``DeterministicPaymentAdapter`` records every order it is asked to create,
    so "no provider call" is asserted against the adapter itself rather than
    inferred from the absence of a row.
    """
    hold = W.place_hold(db_session, world, now=T0, key=f"svc-{label}")
    db_session.commit()
    adapter = DeterministicPaymentAdapter()
    before = Ledger.counts(db_session)

    with pytest.raises(errors.TutoringError) as refused:
        payments.create_order(
            db_session,
            hold_id=hold.id,
            student_user_id=world.student_id,
            amount_paise=amount,
            currency=currency,
            idempotency_key=f"svc-{label}",
            provider=adapter,
            now=T0,
        )
    assert refused.value.code == code
    assert refused.value.status_code == 422
    assert adapter.created_orders == [], "a tampered amount reached the provider"
    db_session.rollback()
    assert Ledger.counts(db_session) == before


def test_the_mismatch_error_reports_the_authoritative_amount(ctx):
    """A stale checkout screen must be able to re-render, not just fail."""
    hold_id = _hold(ctx, key="h-report").json()["id"]
    refused = ctx.post(
        "/api/v1/payments/orders",
        json=_order_body(hold_id, amount=1, key="o-report"),
    )
    detail = refused.json()["detail"]
    assert detail["code"] == "PAYMENT_AMOUNT_MISMATCH"
    assert detail["expected_paise"] == AUTHORITATIVE
    assert detail["observed_paise"] == 1
    assert detail["currency"] == "INR"
    assert detail["retryable"] is False


def test_a_currency_that_is_not_this_sessions_is_a_typed_mismatch(
    db_session, world, monkeypatch
):
    """The ``PAYMENT_AMOUNT_MISMATCH`` currency branch, reached honestly.

    Today ``PAYMENT_CURRENCIES == ("INR",)``, so a non-INR request is refused
    one step earlier as ``VALIDATION_ERROR`` ("this product has no such
    currency") and the branch below is unreachable through the boundary. Widen
    the supported set exactly as adding a second currency would, and the
    comparison against the HOLD SNAPSHOT is what refuses the request — which is
    the behaviour that must already be right on the day that ships.
    """
    monkeypatch.setattr(pricing, "PAYMENT_CURRENCIES", ("INR", "USD"))
    hold = W.place_hold(db_session, world, now=T0, key="cur")
    db_session.commit()
    before = Ledger.counts(db_session)
    adapter = DeterministicPaymentAdapter()

    with pytest.raises(errors.PaymentAmountMismatch) as refused:
        payments.create_order(
            db_session,
            hold_id=hold.id,
            student_user_id=world.student_id,
            amount_paise=AUTHORITATIVE,
            currency="USD",
            idempotency_key="cur",
            provider=adapter,
            now=T0,
        )
    assert refused.value.code == "PAYMENT_AMOUNT_MISMATCH"
    assert refused.value.extra["expected"] == "INR"
    assert refused.value.extra["observed"] == "USD"
    assert adapter.created_orders == []
    db_session.rollback()
    assert Ledger.counts(db_session) == before


# --------------------------------------------------------------------------- #
# 4. the honest paths
# --------------------------------------------------------------------------- #


def test_the_exact_authoritative_amount_succeeds(ctx):
    hold_id = _hold(ctx, key="h-ok").json()["id"]
    created = ctx.post(
        "/api/v1/payments/orders",
        json=_order_body(hold_id, amount=AUTHORITATIVE, key="o-ok"),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["amount_paise"] == AUTHORITATIVE and body["currency"] == "INR"
    with ctx.fresh() as s:
        row = s.scalars(select(PaymentOrder)).one()
        assert row.amount_paise == AUTHORITATIVE and row.currency == "INR"


def test_omitting_the_amount_entirely_is_the_correct_call(ctx):
    """The preferred client shape: send no amount at all; the server prices it."""
    hold_id = _hold(ctx, key="h-none").json()["id"]
    created = ctx.post(
        "/api/v1/payments/orders", json=_order_body(hold_id, key="o-none")
    )
    assert created.status_code == 201, created.text
    assert created.json()["amount_paise"] == AUTHORITATIVE
    assert created.json()["currency"] == "INR"


def test_the_api_publishes_the_authoritative_price_so_a_screen_need_not_guess(ctx):
    """No client may need a build-time fee setting to render the amount."""
    detail = ctx.get(f"/api/v1/tutors/{ctx.world.tutor_id}").json()
    assert detail["session_price_paise"] == AUTHORITATIVE
    assert detail["currency"] == "INR"

    listed = ctx.get("/api/v1/tutors").json()["items"]
    assert listed and all(t["session_price_paise"] == AUTHORITATIVE for t in listed)

    slots = ctx.get(f"/api/v1/tutors/{ctx.world.tutor_id}/availability").json()["slots"]
    assert slots and all(s["price_paise"] == AUTHORITATIVE for s in slots)
    assert all(s["currency"] == "INR" for s in slots)

    hold = _hold(ctx, key="h-published").json()
    assert hold["price_paise"] == AUTHORITATIVE and hold["currency"] == "INR"
    read_back = ctx.get(f"/api/v1/tutoring/booking-holds/{hold['id']}").json()
    assert read_back["price_paise"] == AUTHORITATIVE


def test_identical_replay_returns_the_same_order_and_no_second_row(ctx):
    hold_id = _hold(ctx, key="h-replay").json()["id"]
    first = ctx.post(
        "/api/v1/payments/orders",
        json=_order_body(hold_id, amount=AUTHORITATIVE, key="o-replay"),
    )
    again = ctx.post(
        "/api/v1/payments/orders",
        json=_order_body(hold_id, amount=AUTHORITATIVE, key="o-replay"),
    )
    once_more = ctx.post(  # ...and a replay that omits the amount is the same
        "/api/v1/payments/orders", json=_order_body(hold_id, key="o-replay")
    )
    assert first.status_code == 201
    assert again.status_code == 200 and once_more.status_code == 200
    assert again.json()["id"] == first.json()["id"]
    assert once_more.json()["id"] == first.json()["id"]
    assert again.json()["replayed"] is True
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(PaymentOrder)) == 1
        assert len(W.audit_rows(s, "tutoring.payment.order_created")) == 1


def test_the_same_key_replayed_with_a_tampered_amount_is_refused(ctx):
    """Key reuse is diagnosed as key reuse, and still writes nothing new."""
    hold_id = _hold(ctx, key="h-reuse").json()["id"]
    assert ctx.post(
        "/api/v1/payments/orders",
        json=_order_body(hold_id, amount=AUTHORITATIVE, key="o-reuse"),
    ).status_code == 201
    before = _counts(ctx)
    refused = ctx.post(
        "/api/v1/payments/orders", json=_order_body(hold_id, amount=0, key="o-reuse")
    )
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "VALIDATION_ERROR"
    assert _counts(ctx) == before


# --------------------------------------------------------------------------- #
# 5. concurrency: one hold, one logical order
# --------------------------------------------------------------------------- #


def test_eight_concurrent_orders_for_one_hold_yield_one_logical_order(
    tmp_path, monkeypatch
):
    """Eight callers, one hold, one idempotency key, released together.

    A file-backed engine with ``BEGIN IMMEDIATE`` makes SQLite serialise writers
    the way PostgreSQL serialises on ``uq_payment_orders_idempotency_key``, and
    the route table is materialised in the MAIN thread first so the race
    measures the database boundary rather than FastAPI's lazy route
    construction. The invariant is not "one caller succeeds": every caller may
    legitimately be answered, but there must be exactly ONE order row, ONE
    amount, and it must be the server's.
    """
    engine = W.serialized_file_engine(tmp_path, "wave2_order_race")
    ctx = W.api_context(monkeypatch, now=T0, engine=engine)
    monkeypatch.setattr(settings, "rate_limit_booking_per_min", 100)
    rate_limit.reset()
    assert W.materialise_routes(ctx.app) > 0
    hold_id = _hold(ctx, key="h-race").json()["id"]
    gate = threading.Barrier(8, timeout=20)

    def _attempt(index: int):
        gate.wait()
        return ctx.post(
            "/api/v1/payments/orders",
            json=_order_body(hold_id, amount=AUTHORITATIVE, key="o-race"),
        )

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(_attempt, range(8)))
        accepted = [r for r in results if r.status_code in (200, 201)]
        assert accepted, [(r.status_code, r.text[:160]) for r in results]
        # Every answered caller was handed the SAME order at the SAME price.
        ids = {r.json()["id"] for r in accepted}
        assert len(ids) == 1, ids
        assert {r.json()["amount_paise"] for r in accepted} == {AUTHORITATIVE}
        # A refusal, if any, must be typed — never a leaked 500.
        for refused in (r for r in results if r.status_code not in (200, 201)):
            assert refused.status_code < 500, refused.text
            assert refused.json()["detail"]["code"]
        with ctx.fresh() as s:
            assert s.scalar(select(func.count()).select_from(PaymentOrder)) == 1
            assert s.scalars(select(PaymentOrder)).one().amount_paise == AUTHORITATIVE
            assert len(W.audit_rows(s, "tutoring.payment.order_created")) == 1
    finally:
        from app.db.base import Base

        Base.metadata.drop_all(engine)
        engine.dispose()


# --------------------------------------------------------------------------- #
# 6. failure atomicity
# --------------------------------------------------------------------------- #


class _CommitFailOnce(Session):
    """A session whose next ``commit()`` really fails (see test_wave2_api_failures).

    The flag is read and cleared through the CLASS NAME, never ``type(self)``:
    ``sessionmaker(class_=X)`` instantiates a generated SUBCLASS, so
    ``type(self).arm = False`` would shadow the attribute a later test sets.
    """

    arm = False

    def commit(self):  # type: ignore[override]
        if _CommitFailOnce.arm:
            _CommitFailOnce.arm = False
            raise RuntimeError("forced commit failure (injected)")
        return super().commit()


@pytest.fixture(scope="module")
def failing_rig():
    built = W.ApiRig(session_class=_CommitFailOnce, raise_server_exceptions=False)
    yield built
    built.close()


@pytest.fixture()
def failing(monkeypatch, failing_rig):
    _CommitFailOnce.arm = False
    context = failing_rig.context(monkeypatch, now=T0)
    yield context
    _CommitFailOnce.arm = False
    rate_limit.reset()


def test_commit_failure_on_order_creation_leaves_no_partial_state(failing):
    ctx = failing
    hold_id = _hold(ctx, key="h-commit").json()["id"]
    before = _counts(ctx)
    _CommitFailOnce.arm = True
    boom = ctx.post(
        "/api/v1/payments/orders",
        json=_order_body(hold_id, amount=AUTHORITATIVE, key="o-commit"),
    )
    assert boom.status_code == 500
    assert boom.json()["detail"]["code"] == "internal_error"
    for leak in ("RuntimeError", "forced commit failure", "Traceback"):
        assert leak not in boom.text
    assert _counts(ctx) == before
    # The identical request is safe to retry, and still costs the true price.
    retry = ctx.post(
        "/api/v1/payments/orders",
        json=_order_body(hold_id, amount=AUTHORITATIVE, key="o-commit"),
    )
    assert retry.status_code == 201, retry.text
    assert retry.json()["amount_paise"] == AUTHORITATIVE
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(PaymentOrder)) == 1
        assert len(W.audit_rows(s, "tutoring.payment.order_created")) == 1


def test_a_provider_failure_leaves_no_order_audit_or_outbox_row(db_session, world):
    hold = W.place_hold(db_session, world, now=T0, key="h-provider")
    db_session.commit()
    before = Ledger.counts(db_session)
    with pytest.raises(errors.ProviderUnavailable) as refused:
        payments.create_order(
            db_session,
            hold_id=hold.id,
            student_user_id=world.student_id,
            idempotency_key="o-provider",
            provider=FailingPaymentAdapter(),
            now=T0,
        )
    assert refused.value.code == "PROVIDER_UNAVAILABLE"
    db_session.rollback()
    assert Ledger.counts(db_session) == before
    assert db_session.get(BookingHold, hold.id).status == "active"
    assert db_session.get(BookingHold, hold.id).price_paise == AUTHORITATIVE


# --------------------------------------------------------------------------- #
# 7. a valid signature is not a valid amount
# --------------------------------------------------------------------------- #


def test_a_correctly_signed_callback_with_the_wrong_amount_is_refused(ctx):
    """The defect's real payload: signature good, money wrong. Nothing applies."""
    hold_id = _hold(ctx, key="h-sig").json()["id"]
    order = ctx.post(
        "/api/v1/payments/orders",
        json=_order_body(hold_id, amount=AUTHORITATIVE, key="o-sig"),
    ).json()
    before = _counts(ctx)

    adapter = DeterministicPaymentAdapter()
    for tampered in (0, 1, AUTHORITATIVE - 1, AUTHORITATIVE + 1):
        raw, signature = adapter.make_event_body(
            provider_order_ref=order["provider_order_ref"],
            amount_paise=tampered,
            token=TOKEN_SUCCESS,
            event_id=f"evt-{tampered}",
        )
        # The signature is genuinely valid for this body: the adapter signs it.
        assert adapter.sign(raw) == signature
        refused = ctx.client.post(
            "/api/v1/payments/webhook", content=raw, headers={PAY_SIG: signature}
        )
        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"]["code"] == "AMOUNT_MISMATCH"
        assert refused.json()["detail"]["expected_paise"] == AUTHORITATIVE
        assert refused.json()["detail"]["observed_paise"] == tampered

    after = _counts(ctx)
    assert after == before, "a signed-but-wrong callback mutated the database"
    with ctx.fresh() as s:
        assert s.scalar(select(func.count()).select_from(PaymentEvent)) == 0
        assert s.scalar(select(func.count()).select_from(TutoringSession)) == 0
        assert s.get(PaymentOrder, uuid.UUID(order["id"])).status == "created"
        assert W.outbox_rows(s) == []
    # ...and the honest amount still books, so the guard is not just "refuse all".
    raw, signature = adapter.make_event_body(
        provider_order_ref=order["provider_order_ref"],
        amount_paise=AUTHORITATIVE,
        token=TOKEN_SUCCESS,
        event_id="evt-good",
    )
    ok = ctx.client.post(
        "/api/v1/payments/webhook", content=raw, headers={PAY_SIG: signature}
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["order_status"] == "paid"


def test_a_signed_capture_cannot_bless_an_order_that_drifted_from_the_snapshot(
    db_session, world
):
    """Both directions are checked: event vs order AND order vs hold snapshot.

    A row written past the service (a rogue UPDATE, a bad backfill, a future
    code path) must not become payable just because the provider signs a
    matching event.
    """
    hold = W.place_hold(db_session, world, now=T0, key="h-drift")
    adapter, order = W.open_order(db_session, world, hold, now=T0)
    db_session.commit()

    # Simulate the drift the schema alone cannot prevent.
    order.amount_paise = 1
    db_session.commit()
    before = Ledger.counts(db_session)

    with pytest.raises(errors.AmountMismatch) as refused:
        W.deliver_paid_event(db_session, adapter, order, amount_paise=1, now=T0)
    assert refused.value.code == "AMOUNT_MISMATCH"
    assert refused.value.extra["expected_paise"] == AUTHORITATIVE
    assert refused.value.extra["observed_paise"] == 1
    db_session.rollback()
    assert Ledger.counts(db_session) == before
    assert db_session.scalars(select(TutoringSession)).all() == []
    assert db_session.scalars(select(PaymentEvent)).all() == []
