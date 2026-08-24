from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import uuid

import pytest
from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.crypto import encrypt, keyed_hash
from app.core.auth import ActorContext, Role
from app.api.v1 import credentials as credential_api
from app.db.models.audit import AuditEvent
from app.models.credentials import (
    Credential,
    CredentialShareProjection,
    VerificationToken,
)
from app.models.registration import (
    AuthSession,
    GuardianConsent,
    StudentProfile,
    StudentRegistration,
    StudentVerification,
    User,
)
from app.services import profile_service
from app.services import login_service

NOW = datetime(2026, 8, 22, 10, 30, tzinfo=timezone.utc)


def _seed(
    session: Session,
    *,
    dob: date = date(2000, 1, 1),
    is_minor: bool = False,
) -> tuple[User, StudentRegistration, StudentProfile]:
    user = User(role="student", status="active")
    session.add(user)
    session.flush()
    registration = StudentRegistration(
        user_id=user.id,
        first_name="Aditi",
        middle_name=None,
        last_name="Nair",
        mobile_hash=keyed_hash("9876543210"),
        mobile_ct=encrypt("9876543210"),
        dob_hash=keyed_hash(dob.isoformat()),
        dob_ct=encrypt(dob.isoformat()),
        dob_hash_state="verified",
        key_version="v1",
        status="active",
        is_minor=is_minor,
    )
    session.add(registration)
    session.flush()
    profile = StudentProfile(registration_id=registration.id, profile_version=1)
    session.add(profile)
    if is_minor:
        session.add(
            GuardianConsent(
                registration_id=registration.id,
                status="pending",
                verified=False,
            )
        )
    session.commit()
    return user, registration, profile


def _personal(
    session: Session,
    user: User,
    *,
    version: int,
    dob: date,
    now: datetime = NOW,
) -> dict:
    return profile_service.update_personal(
        session,
        user.id,
        expected_profile_version=version,
        first_name="Aditi",
        middle_name=None,
        last_name="Nair",
        date_of_birth=dob,
        preferred_language="en",
        city="Bengaluru",
        pronouns=None,
        now=now,
    )


def test_full_persisted_sequence_is_exact_0_34_67_100_and_survives_fresh_session(
    db_session,
):
    user, _, _ = _seed(db_session)
    initial = profile_service.projection_for_actor(db_session, user.id, now=NOW)
    assert (initial["completion_percent"], initial["completed_sections"]) == (0, [])

    personal = _personal(
        db_session, user, version=1, dob=date(2000, 1, 1)
    )
    assert (personal["completion_percent"], personal["completed_sections"]) == (
        34,
        ["personal"],
    )
    academic = profile_service.update_academic(
        db_session,
        user.id,
        expected_profile_version=2,
        college="National Law School of India University",
        year_of_study="3rd",
        enrolment_number="KA/1234/2023",
        institutional_email=None,
        bar_enrolment_number=None,
        now=NOW,
    )
    assert (academic["completion_percent"], academic["completed_sections"]) == (
        67,
        ["personal", "academic"],
    )
    complete = profile_service.update_interests(
        db_session,
        user.id,
        expected_profile_version=3,
        interests=["Privacy", "Constitutional law"],
        goals=["Research"],
        now=NOW,
    )
    assert (complete["completion_percent"], complete["completed_sections"]) == (
        100,
        ["personal", "academic", "interests"],
    )
    assert complete["is_complete"] is True

    fresh = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)()
    try:
        reloaded = profile_service.projection_for_actor(fresh, user.id, now=NOW)
        assert reloaded == complete
    finally:
        fresh.close()


def test_projection_for_actor_requests_one_locked_authority_graph(
    db_session,
    monkeypatch,
):
    user, _, _ = _seed(db_session)
    original = profile_service.resolve_authority
    lock_requests = []

    def recording_resolve(session, actor_user_id, **kwargs):
        lock_requests.append(kwargs.get("for_update", False))
        return original(session, actor_user_id, **kwargs)

    monkeypatch.setattr(profile_service, "resolve_authority", recording_resolve)
    profile_service.projection_for_actor(db_session, user.id, now=NOW)
    assert lock_requests == [True]


