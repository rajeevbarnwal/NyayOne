"""SAATHI-63 HTTP-boundary tests — search/detail/compare/save/follow.

Includes the Product-mandated compare cases (2, 4, 5, duplicate, replay,
concurrent additions) — decision 2026-07-27, SAATHI-63 comment 12569.
"""
from __future__ import annotations

import json
import threading
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.v1.router import api_router
from app.db.base import Base
from app.db.session import get_session
from app.models.registration import User
from app.models.wave1 import ComparisonItem, ComparisonSet, LawSchool, LawSchoolFollow, SavedLawSchool
from app.services.law_school_service import CompareError, add_comparison_item, seed_law_schools

# Test-suite plumbing: create_all-equivalent schema copies + a module-scoped
# route-materialised app (see tests/dbtemplate.py, tests/apptemplate.py).
from tests import apptemplate, dbtemplate


def _claims(user_id, roles=("student",)):
    return {"X-Actor-Claims": json.dumps({"sub": str(user_id), "roles": list(roles)})}


@pytest.fixture(scope="module")
def _mounted():
    """App + client built and route-materialised once per module; ``ctx``
    re-points every dependency override per test. See tests/apptemplate.py.
    (The thread-race tests below deliberately keep their own app.)"""
    return apptemplate.mounted_app()


@pytest.fixture()
def ctx(_mounted):
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    dbtemplate.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

    def prod_session():
        s = SessionLocal()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    app, client = _mounted
    apptemplate.fresh(app, client)
    app.dependency_overrides[get_session] = prod_session
    with SessionLocal() as s:
        assert seed_law_schools(s) == 12
        user = User(role="student", status="active")
        s.add(user)
        s.commit()
        uid = user.id
        ids = [str(x) for x in s.scalars(select(LawSchool.id).order_by(LawSchool.name)).all()]
    yield client, SessionLocal, uid, ids
    # Per-test engine: dispose() is the cleanup that matters. The old
    # drop_all here re-walked all 53 tables (~10 ms) to demolish a database
    # that was about to be discarded anyway.
    engine.dispose()


# ------------------------------- search (TC-63-01) ------------------------------
def test_list_filters_sort_pagination(ctx):
    client, SessionLocal, uid, ids = ctx
    r = client.get("/api/v1/law-schools", params={"state": "Maharashtra", "sort": "fees"})
    assert r.status_code == 200
    names = [i["state"] for i in r.json()["items"]]
    assert names and set(names) == {"Maharashtra"}
    assert r.json()["compare_max"] == 4
    r2 = client.get("/api/v1/law-schools", params={"q": "national law", "page_size": 2, "page": 1})
    assert r2.status_code == 200 and len(r2.json()["items"]) <= 2 and r2.json()["total"] >= 3
    r3 = client.get("/api/v1/law-schools", params={"degree": "LLM"})
    assert r3.status_code == 200 and r3.json()["total"] > 0
    r4 = client.get("/api/v1/law-schools", params={"entrance_exam": "CLAT", "fees_max": 250000})
    assert all(i["entrance_exam"] == "CLAT" for i in r4.json()["items"])


@pytest.mark.parametrize("params", [{"sort": "hackable"}, {"institution_type": "hogwarts"}, {"page": 0}, {"page_size": 999}])
def test_list_unsupported_values_422(ctx, params):
    client, *_ = ctx
    assert client.get("/api/v1/law-schools", params=params).status_code == 422


def test_empty_result_deterministic(ctx):
    client, *_ = ctx
    r = client.get("/api/v1/law-schools", params={"q": "zzz-no-such-school"})
    assert r.status_code == 200 and r.json()["items"] == [] and r.json()["total"] == 0


# ------------------------------- detail (TC-63-06) ------------------------------
def test_detail_sourced_facts(ctx):
    client, SessionLocal, uid, ids = ctx
    r = client.get(f"/api/v1/law-schools/{ids[0]}")
    assert r.status_code == 200
    d = r.json()
    assert d["programmes"] and d["facts"]
    for f in d["facts"]:  # every material fact carries its source + retrieved-at
        assert f["source_name"] and f["source_url"] and f["retrieved_at"]


