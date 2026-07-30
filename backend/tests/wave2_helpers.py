"""Shared builders for the Wave 2 P2/P3 tests (SAATHI-123 / SAATHI-127).

Deliberately NOT named ``test_*`` so pytest does not collect it. Everything here
goes through the REAL services (holds, orders, verified webhooks) rather than
inserting rows by hand: a test that fabricates a "paid" session would prove
nothing about the frozen "only a verified payment creates a session" rule.

The second half of this module is the P3 HTTP harness — a production-style
session dependency, a claims header builder and a frozen clock — shared by every
``test_wave2_api*.py`` file so the boundary tests never re-implement it.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.db.models.audit import AuditEvent
from app.models.registration import User
from app.models.wave2 import TutorAvailabilitySlot, TutoringOutbox, TutorProfile
from app.services.providers.payment_provider import (
    DeterministicPaymentAdapter,
    TOKEN_SUCCESS,
)
from app.services.tutoring import booking, outbox_relay, payments, sessions

# Schema builder: a create_all-equivalent template copy (see tests/dbtemplate.py).
from tests import dbtemplate

#: Fixed anchor so every assertion about windows/DST is reproducible.
T0 = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)
AMOUNT_PAISE = 250_000  # Rs 2,500.00 as INTEGER paise. Never a float.


@dataclass
class World:
    """The actors + calendar one test needs."""

    student_id: uuid.UUID
    other_student_id: uuid.UUID
    tutor_user_id: uuid.UUID
    other_tutor_user_id: uuid.UUID
    admin_id: uuid.UUID
    tutor_id: uuid.UUID
    slots: tuple[uuid.UUID, ...]

    @property
    def slot_id(self) -> uuid.UUID:
        return self.slots[0]


def build_world(
    session: Session,
    *,
    now: datetime = T0,
    slot_starts: tuple[datetime, ...] | None = None,
    iana_timezone: str = "Asia/Kolkata",
) -> World:
    """One active tutor, two students, an admin and a handful of free slots."""
    student_id, other_student_id = uuid.uuid4(), uuid.uuid4()
    tutor_user_id, other_tutor_user_id = uuid.uuid4(), uuid.uuid4()
    admin_id = uuid.uuid4()
    for user_id, role in (
        (student_id, "student"),
        (other_student_id, "student"),
        (tutor_user_id, "lawyer"),
        (other_tutor_user_id, "lawyer"),
        (admin_id, "admin"),
    ):
        session.add(User(id=user_id, role=role, status="active"))
    tutor = TutorProfile(
        user_id=tutor_user_id,
        display_name="Adv. Meera Iyer",
        headline="Constitutional law",
        experience_years=11,
        verified_identity=True,
        verified_credentials=True,
        status="active",
    )
    session.add(tutor)
    session.flush()
    starts = slot_starts or tuple(
        now + timedelta(days=days, hours=1) for days in (10, 11, 12, 13)
    )
    slot_ids: list[uuid.UUID] = []
    for start in starts:
        slot = TutorAvailabilitySlot(
            tutor_id=tutor.id,
            start_utc=start,
            end_utc=start + timedelta(minutes=60),
            iana_timezone=iana_timezone,
            status="available",
        )
        session.add(slot)
        session.flush()
        slot_ids.append(slot.id)
    session.commit()
    return World(
        student_id=student_id,
        other_student_id=other_student_id,
        tutor_user_id=tutor_user_id,
        other_tutor_user_id=other_tutor_user_id,
        admin_id=admin_id,
        tutor_id=tutor.id,
        slots=tuple(slot_ids),
    )


@dataclass
class Booked:
    """A confirmed session plus everything the flow produced."""

    tutoring_session: object
    order: object
    hold: object
    adapter: DeterministicPaymentAdapter
    intents: list


def place_hold(
    session: Session,
    world: World,
    *,
    slot_id: uuid.UUID | None = None,
    student_user_id: uuid.UUID | None = None,
    now: datetime = T0,
    key: str | None = None,
):
    return booking.create_hold(
        session,
        slot_id=slot_id or world.slot_id,
        student_user_id=student_user_id or world.student_id,
        idempotency_key=key or f"hold-{uuid.uuid4()}",
        now=now,
    )


def open_order(
    session: Session,
    world: World,
    hold,
    *,
    adapter: DeterministicPaymentAdapter | None = None,
    amount_paise: int = AMOUNT_PAISE,
    now: datetime = T0,
    student_user_id: uuid.UUID | None = None,
):
    adapter = adapter or DeterministicPaymentAdapter()
    created = payments.create_order(
        session,
        hold_id=hold.id,
        student_user_id=student_user_id or world.student_id,
        amount_paise=amount_paise,
        idempotency_key=f"order-{hold.id}",
        provider=adapter,
        now=now,
    )
    return adapter, created.order


def deliver_paid_event(
    session: Session,
    adapter: DeterministicPaymentAdapter,
    order,
    *,
    amount_paise: int = AMOUNT_PAISE,
    now: datetime = T0,
    token: str = TOKEN_SUCCESS,
    event_id: str | None = None,
):
    raw, signature = adapter.make_event_body(
        provider_order_ref=order.provider_order_ref,
        amount_paise=amount_paise,
        token=token,
        event_id=event_id,
    )
    return payments.handle_event(
        session, signature=signature, raw_body=raw, provider=adapter, now=now
    )


def book_session(
    session: Session,
    world: World,
    *,
    slot_id: uuid.UUID | None = None,
    student_user_id: uuid.UUID | None = None,
    amount_paise: int = AMOUNT_PAISE,
    now: datetime = T0,
    commit: bool = True,
) -> Booked:
    """Hold -> order -> VERIFIED paid webhook -> confirmed session."""
    hold = place_hold(
        session, world, slot_id=slot_id, student_user_id=student_user_id, now=now
    )
    adapter, order = open_order(
        session,
        world,
        hold,
        amount_paise=amount_paise,
        now=now,
        student_user_id=student_user_id,
    )
    outcome = deliver_paid_event(
        session, adapter, order, amount_paise=amount_paise, now=now
    )
    if commit:
        session.commit()
    return Booked(
        tutoring_session=outcome.tutoring_session,
        order=order,
        hold=hold,
        adapter=adapter,
        intents=list(outcome.intents),
    )


def complete_and_confirm(
    session: Session,
    world: World,
    sess,
    *,
    now: datetime | None = None,
) -> datetime:
    """Record attendance after the scheduled end and have the student confirm it."""
    from app.services.tutoring import attendance

    after_end = now or (sessions._aware(sess.end_utc) + timedelta(minutes=5))
    attendance.record(
        session,
        sess.id,
        actor_user_id=world.tutor_user_id,
        actor_role="tutor",
        now=after_end,
    )
    attendance.confirm(
        session, sess.id, actor_user_id=world.student_id, now=after_end
    )
    session.commit()
    return after_end


# --------------------------------------------------------------------------- #
# Transaction / dispatch harness
# --------------------------------------------------------------------------- #


def commit_and_dispatch(
    session: Session,
    intents,
    dispatcher: outbox_relay.OutboxDispatcher,
    *,
    now: datetime | None = None,
) -> list[bool]:
    """Exactly what an endpoint does: commit FIRST, dispatch afterwards."""
    session.commit()
    return [
        outbox_relay.run_delivery(session, intent, dispatcher, now=now)
        for intent in intents
    ]


class failing_commit:
    """Context manager that makes the next ``session.commit()`` fail for real.

    Uses SQLAlchemy's ``before_commit`` hook, so the failure happens at commit
    time (after the flush) exactly as a disk/connection failure would — which is
    the only honest way to prove "a failed commit leaves no partial write and no
    outbox side effect".
    """

    def __init__(self, session: Session, *, exc: BaseException | None = None) -> None:
        self._session = session
        self._exc = exc or RuntimeError("simulated commit failure")

    def _boom(self, _session) -> None:
        raise self._exc

    def __enter__(self) -> "failing_commit":
        event.listen(self._session, "before_commit", self._boom)
        return self

    def __exit__(self, *_args) -> bool:
        event.remove(self._session, "before_commit", self._boom)
        return False


# --------------------------------------------------------------------------- #
# Assertion helpers
# --------------------------------------------------------------------------- #


def outbox_rows(
    session: Session, *, kind: str | None = None
) -> list[TutoringOutbox]:
    stmt = select(TutoringOutbox).order_by(
        TutoringOutbox.created_at, TutoringOutbox.id
    )
    if kind:
        stmt = stmt.where(TutoringOutbox.kind == kind)
    return list(session.scalars(stmt).all())


def audit_actions(session: Session) -> list[str]:
    return [
        row.action
        for row in session.scalars(
            select(AuditEvent).order_by(AuditEvent.created_at, AuditEvent.id)
        ).all()
    ]


def audit_rows(session: Session, action: str) -> list[AuditEvent]:
    return [
        row
        for row in session.scalars(select(AuditEvent)).all()
        if row.action == action
    ]


# --------------------------------------------------------------------------- #
# P3 HTTP harness (SAATHI-123/127 P3)
# --------------------------------------------------------------------------- #


def claims(user_id, roles=("student",)) -> dict[str, str]:
    """The dev claims header ``app.core.auth.get_actor_context`` reads."""
    return {"X-Actor-Claims": json.dumps({"sub": str(user_id), "roles": list(roles)})}


def memory_engine():
    """Shared in-memory SQLite with every Wave 2 table created."""
    from app.db.base import Base

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    dbtemplate.create_all(engine)
    return engine


def serialized_file_engine(tmp_path, name: str):
    """File-backed sqlite + NullPool so every THREAD owns a real connection.

    ``BEGIN IMMEDIATE`` makes sqlite serialize writers under the busy timeout the
    way PostgreSQL serializes on the unique index that decides the booking-hold
    race. Same rig as ``test_wave1_law_schools._serialized_file_engine``.
    """
    from sqlalchemy.pool import NullPool

    from app.db.base import Base

    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path}/{name}.db",
        poolclass=NullPool,
        connect_args={"timeout": 15},
    )

    @event.listens_for(engine, "connect")
    def _autocommit(dbapi_conn, _record):
        dbapi_conn.isolation_level = None  # SQLAlchemy issues explicit BEGIN

    @event.listens_for(engine, "begin")
    def _begin_immediate(conn):
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    dbtemplate.create_all(engine)
    return engine


def api_client(session_local, *, raise_server_exceptions: bool = True):
    """The mounted app + a client, wired to a PRODUCTION-style session dependency.

    The dependency commits on success and rolls back on any exception, exactly
    like ``app.db.session.get_session``, so a route that forgets to roll back
    before raising cannot pass by accident. The production exception handlers are
    registered so every assertion below is made against the REAL typed envelope.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.router import api_router
    from app.core.exceptions import register_exception_handlers
    from app.db.session import get_session

    def prod_session():
        s = session_local()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    register_exception_handlers(app)
    app.dependency_overrides[get_session] = prod_session
    return app, TestClient(app, raise_server_exceptions=raise_server_exceptions)


