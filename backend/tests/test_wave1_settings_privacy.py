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

# Test-suite plumbing: create_all-equivalent schema copies + a module-scoped
# route-materialised app (see tests/dbtemplate.py, tests/apptemplate.py).
from tests import apptemplate, dbtemplate

NOW = datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc)


def _claims(user_id, roles=("student",)):
    return {"X-Actor-Claims": json.dumps({"sub": str(user_id), "roles": list(roles)})}


@pytest.fixture(scope="module")
def _mounted():
    """App + client built and route-materialised once per module; ``ctx``
    re-points every dependency override per test. See tests/apptemplate.py."""
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
        reg = register_student(s, StudentRegisterRequest(
            first_name="Aditi", last_name="Nair", mobile="9876543210", dob="2004-03-14",
            consent={"accepted": True})).registration
        s.commit()
        uid, rid = reg.user_id, reg.id
    yield client, SessionLocal, uid, rid
    # Per-test engine: dispose() is the cleanup that matters. The old
    # drop_all here re-walked all 53 tables (~10 ms) to demolish a database
    # that was about to be discarded anyway.
    engine.dispose()


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
    assert up.status_code == 200
    # D1: legacy submissions map onto CANONICAL wire values
    assert up.json()["college"] == "National Law School of India University"
    assert up.json()["year_of_study"] == "3rd"
    with SessionLocal() as s:  # refresh-safe: fresh session sees the persisted value
        reg = s.get(StudentRegistration, rid)
        assert reg.institution_ref == "National Law School of India University"


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
    client.patch("/api/v1/student/profile", headers=_claims(uid), json={"college": "Other"})
    with SessionLocal() as s:
        evs = s.scalars(select(AuditEvent)).all()
        blob = "".join(str(e.after_state) for e in evs)
        assert any(e.action == "student.profile.update" for e in evs)
        assert "9876543210" not in blob and "Aditi" not in blob


# ===================== D1/D2/D3 remediation (QA 18c9fba) =====================
def test_d1_unsupported_college_and_year_rejected(ctx):
    client, SessionLocal, uid, rid = ctx
    h = _claims(uid)
    r1 = client.patch("/api/v1/student/profile", headers=h, json={"college": "Hogwarts School of Law"})
    r2 = client.patch("/api/v1/student/profile", headers=h, json={"year_of_study": "9th year"})
    assert r1.status_code == 422 and r2.status_code == 422


def test_d1_legacy_display_labels_map_to_canonical(ctx):
    client, SessionLocal, uid, rid = ctx
    h = _claims(uid)
    up = client.patch("/api/v1/student/profile", headers=h, json={
        "college": "National Law School of India University (NLSIU)", "year_of_study": "3rd year"})
    assert up.status_code == 200
    assert up.json()["college"] == "National Law School of India University"
    assert up.json()["year_of_study"] == "3rd"


def test_d1_returning_user_reads_canonical_from_legacy_rows(ctx):
    """Returning user: legacy DB values are mapped on READ without mutation."""
    client, SessionLocal, uid, rid = ctx
    from app.models.registration import StudentProfile
    with SessionLocal() as s:
        prof = s.scalar(select(StudentProfile).where(StudentProfile.registration_id == rid))
        if prof is None:
            prof = StudentProfile(registration_id=rid)
            s.add(prof)
        prof.college = "NLSIU"; prof.year_of_study = "3rd year"
        s.commit()
    g = client.get("/api/v1/student/profile", headers=_claims(uid))
    assert g.json()["college"] == "National Law School of India University"
    assert g.json()["year_of_study"] == "3rd"


def test_d1_open_save_without_change_preserves_values(ctx):
    client, SessionLocal, uid, rid = ctx
    h = _claims(uid)
    client.patch("/api/v1/student/profile", headers=h, json={
        "college": "National Law School of India University", "year_of_study": "3rd"})
    g1 = client.get("/api/v1/student/profile", headers=h).json()
    # simulate open-edit + save-without-modification (echo canonical values back)
    up = client.patch("/api/v1/student/profile", headers=h, json={
        "college": g1["college"], "year_of_study": g1["year_of_study"]})
    assert up.status_code == 200
    g2 = client.get("/api/v1/student/profile", headers=h).json()
    assert g2["college"] == g1["college"] and g2["year_of_study"] == g1["year_of_study"]


def test_d2_language_enum_fresh_default_and_persistence(ctx):
    client, SessionLocal, uid, rid = ctx
    h = _claims(uid)
    fresh = client.get("/api/v1/student/settings", headers=h).json()
    assert fresh["language"] == "en"  # wire code, not a display label
    ok = client.patch("/api/v1/student/settings", headers=h,
                      json={"language": "hi", "expected_version": fresh["version"]})
    assert ok.status_code == 200 and ok.json()["language"] == "hi"
    with SessionLocal() as s:  # returning user / reload: fresh session shows 'hi'
        row = s.scalar(select(UserSettings).where(UserSettings.user_id == uid))
        assert row.language == "hi"
    bad = client.patch("/api/v1/student/settings", headers=h,
                       json={"language": "English", "expected_version": ok.json()["version"]})
    assert bad.status_code == 422  # display labels are rejected at the API boundary


def test_d3_fresh_user_gets_all_three_privacy_defaults_false(ctx):
    client, SessionLocal, uid, rid = ctx
    fresh = client.get("/api/v1/student/settings", headers=_claims(uid)).json()
    assert sorted(p["kind"] for p in fresh["privacy"]) == ["analytics", "marketing", "share_partners"]
    assert all(p["enabled"] is False for p in fresh["privacy"])


