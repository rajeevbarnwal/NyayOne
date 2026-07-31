"""F1 — a FILE-BACKED SQLite database serving CONCURRENT HTTP requests.

This module reproduces, and then locks shut, the Wave 2 browser-gate runtime
failure. The gate boots the real backend with
``DATABASE_URL=sqlite+pysqlite:///<file>`` and then drives several browser
contexts at the same session, which produced:

* ``sqlite3.OperationalError: cannot commit - no transaction is active``
* ``Exception in ASGI application``
* ``GET /api/v1/tutoring/sessions/{id} -> 404 NOT_FOUND`` for a session that
  exists and is owned by the caller.

Two defects, both in ``app.db.session``, produced all three:

1. a FILE-BACKED database was wired to ``StaticPool``, so every concurrent
   request shared ONE DBAPI connection and therefore ONE transaction. Whoever
   committed first ended everybody's transaction; whoever rolled back first
   discarded everybody's uncommitted rows (that is the phantom 404);
2. the request had TWO transaction owners — the route committed and the
   ``get_session`` dependency committed again, unconditionally.

Everything below drives the REAL router through the REAL ``get_session``
dependency (deliberately NOT overridden) against a REAL file on disk, which is
the exact wiring ``scripts/wave2_tutoring_browser_gate.sh`` boots. Nothing here
serialises the workload, removes parallelism or retries a failed request.
"""
from __future__ import annotations

import logging
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.api.v1.router import api_router
from app.core import rate_limit
from app.core.exceptions import register_exception_handlers
from app.db import session as db_session
from app.db.base import Base
from app.models.wave2 import (
    BookingHold,
    PaymentOrder,
    TutoringSession,
    VideoSessionGrant,
)
from tests import wave2_helpers as H

#: Every string the sealed evidence contained, plus the two the manifest names.
#: A single sighting anywhere in the captured log stream fails the assertion.
FORBIDDEN = re.compile(
    r"cannot commit|no transaction is active|Exception in ASGI application"
    r"|IndexError|SQLite objects created in a thread",
    re.IGNORECASE,
)

CONCURRENCY = 12  # >= 8, the manifest's floor


# --------------------------------------------------------------------------- #
# Rig
# --------------------------------------------------------------------------- #


class _Wired:
    """The production app + a file-backed database + the actors one test needs."""

    def __init__(self, app, factory, engine, world, booked, db_file: Path) -> None:
        self.app = app
        self.factory = factory
        self.engine = engine
        self.world = world
        self.booked = booked
        self.db_file = db_file
        self.session_id = str(booked.tutoring_session.id)

    def read(self):
        return self.factory()


@pytest.fixture()
def wired(tmp_path, monkeypatch):
    """Point the PRODUCTION engine at a file and mount the PRODUCTION router.

    ``get_session`` is not overridden: this fixture exists precisely so the
    dependency under test is the one the server runs.
    """
    db_file = tmp_path / "wave2_concurrency.db"
    url = f"sqlite+pysqlite:///{db_file}"
    monkeypatch.setattr(db_session.settings, "database_url", url)
    db_session.get_engine.cache_clear()
    db_session.get_sessionmaker.cache_clear()

    engine = db_session.get_engine()
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

    now = datetime.now(timezone.utc).replace(microsecond=0)
    with factory() as seed:
        world = H.build_world(
            seed,
            now=now,
            slot_starts=tuple(
                now + timedelta(days=days, hours=1) for days in range(10, 18)
            ),
        )
        booked = H.book_session(seed, world, now=now)
        seed.commit()

    rate_limit.reset()
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    register_exception_handlers(app)
    assert H.materialise_routes(app) > 0  # warm the route table in ONE thread
    try:
        yield _Wired(app, factory, engine, world, booked, db_file)
    finally:
        rate_limit.reset()
        engine.dispose()
        db_session.get_engine.cache_clear()
        db_session.get_sessionmaker.cache_clear()


@pytest.fixture()
def captured_logs(caplog):
    """Everything the backend logs during a test, at DEBUG, from every thread."""
    caplog.set_level(logging.DEBUG, logger="")
    return caplog


def _fan_out(app, calls):
    """Run ``calls`` genuinely concurrently, each on its OWN HTTP client.

    One ``TestClient`` per worker (the pattern
    ``test_wave3_postgres_runtime.py`` already uses for PostgreSQL): sharing a
    single client would share Starlette's in-process portal and quietly
    serialise the very overlap under test.
    """
    started = threading.Barrier(len(calls))

    def run(call):
        method, path, headers, json_body = call
        with TestClient(app, raise_server_exceptions=False) as worker:
            started.wait(timeout=30)  # all workers hit the API in the same window
            return path, worker.request(method, path, headers=headers, json=json_body)

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return list(pool.map(run, calls))


