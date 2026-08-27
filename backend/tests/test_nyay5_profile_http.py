from __future__ import annotations

import json
from itertools import count
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.core.auth import ActorContext, Role, get_actor_context
from app.core.config import settings
from app.core.crypto import encrypt, keyed_hash
from app.db.models.audit import AuditEvent
from app.db.session import get_session
from app.models.registration import (
    AuthSession,
    AuthSessionProfilePrompt,
    StudentProfile,
    StudentRegistration,
    User,
)
from app.services import login_service
from tests import apptemplate

NOW = datetime(2026, 8, 22, 10, 30, tzinfo=timezone.utc)
TOP_LEVEL_KEYS = {
    "profile_version",
    "completion_version",
    "completion_percent",
    "completed_sections",
    "next_incomplete_section",
    "is_complete",
    "missing_requirements",
    "institutional_email_status",
    "guardian",
    "access_mode",
    "disabled_capabilities",
    "profile_prompt",
    "profile",
}


def _claims(user_id, roles=("student",)) -> dict[str, str]:
    return {
        "X-Actor-Claims": json.dumps(
            {"sub": str(user_id), "roles": list(roles)}
        )
    }


@pytest.fixture(scope="module")
def _mounted():
    return apptemplate.mounted_app()


@pytest.fixture()
def profile_ctx(_mounted, db_session, monkeypatch):
    user = User(role="student", status="active")
    db_session.add(user)
    db_session.flush()
    registration = StudentRegistration(
        user_id=user.id,
        first_name="Aditi",
        middle_name=None,
        last_name="Nair",
        mobile_hash=keyed_hash("9876543210"),
        mobile_ct=encrypt("9876543210"),
        dob_hash=keyed_hash("2002-03-14"),
        dob_ct=encrypt("2002-03-14"),
        dob_hash_state="verified",
        key_version="v1",
        status="active",
        is_minor=False,
    )
    db_session.add(registration)
    db_session.flush()
    profile = StudentProfile(registration_id=registration.id, profile_version=1)
    db_session.add(profile)
    db_session.commit()

    def request_session():
        yield db_session

    app, client = _mounted
    apptemplate.fresh(app, client)
    app.dependency_overrides[get_session] = request_session
    from app.api.v1 import student_settings

    monkeypatch.setattr(student_settings, "_now", lambda: NOW)
    original_patch = client.patch
    mutation_sequence = count(1)

    def canonical_profile_patch(url, *args, **kwargs):
        if url in {
            "/api/v1/auth/student/profile",
            "/api/v1/student/profile/personal",
            "/api/v1/student/profile/academic",
            "/api/v1/student/profile/interests",
        }:
            headers = dict(kwargs.get("headers") or {})
            if not any(name.casefold() == "idempotency-key" for name in headers):
                headers["Idempotency-Key"] = (
                    f"nyay5-fixture-profile-mutation-{next(mutation_sequence):08d}"
                )
            kwargs["headers"] = headers
        return original_patch(url, *args, **kwargs)

    monkeypatch.setattr(client, "patch", canonical_profile_patch)
    yield client, db_session, user, registration, profile


def _personal(version: int, **overrides) -> dict:
    payload = {
        "expected_profile_version": version,
        "first_name": "Aditi",
        "middle_name": None,
        "last_name": "Nair",
        "date_of_birth": "2002-03-14",
        "preferred_language": "en",
        "city": "Bengaluru",
        "pronouns": None,
    }
    payload.update(overrides)
    return payload


def _active_cookie(client, session, user, *, raw_token="p" * 43):
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


def _assert_private_profile_projection(response) -> None:
    assert response.headers["cache-control"] == "private, no-store"
    assert "cookie" in {
        token.strip().casefold()
        for token in response.headers["vary"].split(",")
    }


