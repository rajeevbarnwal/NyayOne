"""NYAY-9 RED contracts for the owner-scoped student-profile API.

These tests deliberately describe the remaining NYAY-9 surface rather than
re-testing the already-frozen NYAY-5 boundary.  In particular they require a
field-level missing-requirements projection, strict response schemas,
actor-and-section-scoped mutation idempotency, a native PostgreSQL concurrency
gate, and a privacy-export materializer.  Until GREEN is authorized, every test
in this file is expected to fail for one of those missing capabilities.
"""
from __future__ import annotations

import ast
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.api.v1 import auth_student, student_settings
from app.core import retention
from app.core.config import settings
from app.core.crypto import encrypt, keyed_hash
from app.db.session import get_session
from app.models import registration as registration_models
from app.models.registration import (
    AuthSession,
    ProfileMutationIdempotencyRecord,
    StudentProfile,
    StudentRegistration,
    User,
)
from app.services import profile_service
from tests import apptemplate


NOW = datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc)
BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent

INITIAL_MISSING_REQUIREMENTS = [
    "personal.preferred_language",
    "personal.city",
    "academic.college",
    "academic.year_of_study",
    "academic.enrolment_number",
    "interests.interests",
    "interests.goals",
]


def _student(session, *, suffix: str, first_name: str):
    user = User(role="student", status="active")
    session.add(user)
    session.flush()
    registration = StudentRegistration(
        user_id=user.id,
        first_name=first_name,
        middle_name=None,
        last_name="Nair",
        mobile_hash=keyed_hash(f"98765432{suffix}"),
        mobile_ct=encrypt(f"98765432{suffix}"),
        dob_hash=keyed_hash("2002-03-14"),
        dob_ct=encrypt("2002-03-14"),
        dob_hash_state="verified",
        key_version="v1",
        status="active",
        is_minor=False,
    )
    session.add(registration)
    session.flush()
    profile = StudentProfile(registration_id=registration.id, profile_version=1)
    session.add(profile)
    session.flush()
    return user, registration, profile


@pytest.fixture(scope="module")
def _mounted():
    return apptemplate.mounted_app(exception_handlers=True)


@pytest.fixture()
def nyay9_ctx(_mounted, db_session, monkeypatch):
    owner, owner_registration, owner_profile = _student(
        db_session, suffix="10", first_name="Aditi"
    )
    other, other_registration, other_profile = _student(
        db_session, suffix="11", first_name="Meera"
    )
    db_session.commit()

    def request_session():
        yield db_session

    app, client = _mounted
    apptemplate.fresh(app, client)
    app.dependency_overrides[get_session] = request_session
    monkeypatch.setattr(student_settings, "_now", lambda: NOW)
    yield {
        "app": app,
        "client": client,
        "session": db_session,
        "owner": owner,
        "owner_registration": owner_registration,
        "owner_profile": owner_profile,
        "other": other,
        "other_registration": other_registration,
        "other_profile": other_profile,
    }
    app.dependency_overrides.clear()


def _activate_cookie(ctx, user, *, token_suffix: str):
    client = ctx["client"]
    session = ctx["session"]
    raw_token = (token_suffix * 43)[:43]
    row = AuthSession(
        user_id=user.id,
        token_hash=keyed_hash(raw_token),
        status="active",
        expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
        last_seen_at=NOW,
    )
    session.add(row)
    session.commit()
    client.cookies.clear()
    client.cookies.set(settings.auth_session_cookie_name, raw_token)
    return row, raw_token


def _headers(*, idempotency_key: str | None = None, forged_actor=None):
    result = {"Origin": settings.cors_origins[0]}
    if idempotency_key is not None:
        result["Idempotency-Key"] = idempotency_key
    if forged_actor is not None:
        result["X-Actor-Claims"] = json.dumps(
            {"sub": str(forged_actor.id), "roles": ["student"]}
        )
    return result


def _personal(version: int, *, city: str = "Bengaluru"):
    return {
        "expected_profile_version": version,
        "first_name": "Aditi",
        "middle_name": None,
        "last_name": "Nair",
        "date_of_birth": "2002-03-14",
        "preferred_language": "en",
        "city": city,
        "pronouns": None,
    }


def _academic(version: int):
    return {
        "expected_profile_version": version,
        "college": "NALSAR University of Law",
        "year_of_study": "4th",
        "enrolment_number": "TS/8/2024",
        "institutional_email": None,
        "bar_enrolment_number": None,
    }