def test_detail_missing_and_malformed(ctx):
    client, *_ = ctx
    assert client.get(f"/api/v1/law-schools/{uuid.uuid4()}").status_code == 404
    assert client.get("/api/v1/law-schools/not-a-uuid").status_code == 422


# ---------------------- compare (TC-63-03/04 + PO decision) ---------------------
def test_compare_two_ok(ctx):
    client, SessionLocal, uid, ids = ctx
    r = client.post("/api/v1/law-schools/compare", json={"school_ids": ids[:2]}, headers=_claims(uid))
    assert r.status_code == 200 and len(r.json()["items"]) == 2 and r.json()["compare_max"] == 4


def test_compare_four_ok(ctx):
    client, SessionLocal, uid, ids = ctx
    r = client.post("/api/v1/law-schools/compare", json={"school_ids": ids[:4]}, headers=_claims(uid))
    assert r.status_code == 200 and len(r.json()["items"]) == 4


def test_compare_five_limit_exceeded_no_partial_mutation(ctx):
    client, SessionLocal, uid, ids = ctx
    r = client.post("/api/v1/law-schools/compare", json={"school_ids": ids[:5]}, headers=_claims(uid))
    assert r.status_code == 422
    assert r.json()["detail"] == {"code": "COMPARE_LIMIT_EXCEEDED", "max_allowed": 4}
    with SessionLocal() as s:  # nothing persisted
        assert s.scalar(select(func.count()).select_from(ComparisonSet)) == 0
        assert s.scalar(select(func.count()).select_from(ComparisonItem)) == 0


def test_compare_one_below_min(ctx):
    client, SessionLocal, uid, ids = ctx
    r = client.post("/api/v1/law-schools/compare", json={"school_ids": ids[:1]}, headers=_claims(uid))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "COMPARE_MIN_NOT_MET"


def test_compare_duplicate_rejected(ctx):
    client, SessionLocal, uid, ids = ctx
    r = client.post("/api/v1/law-schools/compare", json={"school_ids": [ids[0], ids[0]]}, headers=_claims(uid))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "DUPLICATE_SCHOOL"


def test_compare_unknown_school_404(ctx):
    client, SessionLocal, uid, ids = ctx
    r = client.post("/api/v1/law-schools/compare", json={"school_ids": [ids[0], str(uuid.uuid4())]}, headers=_claims(uid))
    assert r.status_code == 404 and r.json()["detail"]["code"] == "school_not_found"


def test_compare_replay_no_duplicate_rows_per_set(ctx):
    client, SessionLocal, uid, ids = ctx
    a = client.post("/api/v1/law-schools/compare", json={"school_ids": ids[:2]}, headers=_claims(uid))
    b = client.post("/api/v1/law-schools/compare", json={"school_ids": ids[:2]}, headers=_claims(uid))
    assert a.status_code == b.status_code == 200
    with SessionLocal() as s:  # each set internally unique; no cross-set corruption
        for set_id in s.scalars(select(ComparisonSet.id)).all():
            items = s.scalars(select(ComparisonItem.school_id).where(ComparisonItem.set_id == set_id)).all()
            assert len(items) == len(set(items)) == 2