def test_every_canonical_projection_response_is_private_and_not_cacheable(
    profile_ctx,
):
    client, session, user, *_ = profile_ctx
    actor_headers = _claims(user.id)

    fetched = client.get("/api/v1/student/profile", headers=actor_headers)
    assert fetched.status_code == 200
    _assert_private_profile_projection(fetched)

    personal = client.patch(
        "/api/v1/student/profile/personal",
        headers=actor_headers,
        json=_personal(1),
    )
    assert personal.status_code == 200
    _assert_private_profile_projection(personal)
    stale_personal = client.patch(
        "/api/v1/student/profile/personal",
        headers=actor_headers,
        json=_personal(1, city="Chennai"),
    )
    assert stale_personal.status_code == 409
    assert "current_projection" in stale_personal.json()["detail"]
    _assert_private_profile_projection(stale_personal)

    academic_payload = {
        "expected_profile_version": 2,
        "college": "NALSAR University of Law",
        "year_of_study": "4th",
        "enrolment_number": "TS/8/2024",
        "institutional_email": None,
        "bar_enrolment_number": None,
    }
    academic = client.patch(
        "/api/v1/student/profile/academic",
        headers=actor_headers,
        json=academic_payload,
    )
    assert academic.status_code == 200
    _assert_private_profile_projection(academic)
    stale_academic = client.patch(
        "/api/v1/student/profile/academic",
        headers=actor_headers,
        json={**academic_payload, "college": "Other"},
    )
    assert stale_academic.status_code == 409
    assert "current_projection" in stale_academic.json()["detail"]
    _assert_private_profile_projection(stale_academic)

    interests_payload = {
        "expected_profile_version": 3,
        "interests": ["Constitutional law"],
        "goals": ["Litigation"],
    }
    interests = client.patch(
        "/api/v1/student/profile/interests",
        headers=actor_headers,
        json=interests_payload,
    )
    assert interests.status_code == 200
    _assert_private_profile_projection(interests)
    stale_interests = client.patch(
        "/api/v1/student/profile/interests",
        headers=actor_headers,
        json={**interests_payload, "goals": ["Judiciary"]},
    )
    assert stale_interests.status_code == 409
    assert "current_projection" in stale_interests.json()["detail"]
    _assert_private_profile_projection(stale_interests)

    _active_cookie(client, session, user)
    dismissed = client.post(
        "/api/v1/student/profile/prompt-dismiss",
        headers={"Origin": settings.cors_origins[0]},
        json={},
    )
    assert dismissed.status_code == 200
    _assert_private_profile_projection(dismissed)


def test_canonical_get_is_exact_owner_projection(profile_ctx):
    client, _, user, *_ = profile_ctx
    response = client.get("/api/v1/student/profile", headers=_claims(user.id))
    assert response.status_code == 200
    body = response.json()
    assert set(body) == TOP_LEVEL_KEYS
    assert body["profile_version"] == 1
    assert body["completion_percent"] == 0
    assert body["completed_sections"] == []
    assert body["missing_requirements"] == [
        "personal.preferred_language",
        "personal.city",
        "academic.college",
        "academic.year_of_study",
        "academic.enrolment_number",
        "interests.interests",
        "interests.goals",
    ]
    assert body["next_incomplete_section"] == "personal"
    assert body["profile"]["personal"] == {
        "first_name": "Aditi",
        "middle_name": None,
        "last_name": "Nair",
        "date_of_birth": "2002-03-14",
        "preferred_language": None,
        "city": None,
        "pronouns": None,
    }
    assert "masked_mobile" not in body