def test_locked_projection_locks_normalized_values_and_presented_session(
    db_session,
    monkeypatch,
):
    user, _, _ = _seed(db_session)
    authority = profile_service.resolve_authority(
        db_session, user.id, for_update=True
    )
    original_values = profile_service._profile_values
    original_session = profile_service._active_auth_session
    value_locks = []
    session_locks = []

    def recording_values(session, profile_id, model, *, for_update=False):
        value_locks.append(for_update)
        return original_values(
            session, profile_id, model, for_update=for_update
        )

    def recording_session(*args, **kwargs):
        session_locks.append(kwargs.get("for_update", False))
        return original_session(*args, **kwargs)

    monkeypatch.setattr(profile_service, "_profile_values", recording_values)
    monkeypatch.setattr(
        profile_service, "_active_auth_session", recording_session
    )
    profile_service.project(db_session, authority, now=NOW)
    assert value_locks == [True, True]
    assert session_locks == [True]


def test_profile_mutation_returns_the_exact_in_transaction_projection_without_reread(
    db_session,
    monkeypatch,
):
    user, _, _ = _seed(db_session)

    def reject_post_commit_reread(*_args, **_kwargs):
        raise AssertionError("profile mutation reread after committing its projection")

    monkeypatch.setattr(
        profile_service,
        "projection_for_actor",
        reject_post_commit_reread,
    )
    result = _personal(
        db_session, user, version=1, dob=date(2000, 1, 1)
    )
    assert result["profile_version"] == 2


@pytest.mark.parametrize(
    ("dob", "is_minor"),
    [
        (date(2008, 8, 23), True),
        (date(2008, 8, 22), False),
        (date(2008, 8, 21), False),
    ],
    ids=("just_under_18", "exactly_18", "over_18"),
)
def test_dob_age_boundaries_atomically_drive_guardian_and_access(
    db_session, dob, is_minor
):
    user, registration, _ = _seed(db_session)
    result = _personal(db_session, user, version=1, dob=dob)
    db_session.refresh(registration)
    assert registration.is_minor is is_minor
    assert result["guardian"]["required"] is is_minor
    assert result["guardian"]["status"] == (
        "required_pending" if is_minor else "not_required"
    )
    assert result["access_mode"] == ("limited" if is_minor else "full")
    assert result["disabled_capabilities"] == (
        ["community", "sharing"] if is_minor else []
    )


def test_leap_day_and_offset_clock_use_one_unshifted_request_date(db_session):
    user, registration, _ = _seed(db_session)
    leap_minor = _personal(
        db_session,
        user,
        version=1,
        dob=date(2008, 2, 29),
        now=datetime(2026, 2, 28, 23, 30, tzinfo=timezone.utc),
    )
    assert leap_minor["guardian"] == {
        "required": True,
        "status": "required_pending",
    }
    leap_adult = _personal(
        db_session,
        user,
        version=2,
        dob=date(2008, 2, 29),
        now=datetime(2026, 3, 1, 0, 1, tzinfo=timezone.utc),
    )
    assert leap_adult["guardian"] == {"required": False, "status": "not_required"}

    offset_clock = datetime(
        2026,
        8,
        22,
        0,
        15,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )
    offset_adult = _personal(
        db_session,
        user,
        version=3,
        dob=date(2008, 8, 22),
        now=offset_clock,
    )
    db_session.refresh(registration)
    assert registration.is_minor is False
    assert offset_adult["guardian"]["status"] == "not_required"


def test_minor_to_adult_never_fabricates_guardian_verification(db_session):
    user, registration, _ = _seed(
        db_session, dob=date(2010, 1, 1), is_minor=True
    )
    guardian = db_session.scalar(
        select(GuardianConsent).where(
            GuardianConsent.registration_id == registration.id
        )
    )
    guardian.status = "verified"
    guardian.verified = True
    db_session.commit()

    result = _personal(
        db_session, user, version=1, dob=date(2000, 1, 1)
    )
    assert result["guardian"] == {"required": False, "status": "not_required"}
    assert result["access_mode"] == "full"


