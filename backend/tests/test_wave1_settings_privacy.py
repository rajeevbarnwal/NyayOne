"""SAATHI-58 HTTP-boundary tests — settings/profile/DPDP (BE-01..BE-07 native)."""
from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.config import settings
from app.db.models.audit import AuditEvent
from app.db.session import get_session
from app.models.registration import OtpFlow, StudentRegistration, User
from app.models.wave1 import DataSubjectRequest, DeletionJob, ExportJob, UserSettings
from app.schemas.registration import StudentRegisterRequest
from app.services.registration_service import register_student
from app.services import otp_authority, otp_flow_service, otp_service

from datetime import datetime, timezone

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
            terms_accepted=True, terms_version="terms.v1",
            privacy_notice_acknowledged=True,
            privacy_notice_version="privacy.v1")).registration
        reg.status = "active"
        s.get(User, reg.user_id).status = "active"
        s.commit()
        uid, rid = reg.user_id, reg.id
    yield client, SessionLocal, uid, rid
    # Per-test engine: dispose() is the cleanup that matters. The old
    # drop_all here re-walked all 53 tables (~10 ms) to demolish a database
    # that was about to be discarded anyway.
    engine.dispose()


def _personal(version=1):
    return {
        "expected_profile_version": version,
        "first_name": "Aditi",
        "middle_name": None,
        "last_name": "Nair",
        "date_of_birth": "2004-03-14",
        "preferred_language": "en",
        "city": "Bengaluru",
        "pronouns": None,
    }


def _academic(version=2, **overrides):
    payload = {
        "expected_profile_version": version,
        "college": "National Law School of India University",
        "year_of_study": "3rd",
        "enrolment_number": "KA/1234/2023",
        "institutional_email": None,
        "bar_enrolment_number": None,
    }
    payload.update(overrides)
    return payload


def _complete_personal(client, uid):
    response = client.patch(
        "/api/v1/student/profile/personal",
        headers={**_claims(uid), "Origin": settings.cors_origins[0]},
        json=_personal(),
    )
    assert response.status_code == 200
    return response.json()


def test_anonymous_and_wrong_role_rejected(ctx):
    client, *_ = ctx
    assert client.get("/api/v1/student/profile").status_code == 401
    assert client.get("/api/v1/student/settings", headers=_claims(uuid.uuid4(), ("lawyer",))).status_code == 403


def test_profile_get_patch_and_fresh_session(ctx):
    client, SessionLocal, uid, rid = ctx
    h = {**_claims(uid), "Origin": settings.cors_origins[0]}
    p = client.get("/api/v1/student/profile", headers=h)
    assert p.status_code == 200
    assert p.json()["profile"]["personal"]["first_name"] == "Aditi"
    assert "masked_mobile" not in p.json()
    _complete_personal(client, uid)
    up = client.patch(
        "/api/v1/student/profile/academic", headers=h, json=_academic()
    )
    assert up.status_code == 200
    assert up.json()["profile"]["academic"]["college"] == "National Law School of India University"
    assert up.json()["profile"]["academic"]["year_of_study"] == "3rd"
    with SessionLocal() as s:  # refresh-safe: fresh session sees the persisted value
        reg = s.get(StudentRegistration, rid)
        assert reg.institution_ref == "National Law School of India University"


@pytest.mark.parametrize("bad", [{"college": "x" * 161}, {"nickname": "no"}])
def test_profile_patch_validation(ctx, bad):
    client, SessionLocal, uid, rid = ctx
    _complete_personal(client, uid)
    assert client.patch(
        "/api/v1/student/profile/academic",
        headers=_claims(uid),
        json={**_academic(), **bad},
    ).status_code == 422


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
        other = User(role="student", status="pending")
        s.add(other)
        s.commit()
        other_id = other.id
    other_view = client.get(f"/api/v1/student/privacy/requests/{opaque}", headers=_claims(other_id))
    missing = client.get(f"/api/v1/student/privacy/requests/{uuid.uuid4().hex}", headers=_claims(other_id))
    assert other_view.status_code == missing.status_code == 404
    assert other_view.json() == missing.json()  # no existence leakage