def _interests(version: int):
    return {
        "expected_profile_version": version,
        "interests": ["Constitutional law"],
        "goals": ["Litigation"],
    }


def test_initial_projection_reports_exact_field_level_missing_requirements(nyay9_ctx):
    _activate_cookie(nyay9_ctx, nyay9_ctx["owner"], token_suffix="a")

    response = nyay9_ctx["client"].get("/api/v1/student/profile")

    assert response.status_code == 200
    assert response.json().get("missing_requirements") == INITIAL_MISSING_REQUIREMENTS


def test_missing_requirements_shrink_server_side_after_each_owner_write(nyay9_ctx):
    first_session, _ = _activate_cookie(
        nyay9_ctx, nyay9_ctx["owner"], token_suffix="b"
    )
    client = nyay9_ctx["client"]

    skipped = client.patch(
        "/api/v1/student/profile/academic",
        headers=_headers(idempotency_key="nyay9-direct-step-skip"),
        json=_academic(1),
    )
    assert skipped.status_code == 409
    assert skipped.json()["detail"]["code"] == (
        "profile_section_prerequisite_incomplete"
    )
    unchanged = client.get("/api/v1/student/profile")
    assert unchanged.json()["profile_version"] == 1
    assert unchanged.json()["missing_requirements"] == INITIAL_MISSING_REQUIREMENTS

    personal = client.patch(
        "/api/v1/student/profile/personal",
        headers=_headers(idempotency_key="nyay9-personal-step"),
        json=_personal(1),
    )
    academic = client.patch(
        "/api/v1/student/profile/academic",
        headers=_headers(idempotency_key="nyay9-academic-step"),
        json=_academic(2),
    )
    interests = client.patch(
        "/api/v1/student/profile/interests",
        headers=_headers(idempotency_key="nyay9-interests-step"),
        json=_interests(3),
    )

    assert [personal.status_code, academic.status_code, interests.status_code] == [
        200,
        200,
        200,
    ]
    actual = [
        personal.json().get("missing_requirements"),
        academic.json().get("missing_requirements"),
        interests.json().get("missing_requirements"),
    ]
    assert actual == [
        INITIAL_MISSING_REQUIREMENTS[2:],
        INITIAL_MISSING_REQUIREMENTS[5:],
        [],
    ]
    assert interests.json()["is_complete"] is True
    sealed_projection = interests.json()

    # A fresh server-issued session must hydrate the exact saved projection;
    # no client-side completion state participates in the read.
    first_session.status = "revoked"
    first_session.revoked_at = NOW
    nyay9_ctx["session"].commit()
    _activate_cookie(nyay9_ctx, nyay9_ctx["owner"], token_suffix="j")
    hydrated = client.get("/api/v1/student/profile")
    assert hydrated.status_code == 200
    assert hydrated.json() == sealed_projection


def test_owner_is_derived_from_session_and_projection_cannot_be_client_selected(
    nyay9_ctx,
):
    active_session, _ = _activate_cookie(
        nyay9_ctx, nyay9_ctx["owner"], token_suffix="c"
    )
    client = nyay9_ctx["client"]
    other = nyay9_ctx["other"]

    selected_by_query = client.get(
        f"/api/v1/student/profile?registration_id={nyay9_ctx['other_registration'].id}"
    )
    selected_by_body = client.patch(
        "/api/v1/student/profile/personal",
        headers=_headers(idempotency_key="nyay9-owner", forged_actor=other),
        json={
            **_personal(1),
            "registration_id": str(nyay9_ctx["other_registration"].id),
            "missing_requirements": [],
        },
    )
    owner_projection = client.get(
        "/api/v1/student/profile", headers=_headers(forged_actor=other)
    )

    assert selected_by_query.status_code == 422
    assert selected_by_body.status_code == 422
    assert owner_projection.status_code == 200
    body = owner_projection.json()
    assert body["profile"]["personal"]["first_name"] == "Aditi"
    serialized = json.dumps(body, sort_keys=True)
    assert "Meera" not in serialized
    for forbidden in (
        "registration_id",
        "user_id",
        "mobile",
        "mobile_hash",
        "token",
        "ciphertext",
    ):
        assert forbidden not in serialized
    assert body.get("missing_requirements") == INITIAL_MISSING_REQUIREMENTS

    session = nyay9_ctx["session"]
    active_session.status = "revoked"
    active_session.revoked_at = NOW
    session.commit()
    assert client.get("/api/v1/student/profile").status_code == 401

    expired, _ = _activate_cookie(
        nyay9_ctx, nyay9_ctx["owner"], token_suffix="l"
    )
    expired.status = "expired"
    expired.expires_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    expired.revoked_at = NOW
    session.commit()
    assert client.get("/api/v1/student/profile").status_code == 401