def test_concurrent_additions_cannot_exceed_limit(tmp_path):
    """PO rule: concurrent additions must not allow the configured limit to be
    exceeded. 6 threads with SEPARATE connections race to add distinct schools
    to one 2-item set. (File-backed DB so each thread has its own connection;
    the same invariant is re-proven on PostgreSQL by scripts/db_gate.sh.)"""
    from sqlalchemy.pool import NullPool
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path}/conc.db", poolclass=NullPool,
                           connect_args={"timeout": 15})
    dbtemplate.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    with SessionLocal() as s:
        seed_law_schools(s)
        cs = ComparisonSet(user_id=None)
        s.add(cs); s.flush()
        ids = [str(x) for x in s.scalars(select(LawSchool.id).order_by(LawSchool.name)).all()]
        add_comparison_item(s, cs.id, uuid.UUID(ids[0]))
        add_comparison_item(s, cs.id, uuid.UUID(ids[1]))
        s.commit(); set_id = cs.id
    outcomes = []

    def worker(school_id):
        with SessionLocal() as s:
            try:
                add_comparison_item(s, set_id, uuid.UUID(school_id))
                s.commit()
                outcomes.append("added")
            except CompareError as e:
                s.rollback()
                outcomes.append(e.code)
            except Exception as e:  # DB lock contention surfaces as retry-able error, never as >limit
                s.rollback()
                outcomes.append(type(e).__name__)

    threads = [threading.Thread(target=worker, args=(sid,)) for sid in ids[2:8]]
    [t.start() for t in threads]
    [t.join() for t in threads]
    with SessionLocal() as s:
        count = s.scalar(select(func.count()).select_from(ComparisonItem).where(ComparisonItem.set_id == set_id))
    assert count <= 4, f"limit exceeded: {count} items after concurrent adds ({outcomes})"
    assert outcomes.count("added") == count - 2, f"lost/phantom writes: {outcomes} vs count={count}"
    Base.metadata.drop_all(engine)


# ---------------------- saved / follow (TC-63-04/05/07) -------------------------
def test_save_follow_idempotent_and_persisted(ctx):
    client, SessionLocal, uid, ids = ctx
    h = _claims(uid)
    a = client.put(f"/api/v1/student/law-schools/{ids[0]}/saved", headers=h)
    b = client.put(f"/api/v1/student/law-schools/{ids[0]}/saved", headers=h)
    assert a.status_code == b.status_code == 200
    f1 = client.put(f"/api/v1/student/law-schools/{ids[1]}/follow", headers=h, json={"notify_opt_in": True})
    assert f1.status_code == 200 and f1.json()["notify_opt_in"] is True
    with SessionLocal() as s:  # fresh session: single rows, durable
        assert s.scalar(select(func.count()).select_from(SavedLawSchool)) == 1
        fl = s.scalar(select(LawSchoolFollow))
        assert fl.notify_opt_in is True
    sv = client.get("/api/v1/student/law-schools/saved", headers=h)
    fo = client.get("/api/v1/student/law-schools/followed", headers=h)
    assert len(sv.json()["items"]) == 1 and fo.json()["items"][0]["notify_opt_in"] is True
    d = client.delete(f"/api/v1/student/law-schools/{ids[0]}/saved", headers=h)
    d2 = client.delete(f"/api/v1/student/law-schools/{ids[0]}/saved", headers=h)  # idempotent delete
    assert d.status_code == d2.status_code == 200
    det = client.get(f"/api/v1/law-schools/{ids[1]}", headers=h)
    assert det.json()["followed"] is True and det.json()["saved"] is False


def test_saved_follow_auth_and_cross_user_scoping(ctx):
    client, SessionLocal, uid, ids = ctx
    assert client.put(f"/api/v1/student/law-schools/{ids[0]}/saved").status_code == 401
    assert client.put(f"/api/v1/student/law-schools/{ids[0]}/saved",
                      headers=_claims(uuid.uuid4(), ("lawyer",))).status_code == 403
    client.put(f"/api/v1/student/law-schools/{ids[0]}/saved", headers=_claims(uid))
    with SessionLocal() as s:
        other = User(role="student", status="active"); s.add(other); s.commit(); other_id = other.id
    r = client.get("/api/v1/student/law-schools/saved", headers=_claims(other_id))
    assert r.json()["items"] == []  # cross-user isolation
    assert client.put(f"/api/v1/student/law-schools/{uuid.uuid4()}/saved",
                      headers=_claims(uid)).status_code == 404


def test_no_pii_in_audit_for_school_actions(ctx):
    client, SessionLocal, uid, ids = ctx
    client.put(f"/api/v1/student/law-schools/{ids[0]}/follow", headers=_claims(uid), json={"notify_opt_in": True})
    from app.db.models.audit import AuditEvent
    with SessionLocal() as s:
        ev = s.scalar(select(AuditEvent).where(AuditEvent.action == "law_school.followed"))
        assert ev is not None and "mobile" not in str(ev.after_state)