def _assert_clean(results, captured_logs, *, allowed=(200, 201)):
    bad = [
        (path, r.status_code, r.text[:400])
        for path, r in results
        if r.status_code not in allowed
    ]
    assert not bad, f"unexpected responses: {bad}"
    hits = FORBIDDEN.findall(captured_logs.text)
    assert not hits, f"forbidden runtime errors in the backend log: {sorted(set(hits))}"


# --------------------------------------------------------------------------- #
# 1. The engine wiring itself
# --------------------------------------------------------------------------- #


def test_file_backed_sqlite_gets_independent_connections_not_staticpool(tmp_path):
    """A file-backed SQLite engine must NOT share one connection across requests.

    FAILED BEFORE THE FIX: ``_make_engine`` forced ``StaticPool`` for every
    SQLite URL and passed ``check_same_thread`` only for ``:memory:``.
    """
    url = f"sqlite+pysqlite:///{tmp_path/'f.db'}"
    args = db_session.sqlite_connect_args(url)
    assert args.get("check_same_thread") is False
    assert args.get("timeout") == db_session.SQLITE_BUSY_TIMEOUT_SECONDS

    engine = db_session._make_engine(url)
    try:
        assert not isinstance(engine.pool, StaticPool), (
            "a file-backed SQLite database serving concurrent HTTP requests "
            "must use an independent-connection pool, not StaticPool"
        )
        # Two checkouts at once really are two different connections.
        with engine.connect() as a, engine.connect() as b:
            assert a.connection.dbapi_connection is not b.connection.dbapi_connection
            # ... and the lock wait really is configured on the connection.
            assert (
                a.exec_driver_sql("PRAGMA busy_timeout").scalar()
                == db_session.SQLITE_BUSY_TIMEOUT_SECONDS * 1000
            )
        # A pooled connection may legitimately cross threads (check_same_thread).
        crossed: list[object] = []
        with engine.connect() as conn:
            worker = threading.Thread(
                target=lambda: crossed.append(
                    conn.exec_driver_sql("SELECT 1").scalar()
                )
            )
            worker.start()
            worker.join(timeout=10)
        assert crossed == [1]
    finally:
        engine.dispose()


def test_in_memory_sqlite_keeps_staticpool():
    """StaticPool stays where it is CORRECT: an in-memory, single-connection DB."""
    for url in ("sqlite+pysqlite://", "sqlite+pysqlite:///:memory:"):
        assert db_session.sqlite_connect_args(url) == {"check_same_thread": False}
        engine = db_session._make_engine(url)
        try:
            assert isinstance(engine.pool, StaticPool), url
            first = engine.raw_connection()
            second = engine.raw_connection()
            try:
                assert first.dbapi_connection is second.dbapi_connection, url
            finally:
                first.close()
                second.close()
        finally:
            engine.dispose()


# --------------------------------------------------------------------------- #
# 2. Transaction ownership
# --------------------------------------------------------------------------- #


def test_get_session_dependency_is_not_a_transaction_owner(tmp_path, monkeypatch):
    """The dependency NEVER commits; the handler is the single owner.

    FAILED BEFORE THE FIX: ``get_session`` committed unconditionally after the
    handler returned, so a handler that never declared its unit of work
    complete still had its rows written — two owners for one request.
    """
    url = f"sqlite+pysqlite:///{tmp_path/'owner.db'}"
    monkeypatch.setattr(db_session.settings, "database_url", url)
    db_session.get_engine.cache_clear()
    db_session.get_sessionmaker.cache_clear()
    engine = db_session.get_engine()
    Base.metadata.create_all(engine)

    probe = FastAPI()

    @probe.post("/uncommitted")
    def uncommitted(session: Session = Depends(db_session.get_session)) -> dict:
        session.add(
            H.TutorProfile(
                user_id=uuid.uuid4(),
                display_name="never committed",
                status="active",
            )
        )
        session.flush()  # the row reaches the DB but not a commit
        return {"ok": True}

    try:
        with TestClient(probe) as client:
            assert client.post("/uncommitted").status_code == 200
        with db_session.get_sessionmaker()() as check:
            assert (
                check.scalar(
                    select(func.count()).select_from(H.TutorProfile)
                )
                == 0
            ), "the dependency committed work the handler never committed"
    finally:
        engine.dispose()
        db_session.get_engine.cache_clear()
        db_session.get_sessionmaker.cache_clear()