def test_verified_identity_dob_change_requires_unimplemented_step_up_with_zero_write(
    db_session,
):
    user, registration, profile = _seed(db_session)
    profile.institutional_email_hash = keyed_hash(
        "student@nls.ac.in", lower=True
    )
    profile.institutional_email_ct = encrypt("student@nls.ac.in")
    verification = StudentVerification(
        registration_id=registration.id,
        method="institutional_email",
        status="verified",
        verified_email_hash=profile.institutional_email_hash,
    )
    reviewer = User(role="legal_reviewer", status="active")
    db_session.add_all([verification, reviewer])
    db_session.flush()
    db_session.add(
        AuditEvent(
            actor_user_id=reviewer.id,
            actor_role="legal_reviewer",
            action="student.verification.status_changed",
            resource_type="student_verification",
            resource_id=verification.id,
            before_state={"status": "in_review"},
            after_state={"status": "verified", "profile_version": 1},
        )
    )
    db_session.commit()
    with pytest.raises(profile_service.ProfileBoundaryError) as caught:
        _personal(
            db_session, user, version=1, dob=date(2010, 1, 1)
        )
    assert (caught.value.status_code, caught.value.code) == (
        403,
        "dob_step_up_required",
    )
    db_session.expire_all()
    assert db_session.get(StudentProfile, profile.id).profile_version == 1
    assert db_session.get(StudentRegistration, registration.id).is_minor is False


def test_bare_forged_verification_positive_has_no_authority(db_session):
    user, registration, _ = _seed(db_session)
    verification = StudentVerification(
        registration_id=registration.id,
        method="institutional_email",
        status="verified",
        verified_email_hash="f" * 64,
    )
    db_session.add(verification)
    db_session.commit()

    projection = profile_service.projection_for_actor(db_session, user.id, now=NOW)
    assert projection["institutional_email_status"] == "not_provided"

    # Add a saved email to make the public status meaningful; the bare row
    # still has no authorized-review audit bound to this profile version.
    profile = profile_service.resolve_authority(db_session, user.id).profile
    profile.institutional_email_hash = keyed_hash("student@nls.ac.in", lower=True)
    profile.institutional_email_ct = encrypt("student@nls.ac.in")
    db_session.commit()
    projection = profile_service.projection_for_actor(db_session, user.id, now=NOW)
    assert projection["institutional_email_status"] == "revoked"

    changed = _personal(db_session, user, version=1, dob=date(2010, 1, 1))
    assert changed["profile_version"] == 2
    db_session.refresh(verification)
    assert verification.status == "revoked"


def test_verified_email_proof_survives_unrelated_profile_cas_and_drives_session_claims(
    db_session,
):
    user, registration, profile = _seed(db_session)
    raw_token = "verified-email-session"
    profile.institutional_email_hash = keyed_hash(
        "student@nls.ac.in", lower=True
    )
    profile.institutional_email_ct = encrypt("student@nls.ac.in")
    verification = StudentVerification(
        registration_id=registration.id,
        method="institutional_email",
        status="verified",
        verified_email_hash=profile.institutional_email_hash,
    )
    db_session.add_all(
        [
            verification,
            AuthSession(
                user_id=user.id,
                token_hash=keyed_hash(raw_token),
                status="active",
                expires_at=NOW + timedelta(hours=1),
                last_seen_at=NOW,
            ),
        ]
    )
    db_session.commit()

    projection = _personal(
        db_session, user, version=1, dob=date(2000, 1, 1)
    )
    assert projection["profile_version"] == 2
    assert projection["institutional_email_status"] == "verified"
    claims = login_service.session_claims(
        db_session, raw_token, NOW, touch=False
    )
    assert claims is not None
    assert claims["student_verification"] == "verified"

    changed = profile_service.update_academic(
        db_session,
        user.id,
        expected_profile_version=2,
        college="National Law School of India University",
        year_of_study="3rd",
        enrolment_number="KA/1234/2023",
        institutional_email="changed@nls.ac.in",
        bar_enrolment_number=None,
        now=NOW,
    )
    assert changed["institutional_email_status"] == "pending"
    db_session.refresh(verification)
    assert verification.status == "pending"
    assert verification.verified_email_hash is None
    claims = login_service.session_claims(
        db_session, raw_token, NOW, touch=False
    )
    assert claims is not None
    assert claims["student_verification"] == "draft"