# ------------- F1 (SAATHI-119) — parallel save/follow idempotency ----------------
def _serialized_file_engine(tmp_path, name):
    """File-backed sqlite + NullPool so every thread owns a REAL connection
    (test_concurrent_additions pattern), plus BEGIN IMMEDIATE so sqlite
    serializes writers under the busy timeout instead of deadlocking on lock
    upgrades — the way PostgreSQL serializes on the unique index for the
    production ON CONFLICT DO NOTHING path."""
    from sqlalchemy import event
    from sqlalchemy.pool import NullPool

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path}/{name}.db", poolclass=NullPool,
                           connect_args={"timeout": 15})

    @event.listens_for(engine, "connect")
    def _autocommit(dbapi_conn, _record):
        dbapi_conn.isolation_level = None  # SQLAlchemy issues explicit BEGIN

    @event.listens_for(engine, "begin")
    def _begin_immediate(conn):
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


def test_concurrent_follow_service_level_single_row_single_audit(tmp_path):
    """8 parallel threads race the idempotent follow insert on ONE
    (user, school): every caller succeeds logically, exactly 1 row persists
    and exactly 1 audit event is written (audit only on actual creation)."""
    from app.api.v1.law_schools import _idempotent_insert
    from app.db.models.audit import AuditEvent

    engine = _serialized_file_engine(tmp_path, "conc_follow_service")
    dbtemplate.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    with SessionLocal() as s:
        seed_law_schools(s)
        user = User(role="student", status="active")
        s.add(user)
        s.commit()
        uid = user.id
        school_id = s.scalars(select(LawSchool.id).order_by(LawSchool.name)).first()
    outcomes = []

    def worker():
        with SessionLocal() as s:
            try:
                created = _idempotent_insert(
                    s, LawSchoolFollow,
                    {"user_id": uid, "school_id": school_id, "notify_opt_in": False})
                if created:  # mirror of the endpoint: audit only on real creation
                    s.add(AuditEvent(actor_user_id=uid, actor_role="student",
                                     action="law_school.followed", resource_type="law_school",
                                     resource_id=school_id,
                                     after_state={"followed": True, "notify_opt_in": False}))
                s.commit()
                outcomes.append("ok")
            except Exception as exc:  # any escape = logical failure of a caller
                s.rollback()
                outcomes.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=worker) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert outcomes == ["ok"] * 8, outcomes
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(LawSchoolFollow)) == 1
        assert s.scalar(select(func.count()).select_from(AuditEvent)
                        .where(AuditEvent.action == "law_school.followed")) == 1
    Base.metadata.drop_all(engine)


def _materialise_routes(app_obj) -> int:
    """Resolve the app's effective route table ONCE, in the main thread.

    FastAPI >= 0.141 expands ``include_router`` lazily: the first request to an
    app builds the effective route contexts. Doing that here means the
    concurrency assertion below measures the DB/idempotency boundary only, and
    never first-request route construction. Returns the number of resolved
    routes so a wiring regression (0 routes) fails loudly.
    """
    try:
        from fastapi.routing import iter_route_contexts  # FastAPI >= 0.141

        return len(list(iter_route_contexts(app_obj.routes)))
    except Exception:  # older FastAPI expands eagerly — nothing to warm
        return len(app_obj.routes)


