from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import inspect
from sqlalchemy import func, select

from app.core.crypto import encrypt, keyed_hash
from app.core.retention import anonymise_registration, delete_registration
from app.models.registration import (
    AuthSession,
    AuthSessionProfilePrompt,
    StudentProfile,
    StudentProfileGoal,
    StudentProfileInterest,
    StudentRegistration,
    StudentVerification,
    User,
)
from app.schemas.registration import StudentRegisterRequest
from app.services import registration_service


ROOT = Path(__file__).resolve().parents[2]


def _registration_request(*, dob: str) -> StudentRegisterRequest:
    return StudentRegisterRequest(
        first_name="Clock",
        last_name="Boundary",
        mobile="9876543210",
        dob=dob,
        terms_accepted=True,
        terms_version="terms.v1",
        privacy_notice_acknowledged=True,
        privacy_notice_version="privacy.v1",
    )


def test_authoritative_profile_model_has_versioned_normalized_boundary(db_session):
    inspector = inspect(db_session.get_bind())
    columns = {column["name"] for column in inspector.get_columns("student_profiles")}
    assert {"city", "preferred_language", "profile_version"} <= columns
    assert {"student_profile_interests", "student_profile_goals", "auth_session_profile_prompts"} <= set(
        inspector.get_table_names()
    )
    assert hasattr(StudentProfile, "profile_version")


def test_registration_age_uses_the_injected_request_clock(db_session):
    result = registration_service.register_student(
        db_session,
        _registration_request(dob="2000-03-01"),
        now=datetime(2010, 3, 1, 12, tzinfo=timezone.utc),
    )
    assert result.registration.is_minor is True


def test_anonymisation_revokes_and_scrubs_verified_email_proof(db_session):
    result = registration_service.register_student(
        db_session,
        _registration_request(dob="2000-03-01"),
        now=datetime(2026, 3, 1, 12, tzinfo=timezone.utc),
    )
    registration = result.registration
    profile = db_session.scalar(
        select(StudentProfile).where(
            StudentProfile.registration_id == registration.id
        )
    )
    verification = db_session.scalar(
        select(StudentVerification).where(
            StudentVerification.registration_id == registration.id
        )
    )
    email_hash = keyed_hash("student@nls.ac.in", lower=True)
    profile.institutional_email_hash = email_hash
    profile.institutional_email_ct = encrypt("student@nls.ac.in")
    verification.status = "verified"
    verification.verified_email_hash = email_hash
    verification.metadata_json = {"proof": "must-not-survive"}
    db_session.commit()

    anonymise_registration(db_session, registration)
    db_session.flush()

    assert verification.status == "revoked"
    assert verification.verified_email_hash is None
    assert verification.metadata_json is None
    assert profile.institutional_email_hash is None


def test_registration_future_dob_uses_injected_clock_and_has_zero_write(
    db_session,
):
    with pytest.raises(registration_service.RegistrationError) as caught:
        registration_service.register_student(
            db_session,
            _registration_request(dob="2015-03-01"),
            now=datetime(2010, 3, 1, 12, tzinfo=timezone.utc),
        )
    assert (caught.value.status_code, caught.value.code, caught.value.field) == (
        422,
        "invalid_date_of_birth",
        "dob",
    )
    assert db_session.scalar(select(func.count()).select_from(User)) == 0
    assert (
        db_session.scalar(select(func.count()).select_from(StudentRegistration))
        == 0
    )
    assert db_session.scalar(select(func.count()).select_from(StudentProfile)) == 0


def test_registration_dob_equal_to_injected_request_date_is_allowed(db_session):
    result = registration_service.register_student(
        db_session,
        _registration_request(dob="2010-03-01"),
        now=datetime(2010, 3, 1, 23, 59, tzinfo=timezone.utc),
    )
    assert result.registration.is_minor is True