def test_nyay8_authenticated_session_and_onboarding_use_one_exact_projection(nyay9_ctx):
    _, raw_token = _activate_cookie(
        nyay9_ctx, nyay9_ctx["owner"], token_suffix="d"
    )
    session = nyay9_ctx["session"]
    owner = nyay9_ctx["owner"]

    onboarding = auth_student._authenticated_onboarding_response(
        session,
        actor_user_id=owner.id,
        raw_session_token=raw_token,
        purpose="login",
        now=NOW,
    )["onboarding"]
    fresh_read = nyay9_ctx["client"].get("/api/v1/student/profile")

    assert fresh_read.status_code == 200
    assert onboarding == fresh_read.json()
    assert onboarding.get("missing_requirements") == INITIAL_MISSING_REQUIREMENTS


def test_openapi_seals_exact_profile_response_contracts(nyay9_ctx):
    app = nyay9_ctx["app"]
    app.openapi_schema = None
    schema = app.openapi()
    expected_ref = "#/components/schemas/StudentProfileProjectionResponse"
    routes = {
        ("/api/v1/auth/student/profile", "patch"),
        ("/api/v1/student/profile", "get"),
        ("/api/v1/student/profile/personal", "patch"),
        ("/api/v1/student/profile/academic", "patch"),
        ("/api/v1/student/profile/interests", "patch"),
    }

    actual_refs = {
        f"{method.upper()} {path}": schema["paths"][path][method]["responses"]["200"]
        ["content"]["application/json"]["schema"].get("$ref")
        for path, method in routes
    }
    projection_schema = schema.get("components", {}).get("schemas", {}).get(
        "StudentProfileProjectionResponse"
    )

    assert actual_refs == {key: expected_ref for key in actual_refs}
    assert projection_schema is not None
    assert projection_schema.get("additionalProperties") is False
    assert set(projection_schema["required"]) >= {
        "profile_version",
        "completion_version",
        "completion_percent",
        "completed_sections",
        "missing_requirements",
        "next_incomplete_section",
        "is_complete",
        "profile",
    }


def test_mutation_requires_a_single_valid_opaque_idempotency_key(nyay9_ctx):
    _activate_cookie(nyay9_ctx, nyay9_ctx["owner"], token_suffix="e")
    client = nyay9_ctx["client"]

    missing = client.patch(
        "/api/v1/student/profile/personal",
        headers=_headers(),
        json=_personal(1),
    )

    assert missing.status_code == 422
    assert missing.json()["detail"] == {
        "code": "invalid_idempotency_key",
        "field": "Idempotency-Key",
        "message": "Request failed",
    }
    legacy_missing = client.patch(
        "/api/v1/auth/student/profile",
        headers=_headers(),
        json={**_academic(1), "institutional_email": "student@example.edu"},
    )
    assert legacy_missing.status_code == 422
    assert legacy_missing.json()["detail"] == missing.json()["detail"]
    for value in ("", " ", "short", "contains pii@example.test"):
        rejected = client.patch(
            "/api/v1/student/profile/personal",
            headers=_headers(idempotency_key=value),
            json=_personal(1),
        )
        assert rejected.status_code == 422
        assert rejected.json()["detail"]["code"] == "invalid_idempotency_key"

        legacy_rejected = client.patch(
            "/api/v1/auth/student/profile",
            headers=_headers(idempotency_key=value),
            json={**_academic(1), "institutional_email": "student@example.edu"},
        )
        assert legacy_rejected.status_code == 422
        assert legacy_rejected.json()["detail"]["code"] == (
            "invalid_idempotency_key"
        )

    duplicate_headers = [
        ("Origin", settings.cors_origins[0]),
        ("Idempotency-Key", "nyay9-duplicate-key-000000000001"),
        ("Idempotency-Key", "nyay9-duplicate-key-000000000002"),
    ]
    duplicate = client.patch(
        "/api/v1/student/profile/personal",
        headers=duplicate_headers,
        json=_personal(1),
    )
    legacy_duplicate = client.patch(
        "/api/v1/auth/student/profile",
        headers=duplicate_headers,
        json={**_academic(1), "institutional_email": "student@example.edu"},
    )
    assert duplicate.status_code == legacy_duplicate.status_code == 422
    assert duplicate.json()["detail"]["code"] == "invalid_idempotency_key"
    assert legacy_duplicate.json()["detail"]["code"] == (
        "invalid_idempotency_key"
    )