def materialise_routes(app_obj) -> int:
    """Resolve the app's effective route table ONCE, in the main thread.

    FastAPI >= 0.141 expands ``include_router`` lazily, so the first request to
    an app builds the effective route contexts. Warming that here keeps a
    concurrency assertion measuring the DB/idempotency boundary rather than
    first-request route construction. Returns the resolved count so a wiring
    regression (0 routes) fails loudly.
    """
    try:
        from fastapi.routing import iter_route_contexts  # FastAPI >= 0.141

        return len(list(iter_route_contexts(app_obj.routes)))
    except Exception:  # older FastAPI expands eagerly — nothing to warm
        return len(app_obj.routes)


def route_table(app_obj) -> set[tuple[str, str]]:
    """Every ``(method, path)`` the DEPLOYED app would actually serve.

    Read from the RESOLVED route contexts, not from ``app.routes``: FastAPI
    >= 0.141 expands ``include_router`` lazily, so ``app.routes`` holds the
    un-expanded router objects and would report an empty table for a correctly
    mounted router (and, worse, would report the same empty table for a router
    that was never mounted at all).
    """
    table: set[tuple[str, str]] = set()
    try:
        from fastapi.routing import iter_route_contexts

        contexts = list(iter_route_contexts(app_obj.routes))
    except Exception:  # pragma: no cover - older FastAPI expands eagerly
        contexts = list(app_obj.routes)
    for context in contexts:
        route = getattr(context, "route", context)
        path = getattr(context, "path", None) or getattr(route, "path", None)
        methods = getattr(context, "methods", None) or getattr(route, "methods", None)
        if not path:
            continue
        for method in methods or ("GET",):
            table.add((str(method), str(path)))
    return table