def test_mutating_request_commits_exactly_once_and_a_failed_commit_rolls_back_once(
    wired, captured_logs
):
    """One commit per successful mutation; an injected commit failure -> ONE rollback.

    FAILED BEFORE THE FIX: the successful request committed TWICE (route, then
    dependency), which is the double ownership that produced
    ``cannot commit - no transaction is active`` once the two owners shared a
    connection.
    """
    calls: dict[str, int] = {"commit": 0, "rollback": 0}
    lock = threading.Lock()
    fail_next = {"on": False}

    class _CountingSession(Session):
        def commit(self):
            with lock:
                calls["commit"] += 1
                boom = fail_next["on"]
            if boom:
                raise RuntimeError("simulated commit failure")
            return super().commit()

        def rollback(self):
            with lock:
                calls["rollback"] += 1
            return super().rollback()

    counting = sessionmaker(
        bind=wired.engine,
        autoflush=False,
        expire_on_commit=False,
        class_=_CountingSession,
    )
    db_session.get_sessionmaker.cache_clear()
    original = db_session.get_sessionmaker

    def patched():
        return counting

    db_session.get_sessionmaker = patched  # type: ignore[assignment]
    headers = H.claims(wired.world.student_id)
    try:
        with TestClient(wired.app, raise_server_exceptions=False) as client:
            ok = client.post(
                f"/api/v1/tutoring/sessions/{wired.session_id}/join-credentials",
                headers=headers,
            )
            assert ok.status_code == 201, ok.text
            assert calls["commit"] == 1, (
                "a mutating request must have exactly ONE transaction owner; "
                f"saw {calls['commit']} commit() calls"
            )

            calls["commit"] = calls["rollback"] = 0
            fail_next["on"] = True
            with wired.read() as before:
                grants_before = before.scalar(
                    select(func.count()).select_from(VideoSessionGrant)
                )
            failed = client.post(
                f"/api/v1/tutoring/sessions/{wired.session_id}/join-credentials",
                headers=headers,
            )
            assert failed.status_code == 500
            assert calls["rollback"] == 1, (
                "an injected commit failure must roll back EXACTLY once; "
                f"saw {calls['rollback']}"
            )
            with wired.read() as after:
                assert (
                    after.scalar(select(func.count()).select_from(VideoSessionGrant))
                    == grants_before
                ), "a failed commit left a partial row behind"
    finally:
        fail_next["on"] = False
        db_session.get_sessionmaker = original  # type: ignore[assignment]
        db_session.get_sessionmaker.cache_clear()


# --------------------------------------------------------------------------- #
# 3. Concurrency against the file
# --------------------------------------------------------------------------- #


def test_twelve_concurrent_requests_against_a_file_backed_database(
    wired, captured_logs
):
    """>= 8 overlapping reads AND writes on one SQLite FILE, all successful.

    FAILED BEFORE THE FIX: the shared StaticPool connection produced
    ``cannot commit - no transaction is active`` / ``Exception in ASGI
    application`` and 500s.
    """
    student = H.claims(wired.world.student_id)
    tutor = H.claims(wired.world.tutor_user_id, roles=("tutor",))
    path = f"/api/v1/tutoring/sessions/{wired.session_id}"
    calls = []
    for index in range(CONCURRENCY):
        if index % 3 == 0:
            calls.append(("POST", f"{path}/join-credentials", student, None))
        elif index % 3 == 1:
            calls.append(("GET", path, student, None))
        else:
            calls.append(("GET", "/api/v1/tutoring/sessions", tutor, None))

    results = _fan_out(wired.app, calls)
    _assert_clean(results, captured_logs)

    # No request may report the caller's OWN session as missing.
    for req_path, response in results:
        assert response.status_code != 404, f"{req_path} -> 404 for an owned session"

    # No partial row and no duplicate: the booking flow is untouched by reads,
    # and each successful issue produced exactly one grant.
    issued = sum(1 for p, r in results if p.endswith("/join-credentials"))
    with wired.read() as check:
        assert check.scalar(select(func.count()).select_from(TutoringSession)) == 1
        assert check.scalar(select(func.count()).select_from(BookingHold)) == 1
        assert check.scalar(select(func.count()).select_from(PaymentOrder)) == 1
        grants = list(check.scalars(select(VideoSessionGrant)).all())
        assert len(grants) == issued
        assert all(g.token_hash for g in grants)  # never a half-written grant
        live = [g for g in grants if g.revoked_at is None]
        assert len(live) == 1, "exactly one credential may remain live"