def test_same_idempotency_key_and_payload_replays_exact_first_outcome(nyay9_ctx):
    _activate_cookie(nyay9_ctx, nyay9_ctx["owner"], token_suffix="f")
    client = nyay9_ctx["client"]
    headers = _headers(idempotency_key="profile-personal-replay-key-0001")

    first = client.patch(
        "/api/v1/student/profile/personal", headers=headers, json=_personal(1)
    )
    replay = client.patch(
        "/api/v1/student/profile/personal", headers=headers, json=_personal(1)
    )

    assert first.status_code == replay.status_code == 200
    assert replay.json() == first.json()
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json()["profile_version"] == 2

    legacy_headers = _headers(
        idempotency_key="profile-legacy-academic-replay-key-0001"
    )
    legacy_payload = {
        **_academic(2),
        "institutional_email": "student@example.edu",
    }
    legacy_first = client.patch(
        "/api/v1/auth/student/profile",
        headers=legacy_headers,
        json=legacy_payload,
    )
    legacy_replay = client.patch(
        "/api/v1/auth/student/profile",
        headers=legacy_headers,
        json=legacy_payload,
    )
    legacy_mismatch = client.patch(
        "/api/v1/auth/student/profile",
        headers=legacy_headers,
        json={**legacy_payload, "institutional_email": "other@example.edu"},
    )
    assert legacy_first.status_code == legacy_replay.status_code == 200
    assert legacy_replay.json() == legacy_first.json()
    assert legacy_replay.headers["Idempotency-Replayed"] == "true"
    assert legacy_mismatch.status_code == 409
    assert legacy_mismatch.json()["detail"] == {
        "code": "profile_idempotency_conflict",
        "section": "academic",
        "message": "Request failed",
    }
    assert "other@example.edu" not in legacy_mismatch.text


def test_idempotency_conflict_is_typed_pii_safe_and_scoped_by_actor_and_section(
    nyay9_ctx,
):
    client = nyay9_ctx["client"]
    shared_key = "profile-scope-key-0000000000000001"
    _activate_cookie(nyay9_ctx, nyay9_ctx["owner"], token_suffix="g")

    owner_personal = client.patch(
        "/api/v1/student/profile/personal",
        headers=_headers(idempotency_key=shared_key),
        json=_personal(1),
    )
    owner_academic = client.patch(
        "/api/v1/student/profile/academic",
        headers=_headers(idempotency_key=shared_key),
        json=_academic(2),
    )
    _activate_cookie(nyay9_ctx, nyay9_ctx["other"], token_suffix="h")
    other_personal = client.patch(
        "/api/v1/student/profile/personal",
        headers=_headers(idempotency_key=shared_key),
        json={**_personal(1), "first_name": "Meera"},
    )
    client.cookies.clear()
    client.cookies.set(settings.auth_session_cookie_name, "g" * 43)
    mismatch = client.patch(
        "/api/v1/student/profile/personal",
        headers=_headers(idempotency_key=shared_key),
        json=_personal(1, city="Chennai"),
    )

    assert [
        owner_personal.status_code,
        owner_academic.status_code,
        other_personal.status_code,
    ] == [200, 200, 200]
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"] == {
        "code": "profile_idempotency_conflict",
        "section": "personal",
        "message": "Request failed",
    }
    assert "Bengaluru" not in mismatch.text
    assert "Chennai" not in mismatch.text
    assert "Aditi" not in mismatch.text