def route_paths(app_obj) -> set[str]:
    """Every path in the app's RESOLVED route table (not the router module)."""
    return {path for _method, path in route_table(app_obj)}


class Clock:
    """A mutable ``utcnow`` the HTTP boundary can be pinned to.

    The routes deliberately take no ``now`` parameter — injecting one would be a
    production-visible test hook. Pinning each service module's ``utcnow``
    instead lets a boundary test land EXACTLY on a policy edge (the 24h
    reschedule window, the inclusive scheduled end, the 7-day review deadline)
    instead of approximating it with a few minutes of slack.
    """

    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def set(self, at: datetime) -> None:
        self.at = at

    def shift(self, **kwargs) -> datetime:
        self.at = self.at + timedelta(**kwargs)
        return self.at


#: Every service module that owns its own ``utcnow`` (see each module's header).
_CLOCKED_MODULES = (
    "availability",
    "booking",
    "payments",
    "sessions",
    "attendance",
    "reviews",
    "reminders",
    "join_credentials",
)


def freeze_clock(monkeypatch, at: datetime) -> Clock:
    """Pin every tutoring service module's ``utcnow`` to one mutable instant."""
    import importlib

    clock = Clock(at)
    for name in _CLOCKED_MODULES:
        module = importlib.import_module(f"app.services.tutoring.{name}")
        monkeypatch.setattr(module, "utcnow", clock)
    return clock