@pytest.mark.parametrize("surface", ["follow", "saved"])
def test_http_concurrent_put_all_200_one_row_one_audit(tmp_path, surface):
    """TC-63-04 remediation at the HTTP boundary: 8 parallel PUTs on one
    (user, school) via ThreadPoolExecutor against a production-style session
    → ALL return 200 (idempotent, never 500), one row, one audit row.

    The 8 callers are released by a ``threading.Barrier`` so they provably
    enter the endpoint together instead of relying on pool scheduling; the
    barrier carries a timeout so a lost racer fails the test instead of
    hanging. This STRENGTHENS the race (all eight must still be 200) — it does
    not relax it."""
    from concurrent.futures import ThreadPoolExecutor

    from app.db.models.audit import AuditEvent

    engine = _serialized_file_engine(tmp_path, f"conc_{surface}_http")
    dbtemplate.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

    def prod_session():
        s = SessionLocal()
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
    app.dependency_overrides[get_session] = prod_session
    client = TestClient(app)
    with SessionLocal() as s:
        seed_law_schools(s)
        user = User(role="student", status="active")
        s.add(user)
        s.commit()
        uid = user.id
        sid = str(s.scalars(select(LawSchool.id).order_by(LawSchool.name)).first())
    assert uuid.UUID(sid)  # a missing seed row must fail here, not as a request 404
    assert _materialise_routes(app) > 0
    h = _claims(uid)
    gate = threading.Barrier(8, timeout=20)

    def _put(_i):
        gate.wait()  # all eight callers hit the endpoint together
        return client.put(f"/api/v1/student/law-schools/{sid}/{surface}", headers=h)

    with ThreadPoolExecutor(max_workers=8) as pool:
        rs = list(pool.map(_put, range(8)))
    assert [r.status_code for r in rs] == [200] * 8, [(r.status_code, r.text) for r in rs]
    model = LawSchoolFollow if surface == "follow" else SavedLawSchool
    action = "law_school.followed" if surface == "follow" else "law_school.saved"
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(model)) == 1
        assert s.scalar(select(func.count()).select_from(AuditEvent)
                        .where(AuditEvent.action == action)) == 1
    Base.metadata.drop_all(engine)


# ------- F5 (TC-63-09) — executable commit-failure injection (HTTP boundary) -----
class _CommitFailOnce(Session):
    """Session whose commit() raises once while armed (mirror of
    test_http_contract._CommitFailSession) — a REAL, executable failure
    injection through the deployed HTTP app, not a citation."""

    arm = False

    def commit(self):  # type: ignore[override]
        if type(self).arm:
            type(self).arm = False
            raise RuntimeError("forced commit failure (injected)")
        return super().commit()


def _injection_ctx():
    from app.core.exceptions import register_exception_handlers

    engine = create_engine("sqlite+pysqlite:///:memory:",
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    dbtemplate.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=_CommitFailOnce)

    def prod_session():
        s = SessionLocal()
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
    register_exception_handlers(app)  # production typed 500 envelope
    app.dependency_overrides[get_session] = prod_session
    client = TestClient(app, raise_server_exceptions=False)
    with SessionLocal() as s:  # seeding happens BEFORE the fault is armed
        assert seed_law_schools(s) == 12
        user = User(role="student", status="active")
        s.add(user)
        s.commit()
        uid = user.id
        ids = [str(x) for x in s.scalars(select(LawSchool.id).order_by(LawSchool.name)).all()]
    return client, SessionLocal, uid, ids, engine


def test_commit_failure_put_follow_rolls_back_and_retries():
    """Forced commit failure on PUT follow → typed 500 internal_error envelope,
    ZERO partial rows in a fresh session, NO audit row; safe retry succeeds."""
    from app.db.models.audit import AuditEvent

    client, SessionLocal, uid, ids, engine = _injection_ctx()
    try:
        _CommitFailOnce.arm = True
        r = client.put(f"/api/v1/student/law-schools/{ids[0]}/follow",
                       headers=_claims(uid), json={"notify_opt_in": True})
        assert r.status_code == 500
        assert r.json()["detail"]["code"] == "internal_error"
        assert "RuntimeError" not in r.text  # no internal leak in the envelope
        with SessionLocal() as s:  # fresh session: nothing persisted
            assert s.scalar(select(func.count()).select_from(LawSchoolFollow)) == 0
            assert s.scalar(select(func.count()).select_from(AuditEvent)
                            .where(AuditEvent.action == "law_school.followed")) == 0
        r2 = client.put(f"/api/v1/student/law-schools/{ids[0]}/follow",
                        headers=_claims(uid), json={"notify_opt_in": True})
        assert r2.status_code == 200 and r2.json() == {"followed": True, "notify_opt_in": True}
        with SessionLocal() as s:
            assert s.scalar(select(func.count()).select_from(LawSchoolFollow)) == 1
            assert s.scalar(select(func.count()).select_from(AuditEvent)
                            .where(AuditEvent.action == "law_school.followed")) == 1
    finally:
        _CommitFailOnce.arm = False
        Base.metadata.drop_all(engine)


