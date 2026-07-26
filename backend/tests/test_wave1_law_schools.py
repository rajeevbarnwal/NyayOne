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


def _claims(user_id, roles=("student",)):
    return {"X-Actor-Claims": json.dumps({"sub": str(user_id), "roles": list(roles)})}


@pytest.fixture()
def ctx():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
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
        assert seed_law_schools(s) == 12
        user = User(role="student", status="active")
        s.add(user)
        s.commit()
        uid = user.id
        ids = [str(x) for x in s.scalars(select(LawSchool.id).order_by(LawSchool.name)).all()]
    yield client, SessionLocal, uid, ids
    Base.metadata.drop_all(engine)


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
    Base.metadata.create_all(engine)
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
