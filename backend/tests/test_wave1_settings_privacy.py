"""SAATHI-58 HTTP-boundary tests — settings/profile/DPDP (BE-01..BE-07 native)."""
from __future__ import annotations

import json
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.v1.router import api_router
from app.db.base import Base
from app.db.models.audit import AuditEvent
from app.db.session import get_session
from app.models.registration import RecoverySession, StudentRegistration
from app.models.wave1 import DataSubjectRequest, DeletionJob, ExportJob, UserSettings
from app.schemas.registration import StudentRegisterRequest
from app.services.registration_service import register_student

from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc)


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
        reg = register_student(s, StudentRegisterRequest(
            first_name="Aditi", last_name="Nair", mobile="9876543210", dob="2004-03-14",
            consent={"accepted": True})).registration
        s.commit()
        uid, rid = reg.user_id, reg.id
    yield client, SessionLocal, uid, rid
    Base.metadata.drop_all(engine)


def test_anonymous_and_wrong_role_rejected(ctx):
    client, *_ = ctx
    assert client.get("/api/v1/student/profile").status_code == 401
    assert client.get("/api/v1/student/settings", headers=_claims(uuid.uuid4(), ("lawyer",))).status_code == 403


def test_profile_get_patch_and_fresh_session(ctx):
    client, SessionLocal, uid, rid = ctx
    h = _claims(uid)
    p = client.get("/api/v1/student/profile", headers=h)
    assert p.status_code == 200 and p.json()["first_name"] == "Aditi"
    assert p.json()["masked_mobile"].endswith("3210") and "9876543210" not in p.json()["masked_mobile"]
    up = client.patch("/api/v1/student/profile", headers=h, json={"college": "NLSIU", "year_of_study": "3rd"})
    assert up.status_code == 200 and up.json()["college"] == "NLSIU"
    with SessionLocal() as s:  # refresh-safe: fresh session sees the persisted value
        reg = s.get(StudentRegistration, rid)
        assert reg.institution_ref == "NLSIU"


@pytest.mark.parametrize("bad", [{"college": "   "}, {"college": "x" * 161}, {"nickname": "no"}])
def test_profile_patch_validation(ctx, bad):
    client, SessionLocal, uid, rid = ctx
    assert client.patch("/api/v1/student/profile", headers=_claims(uid), json=bad).status_code == 422


def test_settings_roundtrip_version_conflict_and_privacy(ctx):
    client, SessionLocal, uid, rid = ctx
    h = _claims(uid)
    g = client.get("/api/v1/student/settings", headers=h)
    assert g.status_code == 200 and g.json()["theme"] == "system" and g.json()["version"] == 1
    ok = client.patch("/api/v1/student/settings", headers=h, json={
        "theme": "dark", "notif_sms": True, "privacy": [{"kind": "analytics", "enabled": True}],
        "expected_version": 1})
    assert ok.status_code == 200 and ok.json()["theme"] == "dark" and ok.json()["version"] == 2
    assert {"kind": "analytics", "enabled": True} in ok.json()["privacy"]
    stale = client.patch("/api/v1/student/settings", headers=h, json={"theme": "light", "expected_version": 1})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "settings_version_conflict"
    with SessionLocal() as s:
        row = s.scalar(select(UserSettings).where(UserSettings.user_id == uid))
        assert row.theme == "dark" and row.version == 2  # stale write did not land


@pytest.mark.parametrize("bad", [{"theme": "neon", "expected_version": 1}, {"language": "", "expected_version": 1},
                                 {"privacy": [{"kind": "spying", "enabled": True}], "expected_version": 1}])
def test_settings_unsupported_values(ctx, bad):
    client, SessionLocal, uid, rid = ctx
    assert client.patch("/api/v1/student/settings", headers=_claims(uid), json=bad).status_code == 422