def test_delete_requires_typed_confirmation_and_real_reauth(ctx):
    client, SessionLocal, uid, rid = ctx
    h = {**_claims(uid), "Origin": settings.cors_origins[0]}
    bad = client.post("/api/v1/student/privacy/delete", headers=h,
                      json={"confirmation": "delete"})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid_confirmation"
    noauth = client.post("/api/v1/student/privacy/delete", headers=h,
                         json={"confirmation": "DELETE"})
    assert noauth.status_code == 401 and noauth.json()["detail"]["code"] == "reauth_required"
    # Real server-side evidence: a VERIFIED HttpOnly recovery flow owned by
    # this registration. The raw proof exists only in the browser cookie.
    raw_token = otp_flow_service.random_flow_token()
    with SessionLocal() as s:
        registration = s.get(StudentRegistration, rid)
        assert registration is not None
        registration.status = "active"
        now = datetime.now(timezone.utc)
        authority = otp_authority.lock_or_create_registration_authority(
            s, registration, "recovery", now
        )
        challenge, _ = otp_service.issue_challenge(
            s,
            registration.id,
            now,
            purpose="recovery",
            destination="9876543210",
        )
        _, flow = otp_flow_service.create_flow(
            s,
            authority,
            now=now,
            destination="9876543210",
            challenge=challenge,
            registration_id=rid,
            raw_token=raw_token,
        )
        otp_flow_service.mark_recovery_verified(flow, now=now)
        s.commit()
    client.cookies.set(
        settings.otp_flow_cookie_name,
        raw_token,
        path="/api/v1",
    )
    ok = client.post("/api/v1/student/privacy/delete", headers=h,
                     json={"confirmation": "DELETE"})
    assert ok.status_code == 202
    with SessionLocal() as s:
        dsr = s.scalar(select(DataSubjectRequest).where(DataSubjectRequest.kind == "delete"))
        assert dsr.reauth_verified is True and dsr.confirmation_hash != "DELETE"
        job = s.scalar(select(DeletionJob).where(DeletionJob.request_id == dsr.id))
        assert job is not None and job.mode == settings.retention_mode
        flow = s.scalar(select(OtpFlow))
        assert flow is not None and flow.state == "consumed"
        assert s.get(StudentRegistration, rid).status == "suspended"
        assert s.get(User, uid).status == "suspended"
    deleted_cookies = ok.headers.get_list("set-cookie")
    assert len(deleted_cookies) == 3
    root_auth = [
        header
        for header in deleted_cookies
        if header.startswith(f"{settings.auth_session_cookie_name}=")
        and "Path=/;" in header
    ]
    legacy_auth = [
        header
        for header in deleted_cookies
        if header.startswith(f"{settings.auth_session_cookie_name}=")
        and "Path=/api/v1" in header
    ]
    flow_clear = [
        header
        for header in deleted_cookies
        if header.startswith(f"{settings.otp_flow_cookie_name}=")
    ]
    assert len(root_auth) == len(legacy_auth) == len(flow_clear) == 1
    assert all(
        token in root_auth[0]
        for token in ("Max-Age=0", "Path=/", "HttpOnly", "SameSite=lax")
    )
    assert all(
        token in legacy_auth[0]
        for token in (
            "Max-Age=0",
            "Path=/api/v1",
            "HttpOnly",
            "SameSite=strict",
        )
    )
    assert all(
        token in flow_clear[0]
        for token in (
            "Max-Age=0",
            "Path=/api/v1",
            "HttpOnly",
            "SameSite=strict",
        )
    )
    assert not any(
        header.startswith(f"{settings.auth_session_cookie_name}=")
        and "Domain=" in header
        for header in deleted_cookies
    )
    replay = client.post("/api/v1/student/privacy/delete", headers=h,
                         json={"confirmation": "DELETE"})
    assert replay.status_code == 401  # consumed evidence cannot be replayed


def test_audit_written_and_pii_free(ctx):
    client, SessionLocal, uid, rid = ctx
    _complete_personal(client, uid)
    assert client.patch(
        "/api/v1/student/profile/academic",
        headers=_claims(uid),
        json=_academic(college="Other"),
    ).status_code == 200
    with SessionLocal() as s:
        evs = s.scalars(select(AuditEvent)).all()
        blob = "".join(str(e.after_state) for e in evs)
        assert any(e.action == "student.profile.section_updated" for e in evs)
        assert "9876543210" not in blob and "Aditi" not in blob


# ===================== D1/D2/D3 remediation (QA 18c9fba) =====================
def test_d1_unsupported_college_and_year_rejected(ctx):
    client, SessionLocal, uid, rid = ctx
    h = _claims(uid)
    _complete_personal(client, uid)
    r1 = client.patch(
        "/api/v1/student/profile/academic",
        headers=h,
        json=_academic(college="Hogwarts School of Law"),
    )
    r2 = client.patch(
        "/api/v1/student/profile/academic",
        headers=h,
        json=_academic(year_of_study="9th year"),
    )
    assert r1.status_code == 422 and r2.status_code == 422