def test_d3_toggle_each_kind_persists_and_survives_fresh_session(ctx):
    client, SessionLocal, uid, rid = ctx
    h = _claims(uid)
    v = client.get("/api/v1/student/settings", headers=h).json()["version"]
    for kind in ("analytics", "marketing", "share_partners"):
        r = client.patch("/api/v1/student/settings", headers=h,
                         json={"privacy": [{"kind": kind, "enabled": True}], "expected_version": v})
        assert r.status_code == 200
        v = r.json()["version"]
    final = client.get("/api/v1/student/settings", headers=h).json()
    assert all(p["enabled"] is True for p in final["privacy"]) and len(final["privacy"]) == 3
    with SessionLocal() as s:  # exactly one row per kind (uniqueness held on upsert)
        from app.models.wave1 import PrivacyPreference
        rows = s.scalars(select(PrivacyPreference).where(PrivacyPreference.user_id == uid)).all()
        assert len(rows) == 3 and all(r.enabled for r in rows)


def test_d3_stale_version_no_partial_privacy_write(ctx):
    client, SessionLocal, uid, rid = ctx
    h = _claims(uid)
    v = client.get("/api/v1/student/settings", headers=h).json()["version"]
    stale = client.patch("/api/v1/student/settings", headers=h,
                         json={"privacy": [{"kind": "analytics", "enabled": True}], "expected_version": v + 7})
    assert stale.status_code == 409
    now = client.get("/api/v1/student/settings", headers=h).json()
    assert all(p["enabled"] is False for p in now["privacy"])  # nothing landed


# ===================== F2 remediation (QA ceaf11f) ===========================
def test_f2_db_check_rejects_noncanonical_language(ctx):
    """The DATABASE (not just Pydantic) rejects non-canonical language values."""
    import pytest as _pytest
    from sqlalchemy.exc import IntegrityError
    client, SessionLocal, uid, rid = ctx
    for bad in ("English", "Hindi", "", "xx", "x" * 16):
        with SessionLocal() as s:
            from app.models.registration import User
            u = User(role="student", status="pending"); s.add(u); s.flush()
            s.add(UserSettings(user_id=u.id, language=bad))
            with _pytest.raises(IntegrityError):
                s.flush()
            s.rollback()
    with SessionLocal() as s:  # canonical codes accepted
        from app.models.registration import User
        u = User(role="student", status="pending"); s.add(u); s.flush()
        s.add(UserSettings(user_id=u.id, language="hi")); s.flush(); s.rollback()


def test_f2_migration_maps_legacy_and_guards_unknown(alembic_db):
    """Upgrade 0004 -> insert legacy rows -> upgrade head maps them; unknown
    values abort the migration with an explicit report.

    The two 0004 starting databases come from ``alembic_db`` (a copy of the
    session-scoped snapshot that a real alembic ``upgrade 0004_wave1_foundation``
    produced), instead of re-running that identical upgrade twice here. Every
    step this test actually asserts on — ``upgrade head``, ``downgrade
    0004_wave1_foundation``, the clean re-upgrade, and the must-fail upgrade on
    the unmapped value — is still a real ``python -m alembic`` invocation.
    """
    import os
    import subprocess
    import sys
    import uuid as _uuid

    def alembic(db, *args):
        env = {**os.environ, "DATABASE_URL": f"sqlite+pysqlite:///{db}"}
        return subprocess.run([sys.executable, "-m", "alembic", *args],
                              capture_output=True, text=True, env=env, cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]))

    import sqlite3

    def insert(db, lang):
        c = sqlite3.connect(db)
        uid_u, uid_s = _uuid.uuid4().hex, _uuid.uuid4().hex
        c.execute("INSERT INTO users (id, role, status, created_at, updated_at) VALUES (?, 'student', 'pending', datetime('now'), datetime('now'))", (uid_u,))
        c.execute("INSERT INTO user_settings (id, user_id, theme, language, notif_email, notif_sms, notif_updates, version, created_at, updated_at) VALUES (?, ?, 'system', ?, 1, 0, 1, 1, datetime('now'), datetime('now'))", (uid_s, uid_u, lang))
        c.commit(); c.close()

    # Case A: legacy labels map to canonical codes.
    db_a = alembic_db("0004_wave1_foundation", name="a")
    insert(db_a, "English"); insert(db_a, "हिन्दी (Hindi)")
    up = alembic(db_a, "upgrade", "head")
    assert up.returncode == 0, up.stderr[-500:]
    langs = sorted(r[0] for r in sqlite3.connect(db_a).execute("SELECT language FROM user_settings"))
    assert langs == ["en", "hi"]
    # Downgrade removes only the constraint; data survives; re-upgrade clean.
    # Target 0005's parent explicitly: later migrations must not make this
    # constraint downgrade assertion accidentally exercise another revision.
    assert alembic(db_a, "downgrade", "0004_wave1_foundation").returncode == 0
    assert sorted(r[0] for r in sqlite3.connect(db_a).execute("SELECT language FROM user_settings")) == ["en", "hi"]
    assert alembic(db_a, "upgrade", "head").returncode == 0

    # Case B: unknown value aborts loudly (no silent coercion).
    db_b = alembic_db("0004_wave1_foundation", name="b")
    insert(db_b, "Klingon")
    bad = alembic(db_b, "upgrade", "head")
    assert bad.returncode != 0 and "unmapped legacy language values" in (bad.stderr + bad.stdout)