def test_export_request_idempotent_and_status(ctx):
    client, SessionLocal, uid, rid = ctx
    h = {**_claims(uid), "Idempotency-Key": "exp-1"}
    a = client.post("/api/v1/student/privacy/export", headers=h)
    b = client.post("/api/v1/student/privacy/export", headers=h)
    assert a.status_code == b.status_code == 202
    assert a.json()["request_id"] == b.json()["request_id"]  # replay, same opaque id
    with SessionLocal() as s:
        assert len(s.scalars(select(DataSubjectRequest)).all()) == 1
        assert s.scalar(select(ExportJob)) is not None
    st = client.get(f"/api/v1/student/privacy/requests/{a.json()['request_id']}", headers=_claims(uid))
    assert st.status_code == 200 and st.json()["status"] == "pending" and st.json()["kind"] == "export"


def test_cross_user_request_lookup_uniform_404(ctx):
    client, SessionLocal, uid, rid = ctx
    r = client.post("/api/v1/student/privacy/export", headers=_claims(uid))
    opaque = r.json()["request_id"]
    with SessionLocal() as s:  # a second student user
        from app.models.registration import User
        other = User(role="student", status="pending"); s.add(other); s.commit(); other_id = other.id
    other_view = client.get(f"/api/v1/student/privacy/requests/{opaque}", headers=_claims(other_id))
    missing = client.get(f"/api/v1/student/privacy/requests/{uuid.uuid4().hex}", headers=_claims(other_id))
    assert other_view.status_code == missing.status_code == 404
    assert other_view.json() == missing.json()  # no existence leakage


def test_delete_requires_typed_confirmation_and_real_reauth(ctx):
    client, SessionLocal, uid, rid = ctx
    h = _claims(uid)
    bad = client.post("/api/v1/student/privacy/delete", headers=h,
                      json={"confirmation": "delete", "reauth_recovery_id": "x" * 32})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid_confirmation"
    noauth = client.post("/api/v1/student/privacy/delete", headers=h,
                         json={"confirmation": "DELETE", "reauth_recovery_id": uuid.uuid4().hex})
    assert noauth.status_code == 401 and noauth.json()["detail"]["code"] == "reauth_required"
    # Real server-side evidence: a VERIFIED recovery session owned by this user.
    with SessionLocal() as s:
        from app.core.crypto import keyed_hash
        rs = RecoverySession(opaque_id=uuid.uuid4().hex, lookup_hash=keyed_hash("9876543210"),
                             registration_id=rid, status="verified",
                             expires_at=NOW + timedelta(minutes=10))
        s.add(rs); s.commit(); rec_id = rs.opaque_id
    ok = client.post("/api/v1/student/privacy/delete", headers=h,
                     json={"confirmation": "DELETE", "reauth_recovery_id": rec_id})
    assert ok.status_code == 202
    with SessionLocal() as s:
        dsr = s.scalar(select(DataSubjectRequest).where(DataSubjectRequest.kind == "delete"))
        assert dsr.reauth_verified is True and dsr.confirmation_hash != "DELETE"
        assert s.scalar(select(DeletionJob).where(DeletionJob.request_id == dsr.id)) is not None
        rs2 = s.scalar(select(RecoverySession).where(RecoverySession.opaque_id == rec_id))
        assert rs2.status == "consumed"  # evidence is single-use
    replay = client.post("/api/v1/student/privacy/delete", headers=h,
                         json={"confirmation": "DELETE", "reauth_recovery_id": rec_id})
    assert replay.status_code == 401  # consumed evidence cannot be replayed


def test_audit_written_and_pii_free(ctx):
    client, SessionLocal, uid, rid = ctx
    client.patch("/api/v1/student/profile", headers=_claims(uid), json={"college": "NLSIU"})
    with SessionLocal() as s:
        evs = s.scalars(select(AuditEvent)).all()
        blob = "".join(str(e.after_state) for e in evs)
        assert any(e.action == "student.profile.update" for e in evs)
        assert "9876543210" not in blob and "Aditi" not in blob