def test_native_postgres_gate_seals_idempotent_concurrency_and_storage_contracts():
    migration = list(
        (BACKEND / "app/db/migrations/versions").glob(
            "0022*_nyay9_owner_profile_api.py"
        )
    )
    gate = REPO / "scripts/ci/nyay9-profile-api-postgres.mjs"
    contract = REPO / "scripts/ci/nyay9-profile-api-contract.json"
    model = getattr(registration_models, "ProfileMutationIdempotencyRecord", None)
    checks = {
        "migration_0022": len(migration) == 1,
        "idempotency_model": model is not None,
        "postgres_gate": gate.is_file(),
        "versioned_contract": contract.is_file(),
    }
    assert checks == {key: True for key in checks}

    migration_tree = ast.parse(migration[0].read_text(encoding="utf-8"))
    revision = next(
        ast.literal_eval(node.value)
        for node in migration_tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "revision"
    )
    assert len(revision) <= 32, "Alembic version_num cannot store this revision"

    gate_source = gate.read_text(encoding="utf-8")
    required_oracles = {
        "OWNER_ONLY_SESSION_AUTHORITY",
        "CROSS_OWNER_ISOLATION",
        "IDEMPOTENT_SAME_KEY_CONCURRENCY",
        "VERSION_CONFLICT_DIFFERENT_KEYS",
        "DOB_GUARDIAN_ATOMIC_TRANSITION",
        "PII_CLEAN_DIAGNOSTICS",
        "MIGRATION_UP_DOWN_UP",
    }
    assert all(oracle in gate_source for oracle in required_oracles)
    assert set(model.__table__.columns.keys()) >= {
        "actor_user_id",
        "section",
        "idempotency_key_hash",
        "request_fingerprint",
        "state",
        "profile_version",
    }
    assert "idempotency_key" not in model.__table__.columns


def test_privacy_export_materializes_every_owner_profile_field_without_internals(
    nyay9_ctx,
):
    _activate_cookie(nyay9_ctx, nyay9_ctx["owner"], token_suffix="i")
    exporter = getattr(profile_service, "export_profile_for_actor", None)

    client = nyay9_ctx["client"]
    personal = client.patch(
        "/api/v1/student/profile/personal",
        headers=_headers(idempotency_key="privacy-export-ledger-key-000001"),
        json=_personal(1),
    )
    academic = client.patch(
        "/api/v1/student/profile/academic",
        headers=_headers(idempotency_key="privacy-export-ledger-key-000002"),
        json=_academic(2),
    )
    interests = client.patch(
        "/api/v1/student/profile/interests",
        headers=_headers(idempotency_key="privacy-export-ledger-key-000003"),
        json=_interests(3),
    )
    assert [personal.status_code, academic.status_code, interests.status_code] == [
        200,
        200,
        200,
    ]

    assert callable(exporter), "NYAY-9 must materialize owner profile exports"
    exported = exporter(
        nyay9_ctx["session"],
        nyay9_ctx["owner"].id,
        now=NOW,
    )
    assert set(exported) == {"schema_version", "profile_version", "profile"}
    assert exported["schema_version"] == "student-profile-export.v1"
    assert set(exported["profile"]) == {"personal", "academic", "interests"}
    assert set(exported["profile"]["personal"]) == {
        "first_name",
        "middle_name",
        "last_name",
        "date_of_birth",
        "preferred_language",
        "city",
        "pronouns",
    }
    assert set(exported["profile"]["academic"]) == {
        "college",
        "year_of_study",
        "enrolment_number",
        "institutional_email",
        "bar_enrolment_number",
    }
    assert set(exported["profile"]["interests"]) == {"interests", "goals"}
    assert exported["profile"]["academic"] == {
        "college": "NALSAR University of Law",
        "year_of_study": "4th",
        "enrolment_number": "TS/8/2024",
        "institutional_email": None,
        "bar_enrolment_number": None,
    }
    assert exported["profile"]["interests"] == {
        "interests": ["Constitutional law"],
        "goals": ["Litigation"],
    }
    serialized_keys = json.dumps(exported, sort_keys=True)
    for forbidden in (
        "user_id",
        "registration_id",
        "profile_id",
        "_hash",
        "_ct",
        "ciphertext",
        "token",
    ):
        assert forbidden not in serialized_keys

    session = nyay9_ctx["session"]
    ledgers = list(session.scalars(select(ProfileMutationIdempotencyRecord)))
    assert len(ledgers) == 3
    assert all(ledger.outcome_ct is not None for ledger in ledgers)
    original_key_hashes = {
        ledger.id: ledger.idempotency_key_hash for ledger in ledgers
    }
    registration = session.scalar(
        select(StudentRegistration).where(
            StudentRegistration.user_id == nyay9_ctx["owner"].id
        )
    )
    assert registration is not None
    retention.anonymise_registration(session, registration)
    session.commit()
    for ledger in ledgers:
        session.refresh(ledger)
        assert (
            ledger.state,
            ledger.request_fingerprint,
            ledger.request_fingerprint_version,
            ledger.outcome_status,
            ledger.outcome_ct,
            ledger.key_version,
            ledger.profile_version,
        ) == ("erased", None, None, None, None, None, None)
        assert ledger.idempotency_key_hash != original_key_hashes[ledger.id]