def test_commit_failure_post_compare_rolls_back_and_retries():
    """Forced commit failure on POST compare → typed 500 envelope, ZERO partial
    comparison rows in a fresh session; safe retry creates exactly one set."""
    client, SessionLocal, uid, ids, engine = _injection_ctx()
    try:
        _CommitFailOnce.arm = True
        r = client.post("/api/v1/law-schools/compare",
                        json={"school_ids": ids[:2]}, headers=_claims(uid))
        assert r.status_code == 500
        assert r.json()["detail"]["code"] == "internal_error"
        with SessionLocal() as s:  # fresh session: no partial set/items
            assert s.scalar(select(func.count()).select_from(ComparisonSet)) == 0
            assert s.scalar(select(func.count()).select_from(ComparisonItem)) == 0
        r2 = client.post("/api/v1/law-schools/compare",
                         json={"school_ids": ids[:2]}, headers=_claims(uid))
        assert r2.status_code == 200 and len(r2.json()["items"]) == 2
        with SessionLocal() as s:
            assert s.scalar(select(func.count()).select_from(ComparisonSet)) == 1
            assert s.scalar(select(func.count()).select_from(ComparisonItem)) == 2
    finally:
        _CommitFailOnce.arm = False
        Base.metadata.drop_all(engine)



# ------------- fixture contract parity (SAATHI-121 visual oracle) ---------------
def test_seed_facts_match_shared_fixture_contract(ctx):
    """The seeded law_school_facts MUST byte-match the shared visual fixture
    contract (frontend/scripts/lawschool_fixture_contract.json) — the single
    source consumed by the developed E2E harness AND the Option C+ reference
    renderer. Strengthened (not weakened) per SAATHI-121 oracle closure."""
    import json
    from pathlib import Path

    client, SessionLocal, uid, ids = ctx
    contract_path = Path(__file__).resolve().parents[2] / "frontend" / "scripts" / "lawschool_fixture_contract.json"
    contract = json.loads(contract_path.read_text())
    assert len(contract["catalog"]) == 12  # frozen catalog size

    listing = client.get("/api/v1/law-schools", params={"sort": "name", "page_size": 50}).json()
    by_slug = {i["slug"]: i for i in listing["items"]}
    assert listing["total"] == 12
    assert sorted(by_slug) == sorted(s["slug"] for s in contract["catalog"])

    for cs in contract["catalog"]:
        detail = client.get(f"/api/v1/law-schools/{by_slug[cs['slug']]['id']}").json()
        rows = [(f["key"], f["value"]) for f in detail["facts"]]
        expected = [
            ("established", f"{cs['established']} (sample)"),
            ("location", f"{cs['city']}, {cs['state']} (sample)"),
            ("intake", f"{cs['seats']} seats (sample)"),
            ("hostel", f"{cs['hostel']} (sample)"),
            ("legal_aid_clinics", f"{cs['legalAidClinics']} clinics (sample)"),
            ("moot_teams", f"{cs['mootTeams']} teams (sample)"),
        ]
        assert sorted(rows) == sorted(expected), cs["slug"]
        # sample labelling is mandatory — a sample value must never read as a
        # verified claim
        assert all(v.endswith("(sample)") for _, v in rows)
        assert detail["entrance_exam"] == cs["entranceExam"]
        assert detail["fees_min"] == cs["feesMin"] and detail["fees_max"] == cs["feesMax"]
        assert detail["nirf_rank"] == cs["nirfRank"]