def test_personal_write_completes_only_personal_and_stale_write_is_atomic(profile_ctx):
    client, session, user, registration, profile = profile_ctx
    first = client.patch(
        "/api/v1/student/profile/personal",
        headers=_claims(user.id),
        json=_personal(1),
    )
    assert first.status_code == 200
    assert first.json()["profile_version"] == 2
    assert first.json()["completed_sections"] == ["personal"]

    stale = client.patch(
        "/api/v1/student/profile/personal",
        headers=_claims(user.id),
        json=_personal(1, city="Chennai"),
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == {
        "code": "profile_version_conflict",
        "current_profile_version": 2,
        "current_projection": first.json(),
    }
    session.expire_all()
    assert session.get(StudentProfile, profile.id).city == "Bengaluru"
    assert session.get(StudentRegistration, registration.id).first_name == "Aditi"


def test_later_sections_cannot_bypass_personal(profile_ctx):
    client, session, user, _, profile = profile_ctx
    response = client.patch(
        "/api/v1/student/profile/academic",
        headers=_claims(user.id),
        json={
            "expected_profile_version": 1,
            "college": "NALSAR University of Law",
            "year_of_study": "4th",
            "enrolment_number": "TS/8/2024",
            "institutional_email": "aditi@nalsar.ac.in",
            "bar_enrolment_number": None,
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "profile_section_prerequisite_incomplete"
    session.expire_all()
    assert session.get(StudentProfile, profile.id).profile_version == 1


def test_stale_academic_version_wins_over_concurrent_prerequisite_regression(
    profile_ctx,
):
    client, session, user, _, profile = profile_ctx
    headers = _claims(user.id)
    assert client.patch(
        "/api/v1/student/profile/personal",
        headers=headers,
        json=_personal(1),
    ).status_code == 200
    regressed = client.patch(
        "/api/v1/student/profile/personal",
        headers=headers,
        json=_personal(2, preferred_language=None, city=None),
    )
    assert regressed.status_code == 200
    assert regressed.json()["profile_version"] == 3
    assert regressed.json()["completed_sections"] == []

    academic = {
        "expected_profile_version": 2,
        "college": "NALSAR University of Law",
        "year_of_study": "4th",
        "enrolment_number": "TS/8/2024",
        "institutional_email": None,
        "bar_enrolment_number": None,
    }
    stale = client.patch(
        "/api/v1/student/profile/academic", headers=headers, json=academic
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == {
        "code": "profile_version_conflict",
        "current_profile_version": 3,
        "current_projection": regressed.json(),
    }

    adopted = client.patch(
        "/api/v1/student/profile/academic",
        headers=headers,
        json={**academic, "expected_profile_version": 3},
    )
    assert adopted.status_code == 409
    assert adopted.json()["detail"] == {
        "code": "profile_section_prerequisite_incomplete"
    }
    session.expire_all()
    stored = session.get(StudentProfile, profile.id)
    assert stored.profile_version == 3
    assert stored.college is None


def test_stale_interests_version_wins_over_concurrent_prerequisite_regression(
    profile_ctx,
):
    client, session, user, _, profile = profile_ctx
    headers = _claims(user.id)
    assert client.patch(
        "/api/v1/student/profile/personal",
        headers=headers,
        json=_personal(1),
    ).status_code == 200
    academic = client.patch(
        "/api/v1/student/profile/academic",
        headers=headers,
        json={
            "expected_profile_version": 2,
            "college": "NALSAR University of Law",
            "year_of_study": "4th",
            "enrolment_number": "TS/8/2024",
            "institutional_email": None,
            "bar_enrolment_number": None,
        },
    )
    assert academic.status_code == 200
    regressed = client.patch(
        "/api/v1/student/profile/personal",
        headers=headers,
        json=_personal(3, preferred_language=None, city=None),
    )
    assert regressed.status_code == 200
    assert regressed.json()["profile_version"] == 4
    assert regressed.json()["completed_sections"] == []

    interests = {
        "expected_profile_version": 3,
        "interests": ["Constitutional law"],
        "goals": ["Litigation"],
    }
    stale = client.patch(
        "/api/v1/student/profile/interests", headers=headers, json=interests
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == {
        "code": "profile_version_conflict",
        "current_profile_version": 4,
        "current_projection": regressed.json(),
    }

    adopted = client.patch(
        "/api/v1/student/profile/interests",
        headers=headers,
        json={**interests, "expected_profile_version": 4},
    )
    assert adopted.status_code == 409
    assert adopted.json()["detail"] == {
        "code": "profile_section_prerequisite_incomplete"
    }
    session.expire_all()
    stored = session.get(StudentProfile, profile.id)
    assert stored.profile_version == 4
    current = client.get("/api/v1/student/profile", headers=headers)
    assert current.status_code == 200
    assert current.json()["profile_version"] == 4
    assert current.json()["profile"]["interests"] == {
        "interests": [],
        "goals": [],
    }


def test_legacy_academic_facade_requires_client_version_and_cannot_bypass_or_overwrite(
    profile_ctx,
):
    client, session, user, _, profile = profile_ctx
    academic = {
        "expected_profile_version": 1,
        "college": "NALSAR University of Law",
        "year_of_study": "4th",
        "enrolment_number": "TS/8/2024",
        "institutional_email": "aditi@nalsar.ac.in",
        "bar_enrolment_number": None,
    }
    blocked = client.patch(
        "/api/v1/auth/student/profile",
        headers=_claims(user.id),
        json=academic,
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == (
        "profile_section_prerequisite_incomplete"
    )

    personal = client.patch(
        "/api/v1/student/profile/personal",
        headers=_claims(user.id),
        json=_personal(1),
    )
    assert personal.status_code == 200
    academic["expected_profile_version"] = 2
    winner = client.patch(
        "/api/v1/auth/student/profile",
        headers=_claims(user.id),
        json=academic,
    )
    assert winner.status_code == 200
    assert winner.json()["profile_version"] == 3
    _assert_private_profile_projection(winner)

    stale = client.patch(
        "/api/v1/auth/student/profile",
        headers=_claims(user.id),
        json={**academic, "college": "Other"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "profile_version_conflict"
    assert "current_projection" in stale.json()["detail"]
    _assert_private_profile_projection(stale)
    session.expire_all()
    assert session.get(StudentProfile, profile.id).college == (
        "NALSAR University of Law"
    )


def test_legacy_academic_facade_rejects_every_client_owner_query_selector(
    profile_ctx,
):
    client, session, user, registration, profile = profile_ctx
    personal = client.patch(
        "/api/v1/student/profile/personal",
        headers=_claims(user.id),
        json=_personal(1),
    )
    assert personal.status_code == 200
    denied = client.patch(
        f"/api/v1/auth/student/profile?registration_id={registration.id}",
        headers=_claims(user.id),
        json={
            "expected_profile_version": 2,
            "college": "NALSAR University of Law",
            "year_of_study": "4th",
            "enrolment_number": "TS/8/2024",
            "institutional_email": "aditi@nalsar.ac.in",
            "bar_enrolment_number": None,
        },
    )
    assert denied.status_code == 422
    assert denied.json()["detail"] == {
        "code": "validation_error",
        "field": "query",
    }
    session.expire_all()
    stored = session.get(StudentProfile, profile.id)
    assert stored.profile_version == 2
    assert stored.college is None


def test_anonymous_wrong_role_and_client_owner_selector_fail_without_mutation(profile_ctx):
    client, session, user, _, profile = profile_ctx
    assert client.get("/api/v1/student/profile").status_code == 401
    assert client.get(
        "/api/v1/student/profile", headers=_claims(user.id, ("lawyer",))
    ).status_code == 403
    forged = _personal(1, registration_id="00000000-0000-0000-0000-000000000001")
    denied = client.patch(
        "/api/v1/student/profile/personal", headers=_claims(user.id), json=forged
    )
    assert denied.status_code == 422
    session.expire_all()
    assert session.get(StudentProfile, profile.id).profile_version == 1


def test_profile_audit_is_bounded_and_contains_no_profile_uuid_or_pii(profile_ctx):
    client, session, user, registration, profile = profile_ctx
    assert client.patch(
        "/api/v1/student/profile/personal",
        headers=_claims(user.id),
        json=_personal(1),
    ).status_code == 200
    event = session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "student.profile.section_updated"
        )
    )
    assert event is not None and event.resource_id is None
    blob = json.dumps(event.after_state, sort_keys=True)
    for forbidden in (
        str(registration.id),
        str(profile.id),
        "Aditi",
        "Nair",
        "Bengaluru",
        "2002-03-14",
    ):
        assert forbidden not in blob


def test_prompt_dismiss_requires_active_server_cookie_not_dev_actor_header(profile_ctx):
    client, session, user, *_ = profile_ctx
    response = client.post(
        "/api/v1/student/profile/prompt-dismiss",
        headers=_claims(user.id),
        json={},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "session_authority_required"
    assert session.scalar(select(AuditEvent).where(
        AuditEvent.action == "student.profile.prompt_dismissed"
    )) is None


def test_prompt_dismiss_survives_reload_is_idempotent_and_clears_on_rotation_revocation(
    profile_ctx,
):
    client, session, user, registration, _ = profile_ctx
    old_session, _ = _active_cookie(client, session, user)
    trusted = {"Origin": settings.cors_origins[0]}

    first = client.post(
        "/api/v1/student/profile/prompt-dismiss", headers=trusted, json={}
    )
    second = client.post(
        "/api/v1/student/profile/prompt-dismiss", headers=trusted, json={}
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["profile_prompt"] == {
        "should_show": False,
        "dismissed_for_session": True,
    }
    assert client.get("/api/v1/student/profile").json()["profile_prompt"] == {
        "should_show": False,
        "dismissed_for_session": True,
    }
    assert session.scalar(
        select(func.count()).select_from(AuthSessionProfilePrompt)
    ) == 1

    new_token, new_session = login_service.rotate_authenticated_session(
        session, registration, NOW + timedelta(minutes=1)
    )
    client.cookies.clear()
    client.cookies.set(settings.auth_session_cookie_name, new_token)
    fresh = client.get("/api/v1/student/profile")
    assert fresh.status_code == 200
    assert fresh.json()["profile_prompt"] == {
        "should_show": True,
        "dismissed_for_session": False,
    }
    session.expire_all()
    assert session.get(AuthSession, old_session.id).status == "revoked"
    assert session.scalar(
        select(func.count())
        .select_from(AuthSessionProfilePrompt)
        .where(AuthSessionProfilePrompt.auth_session_id == old_session.id)
    ) == 0

    new_session.status = "revoked"
    new_session.revoked_at = NOW + timedelta(minutes=2)
    session.commit()
    assert client.get("/api/v1/student/profile").status_code == 401


def test_cookie_profile_mutations_require_exact_trusted_origin_with_zero_write(profile_ctx):
    client, session, user, _, profile = profile_ctx
    _active_cookie(client, session, user)
    for origin in (
        None,
        "https://attacker.example",
        f"{settings.cors_origins[0]}.attacker.example",
    ):
        headers = {} if origin is None else {"Origin": origin}
        denied = client.patch(
            "/api/v1/student/profile/personal",
            headers=headers,
            json=_personal(1),
        )
        assert denied.status_code == 403
        session.expire_all()
        assert session.get(StudentProfile, profile.id).profile_version == 1

    allowed = client.patch(
        "/api/v1/student/profile/personal",
        headers={"Origin": settings.cors_origins[0]},
        json=_personal(1),
    )
    assert allowed.status_code == 200


def test_revoked_cookie_revalidation_beats_stale_dependency_actor_with_zero_write(
    profile_ctx,
):
    client, session, user, _, profile = profile_ctx
    auth_session, _ = _active_cookie(client, session, user)
    auth_session.status = "revoked"
    auth_session.revoked_at = NOW
    session.commit()
    client.app.dependency_overrides[get_actor_context] = lambda: ActorContext(
        user_id=user.id,
        roles=frozenset({Role.STUDENT}),
    )
    try:
        denied = client.patch(
            "/api/v1/student/profile/personal",
            headers={"Origin": settings.cors_origins[0]},
            json=_personal(1),
        )
    finally:
        client.app.dependency_overrides.pop(get_actor_context, None)

    assert denied.status_code == 401
    assert denied.json()["detail"]["code"] == "session_authority_required"
    session.expire_all()
    assert session.get(StudentProfile, profile.id).profile_version == 1


def test_cookie_authority_overrides_forged_cross_user_header(profile_ctx):
    client, session, user, *_ = profile_ctx
    _active_cookie(client, session, user)
    other_user = User(role="student", status="active")
    session.add(other_user)
    session.flush()
    other_registration = StudentRegistration(
        user_id=other_user.id,
        first_name="Other",
        middle_name=None,
        last_name="Student",
        mobile_hash=keyed_hash("9123456780"),
        mobile_ct=encrypt("9123456780"),
        dob_hash=keyed_hash("2000-01-01"),
        dob_ct=encrypt("2000-01-01"),
        dob_hash_state="verified",
        key_version="v1",
        status="active",
        is_minor=False,
    )
    session.add(other_registration)
    session.flush()
    session.add(StudentProfile(registration_id=other_registration.id))
    session.commit()

    response = client.get(
        "/api/v1/student/profile", headers=_claims(other_user.id)
    )
    assert response.status_code == 200
    assert response.json()["profile"]["personal"]["first_name"] == "Aditi"

    denied_selector = client.get(
        f"/api/v1/student/profile?registration_id={other_registration.id}"
    )
    assert denied_selector.status_code == 422
    assert denied_selector.json()["detail"]["code"] == "validation_error"


def test_deleted_and_ambiguous_authority_fail_closed_without_mutation(profile_ctx):
    client, session, user, _, profile = profile_ctx
    user.status = "deleted"
    session.commit()
    deleted = client.get("/api/v1/student/profile", headers=_claims(user.id))
    assert deleted.status_code == 404
    session.expire_all()
    assert session.get(StudentProfile, profile.id).profile_version == 1

    user = session.get(User, user.id)
    user.status = "active"
    second = StudentRegistration(
        user_id=user.id,
        first_name="Ambiguous",
        middle_name=None,
        last_name="Owner",
        mobile_hash=keyed_hash("9000000000"),
        mobile_ct=encrypt("9000000000"),
        dob_hash=keyed_hash("2000-01-01"),
        dob_ct=encrypt("2000-01-01"),
        dob_hash_state="verified",
        key_version="v1",
        status="active",
        is_minor=False,
    )
    session.add(second)
    session.flush()
    session.add(StudentProfile(registration_id=second.id))
    session.commit()
    ambiguous = client.get("/api/v1/student/profile", headers=_claims(user.id))
    assert ambiguous.status_code == 404
    assert ambiguous.json()["detail"]["code"] == "profile_not_found"


@pytest.mark.parametrize("authority_field", ["guardian", "institutional_email_status"])
def test_student_cannot_self_set_guardian_or_verification_authority(
    profile_ctx, authority_field
):
    client, session, user, _, profile = profile_ctx
    forged = _personal(1)
    forged[authority_field] = (
        {"required": True, "status": "verified"}
        if authority_field == "guardian"
        else "verified"
    )
    denied = client.patch(
        "/api/v1/student/profile/personal", headers=_claims(user.id), json=forged
    )
    assert denied.status_code == 422
    session.expire_all()
    assert session.get(StudentProfile, profile.id).profile_version == 1