class ApiCtx:
    """One assembled HTTP boundary: app, client, world, pinned clock, engine.

    ``get``/``post``/``patch``/``delete`` send AUTHENTICATED requests (defaulting
    to the world's student); ``ctx.client`` is the same client with no claims
    header, which is how every "unauthenticated" case is expressed.
    """

    def __init__(self, app, client, session_local, world, clock, engine) -> None:
        self.app = app
        self.client = client
        self.SessionLocal = session_local
        self.world = world
        self.clock = clock
        self.engine = engine

    def _headers(self, user, roles) -> dict[str, str]:
        return claims(user or self.world.student_id, roles)

    def get(self, path, *, user=None, roles=("student",), **kw):
        return self.client.get(path, headers=self._headers(user, roles), **kw)

    def post(self, path, *, user=None, roles=("student",), **kw):
        return self.client.post(path, headers=self._headers(user, roles), **kw)

    def patch(self, path, *, user=None, roles=("student",), **kw):
        return self.client.patch(path, headers=self._headers(user, roles), **kw)

    def delete(self, path, *, user=None, roles=("student",), **kw):
        return self.client.delete(path, headers=self._headers(user, roles), **kw)

    def fresh(self) -> Session:
        """A SEPARATE session, so durability claims are read from the database."""
        return self.SessionLocal()

    def teardown(self) -> None:
        from app.db.base import Base

        Base.metadata.drop_all(self.engine)


def truncate_all(engine) -> None:
    """Empty every table without dropping the schema.

    ``create_all``/``drop_all`` per test costs ~0.2s on the 40-table Wave 2
    schema, which is most of the runtime of a 200-case boundary matrix. Deleting
    rows in reverse dependency order is the same isolation for a fraction of the
    cost, and it keeps the FULL suite inside one invocation.
    """
    from app.db.base import Base

    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


def api_context(
    monkeypatch,
    *,
    now: datetime | None = None,
    session_class=Session,
    engine=None,
    slot_starts: tuple[datetime, ...] | None = None,
    iana_timezone: str = "Asia/Kolkata",
    raise_server_exceptions: bool = True,
) -> ApiCtx:
    """Build a STANDALONE P3 boundary fixture (its own engine, app and client).

    Use :class:`ApiRig` for a per-module rig instead when a whole file's worth of
    tests can share one schema; this entry point exists for the cases that need
    their own engine (the file-backed, thread-serialised booking race).
    """
    from app.core import rate_limit

    rate_limit.reset()
    at = now or T0
    engine = engine or memory_engine()
    session_local = sessionmaker(bind=engine, expire_on_commit=False, class_=session_class)
    clock = freeze_clock(monkeypatch, at)
    with session_local() as s:
        world = build_world(
            s, now=at, slot_starts=slot_starts, iana_timezone=iana_timezone
        )
    app, client = api_client(
        session_local, raise_server_exceptions=raise_server_exceptions
    )
    assert materialise_routes(app) > 0  # a wiring regression fails HERE, loudly
    return ApiCtx(app, client, session_local, world, clock, engine)


class ApiRig:
    """A MODULE-scoped engine + app + client; one :class:`ApiCtx` per test.

    The schema, the FastAPI app and the resolved route table are built once; each
    test gets an empty database and a freshly built world. Nothing leaks between
    tests because :func:`truncate_all` runs first and the pinned clock is
    re-installed by ``monkeypatch`` per test.
    """

    def __init__(self, *, session_class=Session, raise_server_exceptions: bool = True) -> None:
        self.engine = memory_engine()
        self.session_local = sessionmaker(
            bind=self.engine, expire_on_commit=False, class_=session_class
        )
        self.app, self.client = api_client(
            self.session_local, raise_server_exceptions=raise_server_exceptions
        )
        # The TestClient context is deliberately NOT held open for the module.
        # Holding it starts one long-lived anyio portal (and runs the app's
        # lifespan); measured against this file it made no reliable difference
        # either way on this container, so the simpler option wins.
        assert materialise_routes(self.app) > 0  # wiring regression fails loudly

    def context(
        self,
        monkeypatch,
        *,
        now: datetime | None = None,
        slot_starts: tuple[datetime, ...] | None = None,
        iana_timezone: str = "Asia/Kolkata",
    ) -> ApiCtx:
        from app.core import rate_limit

        rate_limit.reset()
        truncate_all(self.engine)
        at = now or T0
        clock = freeze_clock(monkeypatch, at)
        with self.session_local() as s:
            world = build_world(
                s, now=at, slot_starts=slot_starts, iana_timezone=iana_timezone
            )
        return ApiCtx(
            self.app, self.client, self.session_local, world, clock, self.engine
        )

    def close(self) -> None:
        from app.db.base import Base

        Base.metadata.drop_all(self.engine)
