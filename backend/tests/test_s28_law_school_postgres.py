"""QA-S28-01: real PostgreSQL consent persistence and create-once auditing.

Run against an explicitly supplied, migrated disposable PostgreSQL 16 database.
The existing PostgreSQL runtime gate invokes this module; the SQLite-only suite
skips it honestly. Tests add UUID-isolated synthetic rows, never rebuild tables
or erase append-only audit history. Actor claims are the existing test seam.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.db.models.audit import AuditEvent
from app.db.session import get_session
from app.models.registration import User
from app.models.wave1 import LawSchool, LawSchoolFollow, SavedLawSchool
from tests import apptemplate


@pytest.fixture(scope="module")
def pg_engine():
    raw = os.environ.get("S28_POSTGRES_TEST_URL")
    if not raw:
        pytest.skip("S28_POSTGRES_TEST_URL absent; SQLite cannot prove this regression")
    url = make_url(raw)
    assert url.drivername == "postgresql+psycopg"
    assert url.host in {"127.0.0.1", "localhost", "::1"} and not url.query
    assert set((url.database or "").split("_")) & {"qa", "test", "ci"}
    engine = create_engine(url, pool_size=6)
    with engine.connect() as conn:
        assert int(conn.scalar(text("SHOW server_version_num"))) // 10000 == 16
        assert conn.scalar(text("SELECT version_num FROM alembic_version"))
    yield engine
    engine.dispose()


def claims(uid):
    return {"X-Actor-Claims": json.dumps({"sub": str(uid), "roles": ["student"]})}


@pytest.fixture
def rig(pg_engine):
    failure = {"next_commit": False}

    class RequestSession(Session):
        def commit(self):
            if failure["next_commit"]:
                failure["next_commit"] = False
                # Send pending UPDATE/audit INSERT to PostgreSQL before failure;
                # the request dependency must roll back the whole transaction.
                self.flush()
                raise RuntimeError("synthetic S-28 commit failure")
            super().commit()

    factory = sessionmaker(pg_engine, expire_on_commit=False)
    request_factory = sessionmaker(pg_engine, class_=RequestSession)

    def sessions():
        with request_factory() as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    app, client = apptemplate.mounted_app(raise_server_exceptions=False)
    app.dependency_overrides[get_session] = sessions
    with factory() as session:
        owner = User(role="student", status="active")
        other = User(role="student", status="active")
        school = LawSchool(name="Synthetic S-28 QA School", slug=f"s28-{uuid.uuid4()}",
                           state="Delhi", institution_type="government")
        session.add_all([owner, other, school])
        session.commit()
        yield SimpleNamespace(app=app, client=client, factory=factory, engine=pg_engine,
                              uid=owner.id, other=other.id, school=school.id,
                              failure=failure)
    client.close()


def put(rig, action, notify=False, *, client=None, uid=None):
    kwargs = {"json": {"notify_opt_in": notify}} if action == "follow" else {}
    return (client or rig.client).put(
        f"/api/v1/student/law-schools/{rig.school}/{action}",
        headers=claims(uid or rig.uid), **kwargs)


def audit_count(rig, action):
    with rig.factory() as session:
        return session.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.actor_user_id == rig.uid, AuditEvent.resource_id == rig.school,
            AuditEvent.action == f"law_school.{action}"))


def persisted_consent(rig, uid=None):
    with rig.factory() as session:
        return session.scalar(select(LawSchoolFollow.notify_opt_in).where(
            LawSchoolFollow.user_id == (uid or rig.uid),
            LawSchoolFollow.school_id == rig.school))


@pytest.mark.parametrize("initial", [False, True], ids=["opt-in", "opt-out"])
def test_follow_preference_survives_reload_and_replays(rig, initial):
    assert put(rig, "follow", not initial, uid=rig.other).status_code == 200
    for preference in (initial, not initial, not initial, initial, initial):
        response = put(rig, "follow", preference)
        assert response.status_code == 200
        assert response.json() == {"followed": True, "notify_opt_in": preference}
        assert persisted_consent(rig) is preference
        assert persisted_consent(rig, rig.other) is not initial
        reload = rig.client.get("/api/v1/student/law-schools/followed", headers=claims(rig.uid))
        assert reload.status_code == 200
        assert [(item["id"], item["notify_opt_in"]) for item in reload.json()["items"]] == [
            (str(rig.school), preference)]
    assert audit_count(rig, "followed") == 1


@pytest.mark.parametrize("action,model,audit", [
    ("saved", SavedLawSchool, "saved"), ("follow", LawSchoolFollow, "followed")])
def test_replayed_put_audits_only_the_insert(rig, action, model, audit):
    for _ in range(3):
        assert put(rig, action).status_code == 200
    with rig.factory() as session:
        assert session.scalar(select(func.count()).select_from(model).where(
            model.user_id == rig.uid, model.school_id == rig.school)) == 1
    assert audit_count(rig, audit) == 1


@pytest.mark.parametrize("action,model,audit", [
    ("saved", SavedLawSchool, "saved"), ("follow", LawSchoolFollow, "followed")])
def test_parallel_put_has_one_row_and_one_audit(rig, action, model, audit):
    barrier = threading.Barrier(4)

    def meet_before_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith(f"INSERT INTO {model.__tablename__} "):
            barrier.wait(timeout=10)

    def writer(_):
        with TestClient(rig.app, raise_server_exceptions=False) as client:
            return put(rig, action, client=client).status_code

    event.listen(rig.engine, "before_cursor_execute", meet_before_insert)
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            assert list(pool.map(writer, range(4))) == [200] * 4
    finally:
        event.remove(rig.engine, "before_cursor_execute", meet_before_insert)
    with rig.factory() as session:
        assert session.scalar(select(func.count()).select_from(model).where(
            model.user_id == rig.uid, model.school_id == rig.school)) == 1
    assert audit_count(rig, audit) == 1


@pytest.mark.parametrize("action,model,audit", [
    ("saved", SavedLawSchool, "saved"), ("follow", LawSchoolFollow, "followed")])
def test_failed_insert_commit_rolls_back_row_and_audit_then_retry_succeeds(rig, action, model, audit):
    rig.failure["next_commit"] = True
    assert put(rig, action).status_code == 500
    with rig.factory() as session:
        assert session.scalar(select(func.count()).select_from(model).where(
            model.user_id == rig.uid, model.school_id == rig.school)) == 0
    assert audit_count(rig, audit) == 0
    assert put(rig, action).status_code == 200
    assert audit_count(rig, audit) == 1


def test_failed_consent_update_keeps_committed_choice_then_retry_succeeds(rig):
    assert put(rig, "follow", True).status_code == 200
    rig.failure["next_commit"] = True
    assert put(rig, "follow", False).status_code == 500
    assert persisted_consent(rig) is True
    assert audit_count(rig, "followed") == 1
    assert put(rig, "follow", False).status_code == 200
    assert persisted_consent(rig) is False
    assert audit_count(rig, "followed") == 1