def test_new_registration_rejects_legacy_academic_fields_and_starts_at_zero(
    db_session,
):
    payload = {
        "first_name": "Clock",
        "last_name": "Boundary",
        "mobile": "9876543210",
        "dob": "2000-03-01",
        "terms_accepted": True,
        "terms_version": "terms.v1",
        "privacy_notice_acknowledged": True,
        "privacy_notice_version": "privacy.v1",
    }
    legacy_request = StudentRegisterRequest.model_validate(
        {
            **payload,
            "college": "Legacy College",
            "year_of_study": "3rd",
            "enrolment_number": "KA/123/2023",
            "institutional_email": "student@legacy.edu",
            "bar_enrolment_number": "BAR/123",
        }
    )
    with pytest.raises(registration_service.RegistrationError) as caught:
        registration_service.register_student(
            db_session,
            legacy_request,
            now=datetime(2026, 3, 1, 12, tzinfo=timezone.utc),
        )
    assert (caught.value.status_code, caught.value.code) == (
        422,
        "profile_fields_require_authenticated_session",
    )

    result = registration_service.register_student(
        db_session,
        StudentRegisterRequest.model_validate(payload),
        now=datetime(2026, 3, 1, 12, tzinfo=timezone.utc),
    )
    profile = db_session.scalar(
        select(StudentProfile).where(
            StudentProfile.registration_id == result.registration.id
        )
    )
    assert result.registration.institution_ref is None
    assert profile.profile_version == 1
    assert profile.college is None
    assert profile.year_of_study is None
    assert profile.enrolment_ct is None
    assert profile.institutional_email_ct is None
    assert profile.bar_enrolment_ct is None


def test_exact_legacy_idempotency_ledger_replays_before_new_write_rejection(
    db_session,
):
    from app.api.v1 import auth_student
    from app.services import otp_flow_service

    key = "pre-nyay5-legacy-ledger"
    clean = _registration_request(dob="2000-03-01")
    seeded = registration_service.register_student(
        db_session,
        clean,
        idempotency_key=key,
        now=datetime(2026, 3, 1, 12, tzinfo=timezone.utc),
    )
    auth_student._signup_flow(
        db_session,
        seeded,
        raw_token=otp_flow_service.deterministic_signup_token(key),
        destination=clean.mobile,
        now=datetime(2026, 3, 1, 12, tzinfo=timezone.utc),
    )
    legacy_payload = {
        "first_name": clean.first_name,
        "middle_name": clean.middle_name,
        "last_name": clean.last_name,
        "mobile": clean.mobile,
        "dob": clean.dob.isoformat(),
        "consent": {"accepted": True, "policy_version": "dpdp-2023.v1"},
        "college": "Legacy College",
        "year_of_study": "3rd",
        "enrolment_number": "KA/123/2023",
        "institutional_email": "student@legacy.edu",
        "bar_enrolment_number": "BAR/123",
    }
    legacy = StudentRegisterRequest.model_validate(legacy_payload)
    seeded.idempotency_record.request_fingerprint = (
        registration_service.registration_request_fingerprint(legacy)
    )
    seeded.idempotency_record.request_fingerprint_version = (
        registration_service.REGISTRATION_REQUEST_FINGERPRINT_VERSION
    )
    db_session.flush()

    replay = registration_service.register_student(
        db_session,
        legacy,
        idempotency_key=key,
        now=datetime(2026, 3, 1, 12, tzinfo=timezone.utc),
    )
    assert replay.replayed is True
    assert replay.registration.id == seeded.registration.id

    with pytest.raises(registration_service.RegistrationError) as conflict:
        registration_service.register_student(
            db_session,
            StudentRegisterRequest.model_validate(
                {**legacy_payload, "college": "Mutated College"}
            ),
            idempotency_key=key,
            now=datetime(2026, 3, 1, 12, tzinfo=timezone.utc),
        )
    assert (conflict.value.status_code, conflict.value.code) == (
        409,
        "idempotency_conflict",
    )

    before = tuple(
        db_session.scalar(select(func.count()).select_from(model))
        for model in (User, StudentRegistration, StudentProfile)
    )
    with pytest.raises(registration_service.RegistrationError) as rejected:
        registration_service.register_student(
            db_session,
            StudentRegisterRequest.model_validate(
                {**legacy_payload, "mobile": "9123456780"}
            ),
            idempotency_key="new-legacy-key",
            now=datetime(2026, 3, 1, 12, tzinfo=timezone.utc),
        )
    assert (rejected.value.status_code, rejected.value.code) == (
        422,
        "profile_fields_require_authenticated_session",
    )
    after = tuple(
        db_session.scalar(select(func.count()).select_from(model))
        for model in (User, StudentRegistration, StudentProfile)
    )
    assert after == before