def test_verified_row_without_email_proof_is_rejected_by_schema(db_session):
    _user, registration, _profile = _seed(db_session)
    db_session.add(
        StudentVerification(
            registration_id=registration.id,
            method="institutional_email",
            status="verified",
            verified_email_hash=None,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_real_two_session_cas_rejects_stale_dob_without_overwrite(db_session):
    user, registration, profile = _seed(db_session)
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    first = factory()
    second = factory()
    try:
        assert profile_service.resolve_authority(first, user.id).profile.profile_version == 1
        assert profile_service.resolve_authority(second, user.id).profile.profile_version == 1
        winner = _personal(
            first, user, version=1, dob=date(2010, 1, 1)
        )
        assert winner["guardian"]["required"] is True
        with pytest.raises(profile_service.ProfileVersionConflict) as caught:
            _personal(
                second, user, version=1, dob=date(2000, 1, 1)
            )
        assert caught.value.projection["profile_version"] == 2
        assert caught.value.projection["guardian"]["required"] is True
    finally:
        first.close()
        second.close()
    db_session.expire_all()
    assert db_session.get(StudentProfile, profile.id).profile_version == 2
    assert db_session.get(StudentRegistration, registration.id).is_minor is True


@pytest.mark.parametrize(
    "email",
    ["not-an-email", "student@gmail.com", f"{'a' * 250}@nls.ac.in"],
)
def test_direct_academic_service_rejects_invalid_institutional_email_atomically(
    db_session, email
):
    user, _, profile = _seed(db_session)
    _personal(db_session, user, version=1, dob=date(2000, 1, 1))
    with pytest.raises(profile_service.ProfileBoundaryError) as caught:
        profile_service.update_academic(
            db_session,
            user.id,
            expected_profile_version=2,
            college="National Law School of India University",
            year_of_study="3rd",
            enrolment_number="KA/123/2023",
            institutional_email=email,
            bar_enrolment_number=None,
            now=NOW,
        )
    assert (caught.value.status_code, caught.value.field) == (
        422,
        "institutional_email",
    )
    db_session.expire_all()
    assert db_session.get(StudentProfile, profile.id).profile_version == 2


def test_direct_academic_service_canonicalizes_legacy_college_and_year(db_session):
    user, _, _ = _seed(db_session)
    _personal(db_session, user, version=1, dob=date(2000, 1, 1))

    projection = profile_service.update_academic(
        db_session,
        user.id,
        expected_profile_version=2,
        college="National Law School of India University (NLSIU)",
        year_of_study="3rd year",
        enrolment_number="KA/1234/2023",
        institutional_email=None,
        bar_enrolment_number=None,
        now=NOW,
    )

    assert projection["profile"]["academic"]["college"] == (
        "National Law School of India University"
    )
    assert projection["profile"]["academic"]["year_of_study"] == "3rd"


@pytest.mark.parametrize(
    ("field", "value"),
    [("college", "Hogwarts School of Law"), ("year_of_study", "9th year")],
)
def test_direct_academic_service_rejects_noncanonical_college_and_year_atomically(
    db_session, field, value
):
    user, _, profile = _seed(db_session)
    _personal(db_session, user, version=1, dob=date(2000, 1, 1))
    payload = {
        "college": "National Law School of India University",
        "year_of_study": "3rd",
    }
    payload[field] = value

    with pytest.raises(profile_service.ProfileBoundaryError) as caught:
        profile_service.update_academic(
            db_session,
            user.id,
            expected_profile_version=2,
            **payload,
            enrolment_number="KA/1234/2023",
            institutional_email=None,
            bar_enrolment_number=None,
            now=NOW,
        )

    assert (caught.value.status_code, caught.value.field) == (422, field)
    db_session.expire_all()
    assert db_session.get(StudentProfile, profile.id).profile_version == 2


def _student_actor(user: User) -> ActorContext:
    return ActorContext(user_id=user.id, roles=frozenset({Role.STUDENT}))


def _direct_request() -> Request:
    return Request({"type": "http", "headers": []})


def _verified_credential(db_session, user: User) -> Credential:
    row = Credential(
        owner_user_id=user.id,
        issuer_id=None,
        title="Privacy certificate",
        credential_type="certificate",
        status="verified",
        issue_date=date(2026, 1, 1),
        expiry_date=None,
        key_version="v1",
        version=1,
        idempotency_key="nyay5-credential",
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_sharing_creation_is_denied_for_unproven_guardian_including_forged_verified(
    db_session,
):
    user, registration, _ = _seed(
        db_session, dob=date(2010, 1, 1), is_minor=True
    )
    guardian = db_session.scalar(
        select(GuardianConsent).where(
            GuardianConsent.registration_id == registration.id
        )
    )
    credential = _verified_credential(db_session, user)
    payload = credential_api.ShareProjectionCreate(fields=["title"])

    for status in ("pending", "rejected", "revoked"):
        guardian.status = status
        guardian.verified = False
        db_session.commit()
        before = db_session.query(CredentialShareProjection).count()
        with pytest.raises(HTTPException) as caught:
            credential_api.create_share_projection(
                credential.id,
                payload,
                _direct_request(),
                idempotency_key=f"projection-{status}",
                actor=_student_actor(user),
                session=db_session,
            )
        assert (caught.value.status_code, caught.value.detail["code"]) == (
            403,
            "guardian_verification_required",
        )
        assert db_session.query(CredentialShareProjection).count() == before

    # No approved guardian proof ceremony exists.  A bare database row cannot
    # manufacture guardian authority, even when it satisfies the legacy CHECK.
    guardian.status = "verified"
    guardian.verified = True
    db_session.commit()
    forged_projection = profile_service.projection_for_actor(
        db_session, user.id, now=NOW
    )
    assert forged_projection["guardian"] == {
        "required": True,
        "status": "revoked",
    }
    assert forged_projection["access_mode"] == "limited"
    before = db_session.query(CredentialShareProjection).count()
    with pytest.raises(HTTPException) as forged_denied:
        credential_api.create_share_projection(
            credential.id,
            payload,
            _direct_request(),
            idempotency_key="projection-forged-verified",
            actor=_student_actor(user),
            session=db_session,
        )
    assert (forged_denied.value.status_code, forged_denied.value.detail["code"]) == (
        403,
        "guardian_verification_required",
    )
    assert db_session.query(CredentialShareProjection).count() == before

    # Seed only the prerequisite projection to exercise the second positive
    # sharing operation independently; the forged guardian still grants none.
    projection = CredentialShareProjection(
        credential_id=credential.id,
        owner_user_id=user.id,
        fields_json=["title"],
        version=1,
        active=True,
        idempotency_key="fixture-only-projection",
    )
    db_session.add(projection)
    db_session.commit()
    token_payload = credential_api.VerificationTokenCreate(
        projection_id=str(projection.id), lifetime_days=1
    )
    with pytest.raises(HTTPException) as denied:
        credential_api.create_verification_token(
            credential.id,
            token_payload,
            _direct_request(),
            idempotency_key="token-forged-verified",
            actor=_student_actor(user),
            session=db_session,
        )
    assert (denied.value.status_code, denied.value.detail["code"]) == (
        403,
        "guardian_verification_required",
    )
    assert db_session.query(VerificationToken).count() == 0



def test_sharing_access_is_db_authoritative_for_adult_cross_user_and_ambiguity(
    db_session,
):
    user, registration, _ = _seed(db_session)
    credential = _verified_credential(db_session, user)
    payload = credential_api.ShareProjectionCreate(fields=["title"])
    adult = credential_api.create_share_projection(
        credential.id,
        payload,
        _direct_request(),
        idempotency_key="projection-adult",
        actor=_student_actor(user),
        session=db_session,
    )
    assert adult["active"] is True

    other = User(role="student", status="active")
    db_session.add(other)
    db_session.commit()
    with pytest.raises(HTTPException) as cross_user:
        credential_api.create_share_projection(
            credential.id,
            payload,
            _direct_request(),
            idempotency_key="projection-cross-user",
            actor=_student_actor(other),
            session=db_session,
        )
    assert cross_user.value.status_code == 404

    second = StudentRegistration(
        user_id=user.id,
        first_name="Ambiguous",
        middle_name=None,
        last_name="Owner",
        mobile_hash=keyed_hash("9123456780"),
        mobile_ct=encrypt("9123456780"),
        dob_hash=keyed_hash("2000-01-01"),
        dob_ct=encrypt("2000-01-01"),
        dob_hash_state="verified",
        key_version="v1",
        status="active",
        is_minor=False,
    )
    db_session.add(second)
    db_session.commit()
    with pytest.raises(HTTPException) as ambiguous:
        credential_api.create_share_projection(
            credential.id,
            payload,
            _direct_request(),
            idempotency_key="projection-ambiguous",
            actor=_student_actor(user),
            session=db_session,
        )
    assert (ambiguous.value.status_code, ambiguous.value.detail["code"]) == (
        403,
        "guardian_verification_required",
    )


@pytest.mark.parametrize("is_minor", [False, True])
def test_sharing_guard_locks_registration_then_guardian_before_decision(
    is_minor,
):
    """The direct-sharing decision serializes with DOB/guardian mutations."""

    user_id = uuid.uuid4()
    registration = StudentRegistration(
        id=uuid.uuid4(),
        user_id=user_id,
        first_name="Lock",
        last_name="Order",
        mobile_hash="m" * 64,
        mobile_ct="ciphertext",
        dob_hash="d" * 64,
        dob_ct="ciphertext",
        dob_hash_state="verified",
        key_version="v1",
        status="active",
        is_minor=is_minor,
    )
    guardian = GuardianConsent(
        id=uuid.uuid4(),
        registration_id=registration.id,
        status="pending",
        verified=False,
    )

    class RecordingSession:
        def __init__(self):
            self.statements = []

        def scalars(self, statement):
            self.statements.append(statement)
            return [registration] if len(self.statements) == 1 else [guardian]

    probe = RecordingSession()
    if is_minor:
        with pytest.raises(HTTPException):
            credential_api._require_current_sharing_access(
                probe, ActorContext(user_id=user_id, roles=frozenset({Role.STUDENT}))
            )
    else:
        credential_api._require_current_sharing_access(
            probe, ActorContext(user_id=user_id, roles=frozenset({Role.STUDENT}))
        )

    assert len(probe.statements) == (2 if is_minor else 1)
    assert all(
        statement._for_update_arg is not None
        for statement in probe.statements
    )


@pytest.mark.parametrize(
    ("operation", "payload"),
    [
        (
            credential_api.create_share_projection,
            credential_api.ShareProjectionCreate(fields=["title"]),
        ),
        (
            credential_api.create_verification_token,
            credential_api.VerificationTokenCreate(
                projection_id=uuid.uuid4(), lifetime_days=1
            ),
        ),
    ],
)
def test_sharing_mutations_lock_access_authority_before_credential_lookup(
    monkeypatch,
    operation,
    payload,
):
    calls = []

    def guard(*_args, **_kwargs):
        calls.append("authority")
        raise RuntimeError("stop after authority lock")

    def owned(*_args, **_kwargs):
        calls.append("credential")
        raise AssertionError("credential was read before authority lock")

    monkeypatch.setattr(credential_api, "_require_current_sharing_access", guard)
    monkeypatch.setattr(credential_api, "_get_owned", owned)

    with pytest.raises(RuntimeError, match="authority lock"):
        operation(
            uuid.uuid4(),
            payload,
            _direct_request(),
            idempotency_key="lock-order",
            actor=ActorContext(
                user_id=uuid.uuid4(), roles=frozenset({Role.STUDENT})
            ),
            session=object(),
        )
    assert calls == ["authority"]