# -------- SAATHI-119 (F2) — approved 13-row S-29 compare projection ------------
# The compare endpoint must deterministically return everything the approved
# 13-row schema renders: 7 catalogue columns (state, institution_type,
# accreditation, entrance_exam, fees_min+fees_max, nirf_rank, programmes) plus
# the six 0006-backfilled facts with source/freshness — for EVERY compared
# school, in a stable order.
APPROVED_FACT_KEYS_SORTED = ["established", "location", "intake", "hostel", "legal_aid_clinics", "moot_teams"]  # approved SEMANTIC order (QA fb8dbc1)
APPROVED_SUMMARY_ROW_FIELDS = [
    "state", "institution_type", "accreditation", "entrance_exam",
    "fees_min", "fees_max", "nirf_rank", "programmes",
]


def _thirteen_row_keys(item: dict) -> list[str]:
    """The 13 approved S-29 row keys derivable from one compare item."""
    return (
        ["state", "institution_type", "accreditation", "entrance_exam", "fees",
         "nirf_rank", "programmes"]
        + [f["key"] for f in item["facts"]]
    )


@pytest.mark.parametrize("n", [2, 4])
def test_compare_returns_13_row_projection(ctx, n):
    client, SessionLocal, uid, ids = ctx
    r = client.post("/api/v1/law-schools/compare", json={"school_ids": ids[:n]}, headers=_claims(uid))
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == n
    for item in items:
        for field in APPROVED_SUMMARY_ROW_FIELDS:
            assert field in item, f"missing summary field {field}"
        # exactly the six approved facts, deterministically key-ordered
        fact_keys = [f["key"] for f in item["facts"]]
        assert fact_keys == APPROVED_FACT_KEYS_SORTED
        for f in item["facts"]:
            assert f["value"].endswith("(sample)")
            assert f["source_name"] and f["source_url"] and f["retrieved_at"]
        row_keys = _thirteen_row_keys(item)
        assert len(row_keys) == 13 and len(set(row_keys)) == 13
        assert item["programmes"] == sorted(item["programmes"], key=lambda p: p["degree"])


def test_compare_projection_deterministic_across_calls(ctx):
    client, SessionLocal, uid, ids = ctx
    a = client.post("/api/v1/law-schools/compare", json={"school_ids": ids[:4]}, headers=_claims(uid))
    b = client.post("/api/v1/law-schools/compare", json={"school_ids": ids[:4]}, headers=_claims(uid))
    assert a.status_code == b.status_code == 200
    strip = lambda payload: [  # noqa: E731 - local shaping helper
        {k: v for k, v in item.items() if k != "id"} for item in payload["items"]
    ]
    assert strip(a.json()) == strip(b.json())  # identical order + content


def test_detail_facts_deterministically_ordered(ctx):
    client, SessionLocal, uid, ids = ctx
    r1 = client.get(f"/api/v1/law-schools/{ids[0]}")
    r2 = client.get(f"/api/v1/law-schools/{ids[0]}")
    keys1 = [f["key"] for f in r1.json()["facts"]]
    keys2 = [f["key"] for f in r2.json()["facts"]]
    assert keys1 == keys2 == APPROVED_FACT_KEYS_SORTED


# ------- approved semantic fact order (QA fb8dbc1 blocker) -------------------
def test_s28_detail_facts_in_approved_semantic_order(ctx):
    client, SessionLocal, uid, ids = ctx
    from app.api.v1.law_schools import FACT_SEMANTIC_ORDER
    r = client.get(f"/api/v1/law-schools/{ids[0]}")
    assert r.status_code == 200
    keys = [f["key"] for f in r.json()["facts"] if f["key"] in FACT_SEMANTIC_ORDER]
    assert keys == list(FACT_SEMANTIC_ORDER), keys  # exact approved order, not alphabetical


def test_compare_facts_semantic_order_2_and_4(ctx):
    client, SessionLocal, uid, ids = ctx
    from app.api.v1.law_schools import FACT_SEMANTIC_ORDER
    for n in (2, 4):
        r = client.post("/api/v1/law-schools/compare", json={"school_ids": ids[:n]}, headers=_claims(uid))
        assert r.status_code == 200
        for item in r.json()["items"]:
            keys = [f["key"] for f in item["facts"] if f["key"] in FACT_SEMANTIC_ORDER]
            assert keys == list(FACT_SEMANTIC_ORDER)