def test_shared_unicode_name_corpus_is_consumed_by_backend_validator():
    document = json.loads(
        (ROOT / "contracts/unicode-legal-name-v1.json").read_text(encoding="utf-8")
    )
    assert document["schema_version"] == 1
    assert len(document["cases"]) >= 17
    from app.services import profile_service

    for case in document["cases"]:
        value = case["input"] * case.get("repeat", 1)
        if case["valid"]:
            expected = case["normalized"] * case.get("repeat", 1)
            assert profile_service.normalize_legal_name(value) == expected
            request = StudentRegisterRequest.model_validate(
                {
                    "first_name": value,
                    "last_name": "Boundary",
                    "mobile": "9876543210",
                    "dob": "2000-03-01",
                    "terms_accepted": True,
                    "terms_version": "terms.v1",
                    "privacy_notice_acknowledged": True,
                    "privacy_notice_version": "privacy.v1",
                }
            )
            assert request.first_name == expected
        else:
            try:
                profile_service.normalize_legal_name(value)
            except ValueError:
                pass
            else:
                raise AssertionError(f"invalid corpus case passed: {case['id']}")
            with pytest.raises(ValidationError):
                StudentRegisterRequest.model_validate(
                    {
                        "first_name": value,
                        "last_name": "Boundary",
                        "mobile": "9876543210",
                        "dob": "2000-03-01",
                        "terms_accepted": True,
                        "terms_version": "terms.v1",
                        "privacy_notice_acknowledged": True,
                        "privacy_notice_version": "privacy.v1",
                    }
                )


def test_completion_v1_is_server_derived_and_never_fabricates_67_percent():
    from app.services import profile_service

    assert profile_service.completion_v1(False, False, False) == {
        "completion_version": "v1",
        "completion_percent": 0,
        "completed_sections": [],
        "next_incomplete_section": "personal",
        "is_complete": False,
    }
    assert profile_service.completion_v1(True, False, False)["completion_percent"] == 34
    assert profile_service.completion_v1(True, True, False)["completion_percent"] == 67
    assert profile_service.completion_v1(True, True, True)["completion_percent"] == 100


def test_registration_anonymisation_scrubs_nyay5_profile_fields_and_children(db_session):
    result = registration_service.register_student(
        db_session,
        _registration_request(dob="2000-03-01"),
        now=datetime(2026, 3, 1, 12, tzinfo=timezone.utc),
    )
    profile = db_session.scalar(
        select(StudentProfile).where(
            StudentProfile.registration_id == result.registration.id
        )
    )
    profile.city = "Bengaluru"
    profile.preferred_language = "en"
    profile.pronouns = "they/them"
    db_session.add_all(
        [
            StudentProfileInterest(profile_id=profile.id, value="privacy"),
            StudentProfileGoal(profile_id=profile.id, value="research"),
        ]
    )
    db_session.flush()

    anonymise_registration(db_session, result.registration)
    db_session.flush()

    assert profile.city is None
    assert profile.preferred_language is None
    assert profile.pronouns is None
    assert db_session.scalar(select(func.count()).select_from(StudentProfileInterest)) == 0
    assert db_session.scalar(select(func.count()).select_from(StudentProfileGoal)) == 0


def test_registration_hard_delete_cascades_profile_children_and_session_prompt(
    db_session,
):
    result = registration_service.register_student(
        db_session,
        _registration_request(dob="2000-03-01"),
        now=datetime(2026, 3, 1, 12, tzinfo=timezone.utc),
    )
    profile = db_session.scalar(
        select(StudentProfile).where(
            StudentProfile.registration_id == result.registration.id
        )
    )
    auth_session = AuthSession(
        user_id=result.registration.user_id,
        token_hash=keyed_hash("nyay5-hard-delete-token"),
        status="active",
        expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
        last_seen_at=datetime(2026, 3, 1, 12, tzinfo=timezone.utc),
    )
    db_session.add(auth_session)
    db_session.flush()
    db_session.add_all(
        [
            StudentProfileInterest(profile_id=profile.id, value="privacy"),
            StudentProfileGoal(profile_id=profile.id, value="research"),
            AuthSessionProfilePrompt(
                auth_session_id=auth_session.id,
                dismissed_at=datetime(2026, 3, 1, 12, tzinfo=timezone.utc),
            ),
        ]
    )
    db_session.flush()

    delete_registration(db_session, result.registration)
    db_session.flush()

    for model in (
        StudentProfile,
        StudentProfileInterest,
        StudentProfileGoal,
        AuthSession,
        AuthSessionProfilePrompt,
    ):
        assert db_session.scalar(select(func.count()).select_from(model)) == 0