def test_overlapping_session_reads_and_join_credential_creation(wired, captured_logs):
    """The exact stage-e / geo interleaving: read the session while minting a token.

    FAILED BEFORE THE FIX: a reader's ``rollback`` on the shared connection
    discarded the writer's uncommitted grant, and a writer's ``commit`` ended
    the reader's transaction — the pair that produced the phantom
    ``404 NOT_FOUND`` for an owned session.
    """
    student = H.claims(wired.world.student_id)
    path = f"/api/v1/tutoring/sessions/{wired.session_id}"
    calls = []
    for _ in range(5):
        calls.append(("GET", path, student, None))
        calls.append(("POST", f"{path}/join-credentials", student, None))

    results = _fan_out(wired.app, calls)
    _assert_clean(results, captured_logs)

    reads = [r for p, r in results if not p.endswith("/join-credentials")]
    assert len(reads) == 5
    for response in reads:
        assert response.status_code == 200, response.text
        assert response.json()["id"] == wired.session_id

    tokens = [
        r.json()["join_token"] for p, r in results if p.endswith("/join-credentials")
    ]
    assert len(tokens) == 5
    assert len(set(tokens)) == 5, "a duplicate join credential was issued"
    with wired.read() as check:
        hashes = list(check.scalars(select(VideoSessionGrant.token_hash)).all())
    assert len(hashes) == 5 and len(set(hashes)) == 5


def test_overlapping_saved_session_and_render_requests(wired, captured_logs):
    """The geometry contexts: several rooms rendering the same session at once.

    Each I2 measurement opens its own browser context, which lists the caller's
    sessions, reads the one it is rendering, reads the tutor behind it and mints
    a credential — all overlapping. FAILED BEFORE THE FIX for the same reason.
    """
    student = H.claims(wired.world.student_id)
    detail = f"/api/v1/tutoring/sessions/{wired.session_id}"
    tutor_path = f"/api/v1/tutors/{wired.world.tutor_id}"
    contexts = 5
    calls = []
    for _ in range(contexts):  # one "geometry context" = four overlapping requests
        calls.append(("GET", "/api/v1/tutoring/sessions", student, None))
        calls.append(("GET", detail, student, None))
        calls.append(("GET", tutor_path, student, None))
        calls.append(("POST", f"{detail}/join-credentials", student, None))

    results = _fan_out(wired.app, calls)
    _assert_clean(results, captured_logs)

    listings = [r for p, r in results if p == "/api/v1/tutoring/sessions"]
    assert len(listings) == contexts
    for response in listings:
        ids = [item["id"] for item in response.json()["items"]]
        assert ids == [wired.session_id], ids
    for path, response in results:
        if path == tutor_path:
            assert response.json()["id"] == str(wired.world.tutor_id)
        elif path == detail:
            assert response.json()["id"] == wired.session_id
    with wired.read() as check:
        assert check.scalar(select(func.count()).select_from(TutoringSession)) == 1
        assert (
            check.scalar(select(func.count()).select_from(VideoSessionGrant))
            == contexts
        )


# --------------------------------------------------------------------------- #
# 4. The PostgreSQL semantics this change must NOT regress
# --------------------------------------------------------------------------- #


def test_postgres_engine_wiring_is_unchanged():
    """A non-SQLite URL still gets the server pool — no SQLite arg leaks in."""
    engine = db_session._make_engine(
        "postgresql+psycopg://u:p@localhost:1/db"
    )
    try:
        assert not isinstance(engine.pool, StaticPool)
        assert engine.pool.size() == db_session.settings.db_pool_size
        assert engine.pool._max_overflow == db_session.settings.db_max_overflow
        assert engine.pool._pre_ping is True
    finally:
        engine.dispose()


def test_postgres_row_lock_and_concurrency_tests_are_still_present():
    """``FOR UPDATE`` semantics and the opt-in PG gate must survive this fix."""
    backend = Path(__file__).resolve().parents[1]
    pg_test = (backend / "tests" / "test_wave3_postgres_runtime.py").read_text()
    assert "def test_postgres_concurrent_idempotency_and_privacy(" in pg_test
    assert 'os.getenv("WAVE3_POSTGRES_TEST") != "1"' in pg_test
    assert "pytest.mark.skipif" in pg_test

    locked = {
        "app/api/v1/credentials.py",
        "app/services/otp_service.py",
        "app/services/law_school_service.py",
        "app/workers/credential_outbox_relay.py",
        "app/workers/otp_outbox_relay.py",
    }
    for relative in sorted(locked):
        source = (backend / relative).read_text()
        assert "with_for_update(" in source, relative