def test_d1_legacy_display_labels_map_to_canonical(ctx):
    client, SessionLocal, uid, rid = ctx
    h = _claims(uid)
    _complete_personal(client, uid)
    up = client.patch(
        "/api/v1/student/profile/academic",
        headers=h,
        json=_academic(
            college="National Law School of India University (NLSIU)",
            year_of_study="3rd year",
        ),
    )
    assert up.status_code == 200
    assert up.json()["profile"]["academic"]["college"] == "National Law School of India University"
    assert up.json()["profile"]["academic"]["year_of_study"] == "3rd"


def test_d1_returning_user_reads_canonical_from_legacy_rows(ctx):
    """Returning user: legacy DB values are mapped on READ without mutation."""
    client, SessionLocal, uid, rid = ctx
    from app.models.registration import StudentProfile
    with SessionLocal() as s:
        prof = s.scalar(select(StudentProfile).where(StudentProfile.registration_id == rid))
        if prof is None:
            prof = StudentProfile(registration_id=rid)
            s.add(prof)
        prof.college = "NLSIU"
        prof.year_of_study = "3rd year"
        s.commit()
    g = client.get("/api/v1/student/profile", headers=_claims(uid))
    assert (
        g.json()["profile"]["academic"]["college"]
        == "National Law School of India University"
    )
    assert g.json()["profile"]["academic"]["year_of_study"] == "3rd"


def test_d1_open_save_without_change_preserves_values(ctx):
    client, SessionLocal, uid, rid = ctx
    h = _claims(uid)
    _complete_personal(client, uid)
    client.patch("/api/v1/student/profile/academic", headers=h, json=_academic())
    g1 = client.get("/api/v1/student/profile", headers=h).json()
    # simulate open-edit + save-without-modification (echo canonical values back)
    up = client.patch(
        "/api/v1/student/profile/academic",
        headers=h,
        json={
            **g1["profile"]["academic"],
            "expected_profile_version": g1["profile_version"],
        },
    )
    assert up.status_code == 200
    g2 = client.get("/api/v1/student/profile", headers=h).json()
    assert g2["profile"]["academic"] == g1["profile"]["academic"]


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
            u = User(role="student", status="pending")
            s.add(u)
            s.flush()
            s.add(UserSettings(user_id=u.id, language=bad))
            with _pytest.raises(IntegrityError):
                s.flush()
            s.rollback()
    with SessionLocal() as s:  # canonical codes accepted
        from app.models.registration import User
        u = User(role="student", status="pending")
        s.add(u)
        s.flush()
        s.add(UserSettings(user_id=u.id, language="hi"))
        s.flush()
        s.rollback()


def test_f2_migration_maps_legacy_and_guards_unknown(alembic_db):
    """Upgrade 0004 -> insert legacy rows -> upgrade 0005 maps them; unknown
    values abort the migration with an explicit report.

    The two 0004 starting databases come from ``alembic_db`` (a copy of the
    session-scoped snapshot that a real alembic ``upgrade 0004_wave1_foundation``
    produced), instead of re-running that identical upgrade twice here. Every
    step this test actually asserts on — ``upgrade 0005_language_check``, ``downgrade
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
        c.commit()
        c.close()

    # Case A: legacy labels map to canonical codes.
    db_a = alembic_db("0004_wave1_foundation", name="a")
    insert(db_a, "English")
    insert(db_a, "हिन्दी (Hindi)")
    up = alembic(db_a, "upgrade", "0005_language_check")
    assert up.returncode == 0, up.stderr[-500:]
    langs = sorted(r[0] for r in sqlite3.connect(db_a).execute("SELECT language FROM user_settings"))
    assert langs == ["en", "hi"]
    # Downgrade removes only the constraint; data survives; re-upgrade clean.
    # Target 0005's parent explicitly: later migrations must not make this
    # constraint downgrade assertion accidentally exercise another revision.
    assert alembic(db_a, "downgrade", "0004_wave1_foundation").returncode == 0
    assert sorted(r[0] for r in sqlite3.connect(db_a).execute("SELECT language FROM user_settings")) == ["en", "hi"]
    assert alembic(db_a, "upgrade", "0005_language_check").returncode == 0

    # Case B: unknown value aborts loudly (no silent coercion).
    db_b = alembic_db("0004_wave1_foundation", name="b")
    insert(db_b, "Klingon")
    bad = alembic(db_b, "upgrade", "0005_language_check")
    assert bad.returncode != 0 and "unmapped legacy language values" in (bad.stderr + bad.stdout)
