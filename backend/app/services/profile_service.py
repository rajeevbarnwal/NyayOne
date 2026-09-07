"""Server-authoritative student profile boundary (NYAY-5).

Identity remains normalized in ``student_registrations``.  This service is the
only profile projection/mutation authority and never accepts an owner selector
from the wire.
"""
from __future__ import annotations

import json
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.crypto import active_key_version, decrypt, encrypt, keyed_hash
from app.core.guardian_authority import has_authoritative_guardian_proof
from app.core.legal_name import normalize_legal_name
from app.core.institutional_email import normalize_institutional_email
from app.core.student_academic_profile import (
    canonical_college,
    canonical_year,
    normalize_college,
    normalize_year,
)
from app.core.student_verification_authority import (
    has_authoritative_institutional_email_proof,
)
from app.db.models.audit import AuditEvent
from app.models.registration import (
    AuthSession,
    AuthSessionProfilePrompt,
    GuardianConsent,
    ProfileMutationIdempotencyRecord,
    StudentProfile,
    StudentProfileGoal,
    StudentProfileInterest,
    StudentRegistration,
    StudentVerification,
    User,
)
from app.services import login_service, otp_service
from app.services.registration_service import _is_minor

COMPLETION_VERSION = "v1"
PROFILE_SECTIONS = ("personal", "academic", "interests")
DISABLED_MINOR_CAPABILITIES = ("community", "sharing")
PROFILE_REQUIREMENTS = (
    "personal.preferred_language",
    "personal.city",
    "academic.college",
    "academic.year_of_study",
    "academic.enrolment_number",
    "interests.interests",
    "interests.goals",
)
# v1 is the exact union of the two shipped secure generators: lowercase UUID
# and "profile-" plus lowercase hex. Keep the established length bounds; this
# alphabet rule does not claim to measure entropy of client-supplied strings.
PROFILE_IDEMPOTENCY_GRAMMAR_VERSION = "profile-key-alphabet.v1"
PROFILE_IDEMPOTENCY_ALPHABET = "-0123456789abcdefilopr"
_PROFILE_IDEMPOTENCY_KEY = re.compile(
    "[" + re.escape(PROFILE_IDEMPOTENCY_ALPHABET) + "]{16,200}"
)
_PROFILE_FINGERPRINT_VERSION = "v1"


class ProfileBoundaryError(RuntimeError):
    """Typed, non-echoing rejection suitable for an HTTP error body."""

    def __init__(self, status_code: int, code: str, *, field: str | None = None) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.field = field


class ProfileVersionConflict(ProfileBoundaryError):
    def __init__(self, projection: dict) -> None:
        super().__init__(409, "profile_version_conflict")
        self.projection = projection


class ProfileIdempotencyConflict(ProfileBoundaryError):
    """One actor/section key was already bound to a different request."""

    def __init__(self, section: str) -> None:
        super().__init__(409, "profile_idempotency_conflict")
        self.section = section


class ProfileMutationProjection(dict):
    """Wire projection carrying response-only replay metadata out of band."""

    replayed: bool

    def __init__(self, projection: dict, *, replayed: bool) -> None:
        super().__init__(projection)
        self.replayed = replayed


@dataclass(frozen=True)
class ProfileAuthority:
    registration: StudentRegistration
    profile: StudentProfile
    verification: StudentVerification | None = None
    guardian: GuardianConsent | None = None
    auth_session: AuthSession | None = None
    rows_locked: bool = False


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def completion_v1(
    personal_complete: bool,
    academic_complete: bool,
    interests_complete: bool,
) -> dict:
    """Return the only four completion-v1 states, always as a prefix."""

    completed_count = 0
    if personal_complete:
        completed_count = 1
        if academic_complete:
            completed_count = 2
            if interests_complete:
                completed_count = 3
    completed = list(PROFILE_SECTIONS[:completed_count])
    percentages = (0, 34, 67, 100)
    return {
        "completion_version": COMPLETION_VERSION,
        "completion_percent": percentages[completed_count],
        "completed_sections": completed,
        "next_incomplete_section": (
            PROFILE_SECTIONS[completed_count] if completed_count < 3 else None
        ),
        "is_complete": completed_count == 3,
    }


def _normalize_optional_text(
    value: str | None,
    *,
    maximum: int,
    field: str,
) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFC", value.strip())
    normalized = re.sub(r"\s+", " ", normalized)
    if not normalized:
        return None
    if len(normalized) > maximum:
        raise ProfileBoundaryError(422, "invalid_profile_field", field=field)
    return normalized


def normalize_list(values: Iterable[str], *, field: str) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = _normalize_optional_text(raw, maximum=80, field=field)
        if value is not None and value not in seen:
            seen.add(value)
            normalized.append(value)
    if len(normalized) > 20:
        raise ProfileBoundaryError(422, "too_many_profile_values", field=field)
    return normalized


def resolve_authority(
    session: Session,
    actor_user_id: uuid.UUID | None,
    *,
    for_update: bool = False,
    now: datetime | None = None,
    raw_session_token: str | None = None,
) -> ProfileAuthority:
    """Resolve exactly one live registration and exactly one normalized profile."""

    if actor_user_id is None:
        raise ProfileBoundaryError(401, "authentication_required")
    user = session.get(User, actor_user_id)
    if user is None or user.status != "active" or user.role != "student":
        raise ProfileBoundaryError(404, "profile_not_found")
    registration_query = (
        select(StudentRegistration)
        .where(
            StudentRegistration.user_id == actor_user_id,
            *otp_service.registration_authority_filters(),
        )
        .limit(2)
    )
    if for_update:
        registration_query = registration_query.with_for_update()
    registrations = list(session.scalars(registration_query))
    if len(registrations) != 1 or registrations[0].status != "active":
        raise ProfileBoundaryError(404, "profile_not_found")
    profile_query = (
        select(StudentProfile)
        .where(StudentProfile.registration_id == registrations[0].id)
        .limit(2)
    )
    if for_update:
        profile_query = profile_query.with_for_update()
    profiles = list(session.scalars(profile_query))
    if len(profiles) != 1:
        raise ProfileBoundaryError(404, "profile_not_found")
    verification = None
    guardian = None
    auth_session = None
    if for_update:
        # Shared mutation/reviewer order: registration -> profile ->
        # institutional verification -> guardian.  Every identity, academic,
        # and reviewer mutation acquires the same locks before inspecting state.
        verification = session.scalar(
            select(StudentVerification)
            .where(StudentVerification.registration_id == registrations[0].id)
            .with_for_update()
        )
        guardian = session.scalar(
            select(GuardianConsent)
            .where(GuardianConsent.registration_id == registrations[0].id)
            .with_for_update()
        )
        if raw_session_token is not None:
            if now is None:
                raise ProfileBoundaryError(401, "session_authority_required")
            auth_session = login_service.lock_presented_session_for_effect(
                session,
                raw_session_token,
                expected_user_id=registrations[0].user_id,
                now=now,
                allowed_roles=frozenset({"student"}),
            )
            if auth_session is None:
                raise ProfileBoundaryError(401, "session_authority_required")
    return ProfileAuthority(
        registration=registrations[0],
        profile=profiles[0],
        verification=verification,
        guardian=guardian,
        auth_session=auth_session,
        rows_locked=for_update,
    )


def lock_authority_for_review(
    session: Session,
    registration_id: uuid.UUID,
) -> ProfileAuthority:
    """Lock the same profile graph used by student mutations for review."""

    registration = session.scalar(
        select(StudentRegistration)
        .where(
            StudentRegistration.id == registration_id,
            *otp_service.registration_authority_filters(),
        )
        .with_for_update()
    )
    if registration is None:
        raise ProfileBoundaryError(404, "verification_not_found")
    profiles = list(
        session.scalars(
            select(StudentProfile)
            .where(StudentProfile.registration_id == registration.id)
            .limit(2)
            .with_for_update()
        )
    )
    if len(profiles) != 1:
        raise ProfileBoundaryError(404, "verification_not_found")
    verification = session.scalar(
        select(StudentVerification)
        .where(StudentVerification.registration_id == registration.id)
        .with_for_update()
    )
    guardian = session.scalar(
        select(GuardianConsent)
        .where(GuardianConsent.registration_id == registration.id)
        .with_for_update()
    )
    if verification is None:
        raise ProfileBoundaryError(404, "verification_not_found")
    return ProfileAuthority(
        registration=registration,
        profile=profiles[0],
        verification=verification,
        guardian=guardian,
        rows_locked=True,
    )


def _active_auth_session(
    session: Session,
    *,
    actor_user_id: uuid.UUID,
    raw_session_token: str | None,
    now: datetime,
    for_update: bool = False,
) -> AuthSession | None:
    if not raw_session_token:
        return None
    statement = select(AuthSession).where(
        AuthSession.user_id == actor_user_id,
        AuthSession.token_hash == keyed_hash(raw_session_token),
        AuthSession.status == "active",
        AuthSession.expires_at > _as_utc(now),
        AuthSession.deleted_at.is_(None),
    )
    if for_update:
        statement = statement.with_for_update().execution_options(
            populate_existing=True
        )
    return session.scalar(statement)


def _verification_status(
    session: Session,
    authority: ProfileAuthority,
    *, now: datetime | None = None,
) -> str:
    if authority.profile.institutional_email_ct is None:
        return "not_provided"
    from app.models.student_authority import AuthorityState
    from app.services.student_authority import institutional_is_current
    state = session.get(AuthorityState, authority.registration.id)
    if state is not None:
        if state.institutional_state == "VERIFIED":
            return "verified" if institutional_is_current(session, authority.registration.id, now=now or datetime.now(timezone.utc)) else "revoked"
        return {"UNVERIFIED": "pending", "PENDING": "pending", "REJECTED": "rejected", "EXPIRED": "expired", "REVOKED": "revoked"}[state.institutional_state]
    row = authority.verification if authority.rows_locked else session.scalar(
        select(StudentVerification).where(
            StudentVerification.registration_id == authority.registration.id
        )
    )
    if row is None or row.status in {"pending", "in_review"}:
        return "pending"
    if row.status == "verified":
        return (
            "verified"
            if verification_has_current_reviewer_provenance(session, authority, now=now)
            else "revoked"
        )
    if row.status in {"rejected", "expired", "revoked"}:
        return row.status
    return "pending"


def verification_has_current_reviewer_provenance(
    session: Session,
    authority: ProfileAuthority,
    *, now: datetime | None = None,
) -> bool:
    """Compatibility name for the shared persisted email-proof authority."""

    verification = authority.verification
    if verification is None:
        verification = session.scalar(
            select(StudentVerification).where(
                StudentVerification.registration_id == authority.registration.id
            )
        )
    return has_authoritative_institutional_email_proof(
        verification, authority.profile, now=now
    )


def _guardian_projection(session: Session, authority: ProfileAuthority, *, now: datetime | None = None) -> dict:
    registration = authority.registration
    from app.models.student_authority import AuthorityState
    from app.services.student_authority import guardian_is_current, is_minor
    state = session.get(AuthorityState, registration.id)
    if state is not None:
        request_now = now or datetime.now(timezone.utc)
        minor = is_minor(date.fromisoformat(decrypt(registration.dob_ct)), request_now.date())
        if not minor:
            return {"required": False, "status": "not_required"}
        if state.guardian_state == "VERIFIED":
            status = "verified" if guardian_is_current(session, registration.id, now=request_now) else "required_pending"
        else:
            status = {"NOT_REQUIRED": "required_pending", "REQUIRED_PENDING": "required_pending", "REJECTED": "rejected", "REVOKED": "revoked"}[state.guardian_state]
        return {"required": True, "status": status}
    if not registration.is_minor:
        return {"required": False, "status": "not_required"}
    row = authority.guardian if authority.rows_locked else session.scalar(
        select(GuardianConsent).where(
            GuardianConsent.registration_id == registration.id
        )
    )
    if row is not None and row.status == "verified" and row.verified:
        status = (
            "verified"
            if has_authoritative_guardian_proof(row)
            else "revoked"
        )
    elif row is not None and row.status == "rejected":
        status = "rejected"
    elif row is not None and row.status == "revoked":
        status = "revoked"
    elif row is None or row.status in {"pending", "sent"}:
        status = "required_pending"
    else:
        status = "required_pending"
    return {"required": True, "status": status}


def _profile_values(
    session: Session,
    profile_id: uuid.UUID,
    model: type[StudentProfileInterest] | type[StudentProfileGoal],
    *,
    for_update: bool = False,
) -> list[str]:
    statement = select(model.value).where(
        model.profile_id == profile_id, model.deleted_at.is_(None)
    )
    if for_update:
        statement = statement.with_for_update()
    values = list(session.scalars(statement))
    return sorted(values)


def _missing_requirements(
    authority: ProfileAuthority,
    *,
    interests: list[str],
    goals: list[str],
) -> list[str]:
    """Reduce the versioned field requirements from persisted owner state."""

    profile = authority.profile
    present = {
        "personal.preferred_language": profile.preferred_language in {"en", "hi"},
        "personal.city": bool(profile.city),
        "academic.college": bool(profile.college),
        "academic.year_of_study": bool(profile.year_of_study),
        "academic.enrolment_number": bool(profile.enrolment_ct),
        "interests.interests": bool(interests),
        "interests.goals": bool(goals),
    }
    return [
        requirement
        for requirement in PROFILE_REQUIREMENTS
        if not present[requirement]
    ]


def project(
    session: Session,
    authority: ProfileAuthority,
    *,
    now: datetime,
    raw_session_token: str | None = None,
) -> dict:
    """Build the exact authorized wire projection from persisted state."""

    registration = authority.registration
    profile = authority.profile
    interests = _profile_values(
        session,
        profile.id,
        StudentProfileInterest,
        for_update=authority.rows_locked,
    )
    goals = _profile_values(
        session,
        profile.id,
        StudentProfileGoal,
        for_update=authority.rows_locked,
    )
    personal_complete = bool(
        registration.first_name
        and registration.last_name
        and profile.preferred_language in {"en", "hi"}
        and profile.city
    )
    academic_complete = bool(
        profile.college and profile.year_of_study and profile.enrolment_ct
    )
    completion = completion_v1(
        personal_complete,
        academic_complete,
        bool(interests and goals),
    )
    auth_session = authority.auth_session
    if auth_session is None:
        auth_session = _active_auth_session(
            session,
            actor_user_id=registration.user_id,
            raw_session_token=raw_session_token,
            now=now,
            for_update=authority.rows_locked,
        )
    prompt_statement = select(AuthSessionProfilePrompt.id).where(
        AuthSessionProfilePrompt.auth_session_id == (
            auth_session.id if auth_session is not None else None
        )
    )
    if authority.rows_locked:
        prompt_statement = prompt_statement.with_for_update()
    dismissed = bool(
        auth_session
        and session.scalar(prompt_statement)
    )
    guardian = _guardian_projection(session, authority, now=now)
    limited = guardian["required"] and guardian["status"] != "verified"
    return {
        "profile_version": profile.profile_version,
        **completion,
        "missing_requirements": _missing_requirements(
            authority,
            interests=interests,
            goals=goals,
        ),
        "institutional_email_status": _verification_status(session, authority, now=now),
        "guardian": guardian,
        "access_mode": "limited" if limited else "full",
        "disabled_capabilities": list(DISABLED_MINOR_CAPABILITIES) if limited else [],
        "profile_prompt": {
            "should_show": not completion["is_complete"] and not dismissed,
            "dismissed_for_session": dismissed,
        },
        "profile": {
            "personal": {
                "first_name": registration.first_name,
                "middle_name": registration.middle_name,
                "last_name": registration.last_name,
                "date_of_birth": decrypt(registration.dob_ct),
                "preferred_language": profile.preferred_language,
                "city": profile.city,
                "pronouns": profile.pronouns,
            },
            "academic": {
                "college": canonical_college(profile.college),
                "year_of_study": canonical_year(profile.year_of_study),
                "enrolment_number": (
                    decrypt(profile.enrolment_ct) if profile.enrolment_ct else None
                ),
                "institutional_email": (
                    decrypt(profile.institutional_email_ct)
                    if profile.institutional_email_ct
                    else None
                ),
                "bar_enrolment_number": (
                    decrypt(profile.bar_enrolment_ct)
                    if profile.bar_enrolment_ct
                    else None
                ),
            },
            "interests": {"interests": interests, "goals": goals},
        },
    }


def projection_for_actor(
    session: Session,
    actor_user_id: uuid.UUID | None,
    *,
    now: datetime,
    raw_session_token: str | None = None,
) -> dict:
    return project(
        session,
        resolve_authority(
            session,
            actor_user_id,
            for_update=True,
            now=now,
            raw_session_token=raw_session_token,
        ),
        now=now,
        raw_session_token=raw_session_token,
    )


def export_profile_for_actor(
    session: Session,
    actor_user_id: uuid.UUID | None,
    *,
    now: datetime,
) -> dict:
    """Materialize the complete owner profile through an explicit export allowlist."""

    projection = projection_for_actor(session, actor_user_id, now=now)
    profile = projection["profile"]
    personal = profile["personal"]
    academic = profile["academic"]
    interests = profile["interests"]
    return {
        "schema_version": "student-profile-export.v1",
        "profile_version": projection["profile_version"],
        "profile": {
            "personal": {
                "first_name": personal["first_name"],
                "middle_name": personal["middle_name"],
                "last_name": personal["last_name"],
                "date_of_birth": personal["date_of_birth"],
                "preferred_language": personal["preferred_language"],
                "city": personal["city"],
                "pronouns": personal["pronouns"],
            },
            "academic": {
                "college": academic["college"],
                "year_of_study": academic["year_of_study"],
                "enrolment_number": academic["enrolment_number"],
                "institutional_email": academic["institutional_email"],
                "bar_enrolment_number": academic["bar_enrolment_number"],
            },
            "interests": {
                "interests": interests["interests"],
                "goals": interests["goals"],
            },
        },
    }


def materialize_student_privacy_export(
    session: Session,
    actor_user_id: uuid.UUID | None,
    *,
    now: datetime,
) -> dict:
    """Compose the closed owner-profile and mentor-history export allowlists."""

    owner_profile = export_profile_for_actor(
        session,
        actor_user_id,
        now=now,
    )
    registration_id = session.scalar(
        select(StudentRegistration.id).where(
            StudentRegistration.user_id == actor_user_id,
            StudentRegistration.deleted_at.is_(None),
        )
    )
    if registration_id is None:
        raise ProfileBoundaryError(404, "profile_not_found")
    # Local import avoids creating a second identity system or a module cycle.
    from app.services.mentor_ceremony import (
        materialize_subject_mentor_privacy_export,
    )

    mentor = materialize_subject_mentor_privacy_export(
        session,
        registration_id,
    )
    result = {
        "schema_version": "student-data-export.v1",
        "profile_version": owner_profile["profile_version"],
        "profile": owner_profile["profile"],
        "mentor_history": mentor["mentor_history"],
    }
    from app.services.student_authority import export_owner_authority
    authority_history = export_owner_authority(session, actor_user_id)
    if authority_history:
        result["authority_history"] = authority_history
    return result


def validate_profile_idempotency_key(value: str | None) -> str:
    """Require one opaque, bounded, non-PII profile mutation token."""

    if (
        not isinstance(value, str)
        or _PROFILE_IDEMPOTENCY_KEY.fullmatch(value) is None
    ):
        raise ProfileBoundaryError(
            422,
            "invalid_idempotency_key",
            field="Idempotency-Key",
        )
    return value


def _profile_idempotency_key_hash(value: str) -> str:
    return keyed_hash(f"profile-mutation-idempotency-key:v1:{value}")


def _profile_request_fingerprint(section: str, payload: dict) -> str:
    encoded = json.dumps(
        {"section": section, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return keyed_hash(f"profile-mutation-request:v1:{encoded}")


def _decode_replay(record: ProfileMutationIdempotencyRecord) -> dict:
    if (
        record.state != "succeeded"
        or record.outcome_status != 200
        or record.outcome_ct is None
        or record.key_version is None
        or record.profile_version is None
    ):
        raise ProfileBoundaryError(409, "profile_idempotency_replay_unavailable")
    try:
        decoded = json.loads(decrypt(record.outcome_ct))
    except (TypeError, ValueError):
        raise ProfileBoundaryError(
            409, "profile_idempotency_replay_unavailable"
        ) from None
    if (
        not isinstance(decoded, dict)
        or decoded.get("profile_version") != record.profile_version
    ):
        raise ProfileBoundaryError(409, "profile_idempotency_replay_unavailable")
    return decoded


def _begin_profile_mutation(
    session: Session,
    authority: ProfileAuthority,
    *,
    section: str,
    idempotency_key: str | None,
    fingerprint_payload: dict,
) -> tuple[ProfileMutationIdempotencyRecord | None, ProfileMutationProjection | None]:
    """Resolve replay/conflict before any profile version or field mutation.

    Trusted internal callers remain compatible when no key is supplied; every
    HTTP mutation boundary requires and validates the header before reaching
    this seam.  PostgreSQL serializes requests on the already-locked profile
    graph, so the unique ledger scope has one deterministic winner.
    """

    if idempotency_key is None:
        return None, None
    key = validate_profile_idempotency_key(idempotency_key)
    key_hash = _profile_idempotency_key_hash(key)
    fingerprint = _profile_request_fingerprint(section, fingerprint_payload)
    actor_user_id = authority.registration.user_id
    record = session.scalar(
        select(ProfileMutationIdempotencyRecord)
        .where(
            ProfileMutationIdempotencyRecord.actor_user_id == actor_user_id,
            ProfileMutationIdempotencyRecord.section == section,
            ProfileMutationIdempotencyRecord.idempotency_key_hash == key_hash,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if record is not None:
        if (
            record.request_fingerprint_version != _PROFILE_FINGERPRINT_VERSION
            or record.request_fingerprint != fingerprint
        ):
            raise ProfileIdempotencyConflict(section)
        if record.state == "succeeded":
            return None, ProfileMutationProjection(
                _decode_replay(record), replayed=True
            )
        if record.state == "erased":
            raise ProfileBoundaryError(409, "profile_idempotency_replay_expired")
        raise ProfileBoundaryError(409, "profile_mutation_in_progress")

    record = ProfileMutationIdempotencyRecord(
        actor_user_id=actor_user_id,
        section=section,
        idempotency_key_hash=key_hash,
        request_fingerprint=fingerprint,
        request_fingerprint_version=_PROFILE_FINGERPRINT_VERSION,
        state="pending",
    )
    session.add(record)
    session.flush()
    return record, None


def _seal_profile_mutation_outcome(
    record: ProfileMutationIdempotencyRecord,
    projection: dict,
    *,
    now: datetime,
) -> None:
    encoded = json.dumps(
        projection,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    record.state = "succeeded"
    record.outcome_status = 200
    record.outcome_ct = encrypt(encoded)
    record.key_version = active_key_version()
    record.profile_version = int(projection["profile_version"])
    record.updated_at = _as_utc(now)


def _audit_success(
    session: Session,
    *,
    actor_user_id: uuid.UUID,
    section: str,
    profile_version: int,
    guardian_required: bool,
) -> None:
    session.add(
        AuditEvent(
            actor_user_id=actor_user_id,
            actor_role="student",
            action="student.profile.section_updated",
            resource_type="student_profile",
            resource_id=None,
            after_state={
                "outcome": "succeeded",
                "section": section,
                "profile_version": profile_version,
                "guardian_required": guardian_required,
            },
        )
    )


def _cas(
    session: Session,
    authority: ProfileAuthority,
    expected_profile_version: int,
    *,
    now: datetime,
    raw_session_token: str | None,
) -> int:
    result = session.execute(
        update(StudentProfile)
        .where(
            StudentProfile.id == authority.profile.id,
            StudentProfile.profile_version == expected_profile_version,
        )
        .values(profile_version=StudentProfile.profile_version + 1)
        .returning(StudentProfile.profile_version),
        execution_options={"synchronize_session": False},
    ).scalar_one_or_none()
    if result is None:
        actor_user_id = authority.registration.user_id
        session.rollback()
        raise ProfileVersionConflict(
            projection_for_actor(
                session,
                actor_user_id,
                now=now,
                raw_session_token=raw_session_token,
            )
        )
    session.expire(authority.profile)
    session.refresh(authority.profile)
    return int(result)


def _require_expected_profile_version(
    session: Session,
    authority: ProfileAuthority,
    expected_profile_version: int,
    *,
    now: datetime,
    raw_session_token: str | None,
) -> None:
    """Expose an authoritative conflict before evaluating later-step state.

    ``resolve_authority(..., for_update=True)`` already holds the canonical
    profile row lock.  A stale later-section writer must therefore receive the
    current projection even when the winning write also regressed a section
    prerequisite; only a writer that has deliberately adopted that version is
    eligible for the prerequisite decision.
    """

    if authority.profile.profile_version == expected_profile_version:
        return
    actor_user_id = authority.registration.user_id
    session.rollback()
    raise ProfileVersionConflict(
        projection_for_actor(
            session,
            actor_user_id,
            now=now,
            raw_session_token=raw_session_token,
        )
    )


def _remove_completed_prompt(
    session: Session,
    *,
    authority: ProfileAuthority,
    projection: dict,
) -> bool:
    if not projection["is_complete"]:
        return False
    auth_session = authority.auth_session
    if auth_session is not None:
        result = session.execute(
            delete(AuthSessionProfilePrompt).where(
                AuthSessionProfilePrompt.auth_session_id == auth_session.id
            )
        )
        return bool(result.rowcount)
    return False


def _commit_projection(
    session: Session,
    authority: ProfileAuthority,
    *,
    now: datetime,
    raw_session_token: str | None,
    section: str,
    idempotency_record: ProfileMutationIdempotencyRecord | None = None,
) -> dict:
    projected = project(
        session, authority, now=now, raw_session_token=raw_session_token
    )
    _remove_completed_prompt(
        session,
        authority=authority,
        projection=projected,
    )
    session.flush()
    projected = project(
        session, authority, now=now, raw_session_token=raw_session_token
    )
    _audit_success(
        session,
        actor_user_id=authority.registration.user_id,
        section=section,
        profile_version=authority.profile.profile_version,
        guardian_required=authority.registration.is_minor,
    )
    if idempotency_record is not None:
        _seal_profile_mutation_outcome(
            idempotency_record,
            projected,
            now=now,
        )
        session.flush()
    session.commit()
    return ProfileMutationProjection(projected, replayed=False)


def _current_completion(session: Session, authority: ProfileAuthority, *, now: datetime) -> list[str]:
    return project(session, authority, now=now)["completed_sections"]


def update_personal(
    session: Session,
    actor_user_id: uuid.UUID | None,
    *,
    expected_profile_version: int,
    first_name: str,
    middle_name: str | None,
    last_name: str,
    date_of_birth: date,
    preferred_language: str | None,
    city: str | None,
    pronouns: str | None,
    now: datetime,
    raw_session_token: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    authority = resolve_authority(
        session,
        actor_user_id,
        for_update=True,
        now=now,
        raw_session_token=raw_session_token,
    )
    if expected_profile_version < 1:
        raise ProfileBoundaryError(
            422, "invalid_expected_profile_version", field="expected_profile_version"
        )
    try:
        normalized_first = normalize_legal_name(first_name)
        normalized_middle = (
            normalize_legal_name(middle_name) if middle_name is not None else None
        )
        normalized_last = normalize_legal_name(last_name)
    except ValueError as exc:
        raise ProfileBoundaryError(422, "invalid_legal_name", field="first_name") from exc
    if preferred_language not in {None, "en", "hi"}:
        raise ProfileBoundaryError(
            422, "invalid_profile_field", field="preferred_language"
        )
    normalized_city = _normalize_optional_text(city, maximum=120, field="city")
    normalized_pronouns = _normalize_optional_text(
        pronouns, maximum=60, field="pronouns"
    )
    # DOB is a calendar date. Use the caller's single injected request-clock
    # date directly; converting its timezone could shift the civil day.
    request_date = now.date()
    if date_of_birth > request_date:
        raise ProfileBoundaryError(422, "invalid_date_of_birth", field="date_of_birth")

    idempotency_record, replay = _begin_profile_mutation(
        session,
        authority,
        section="personal",
        idempotency_key=idempotency_key,
        fingerprint_payload={
            "expected_profile_version": expected_profile_version,
            "first_name": normalized_first,
            "middle_name": normalized_middle,
            "last_name": normalized_last,
            "date_of_birth": date_of_birth.isoformat(),
            "preferred_language": preferred_language,
            "city": normalized_city,
            "pronouns": normalized_pronouns,
        },
    )
    if replay is not None:
        session.commit()
        return replay

    registration = authority.registration
    current_dob = date.fromisoformat(decrypt(registration.dob_ct))
    dob_changed = current_dob != date_of_birth
    if dob_changed:
        from app.services.student_authority import AuthorityError, identity_changed
        try:
            identity_changed(session, registration, "date_of_birth", now)
        except AuthorityError as exc:
            raise ProfileBoundaryError(exc.status_code, exc.code) from exc
        verification = authority.verification
        if verification_has_current_reviewer_provenance(session, authority, now=now):
            # No approved student step-up ceremony exists yet. Fail closed and
            # leave the verified identity boundary untouched.
            raise ProfileBoundaryError(403, "dob_step_up_required", field="date_of_birth")
        if verification is not None and verification.status == "verified":
            verification.status = "revoked"
            verification.verified_email_hash = None

    _cas(
        session,
        authority,
        expected_profile_version,
        now=now,
        raw_session_token=raw_session_token,
    )
    registration.first_name = normalized_first
    registration.middle_name = normalized_middle
    registration.last_name = normalized_last
    authority.profile.preferred_language = preferred_language
    authority.profile.city = normalized_city
    authority.profile.pronouns = normalized_pronouns

    previous_minor = registration.is_minor
    new_minor = _is_minor(date_of_birth, request_date)
    if dob_changed:
        registration.dob_hash = keyed_hash(date_of_birth.isoformat())
        registration.dob_ct = encrypt(date_of_birth.isoformat())
        registration.key_version = active_key_version()
    registration.is_minor = new_minor
    from app.models.student_authority import AuthorityState
    from app.services.student_authority import settle_state
    state = session.get(AuthorityState, registration.id)
    if state is not None:
        settle_state(session, registration, state, now)
    if new_minor and not previous_minor:
        guardian = authority.guardian
        if guardian is None:
            session.add(
                GuardianConsent(
                    registration_id=registration.id,
                    status="pending",
                    verified=False,
                )
            )
        else:
            # A prior ceremony cannot silently carry across a new
            # adult-to-minor identity decision.
            guardian.status = "pending"
            guardian.verified = False

    session.flush()
    return _commit_projection(
        session,
        authority,
        now=now,
        raw_session_token=raw_session_token,
        section="personal",
        idempotency_record=idempotency_record,
    )


def update_academic(
    session: Session,
    actor_user_id: uuid.UUID | None,
    *,
    expected_profile_version: int,
    college: str | None,
    year_of_study: str | None,
    enrolment_number: str | None,
    institutional_email: str | None,
    bar_enrolment_number: str | None,
    now: datetime,
    raw_session_token: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    authority = resolve_authority(
        session,
        actor_user_id,
        for_update=True,
        now=now,
        raw_session_token=raw_session_token,
    )
    normalized_college_text = _normalize_optional_text(
        college, maximum=160, field="college"
    )
    normalized_year_text = _normalize_optional_text(
        year_of_study, maximum=40, field="year_of_study"
    )
    try:
        normalized_college = normalize_college(normalized_college_text)
    except ValueError as exc:
        raise ProfileBoundaryError(
            422, "invalid_profile_field", field="college"
        ) from exc
    try:
        normalized_year = normalize_year(normalized_year_text)
    except ValueError as exc:
        raise ProfileBoundaryError(
            422, "invalid_profile_field", field="year_of_study"
        ) from exc
    normalized_enrolment = _normalize_optional_text(
        enrolment_number, maximum=120, field="enrolment_number"
    )
    normalized_email = _normalize_optional_text(
        institutional_email, maximum=254, field="institutional_email"
    )
    try:
        normalized_email = normalize_institutional_email(normalized_email)
    except ValueError as exc:
        raise ProfileBoundaryError(
            422, "invalid_profile_field", field="institutional_email"
        ) from exc
    normalized_bar = _normalize_optional_text(
        bar_enrolment_number, maximum=120, field="bar_enrolment_number"
    )

    idempotency_record, replay = _begin_profile_mutation(
        session,
        authority,
        section="academic",
        idempotency_key=idempotency_key,
        fingerprint_payload={
            "expected_profile_version": expected_profile_version,
            "college": normalized_college,
            "year_of_study": normalized_year,
            "enrolment_number": normalized_enrolment,
            "institutional_email": normalized_email,
            "bar_enrolment_number": normalized_bar,
        },
    )
    if replay is not None:
        session.commit()
        return replay
    _require_expected_profile_version(
        session,
        authority,
        expected_profile_version,
        now=now,
        raw_session_token=raw_session_token,
    )
    if "personal" not in _current_completion(session, authority, now=now):
        raise ProfileBoundaryError(409, "profile_section_prerequisite_incomplete")

    _cas(
        session,
        authority,
        expected_profile_version,
        now=now,
        raw_session_token=raw_session_token,
    )
    profile = authority.profile
    old_email_hash = profile.institutional_email_hash
    profile.college = normalized_college
    profile.year_of_study = normalized_year
    profile.enrolment_ct = encrypt(normalized_enrolment) if normalized_enrolment else None
    profile.enrolment_hash = keyed_hash(normalized_enrolment) if normalized_enrolment else None
    profile.institutional_email_ct = encrypt(normalized_email) if normalized_email else None
    profile.institutional_email_hash = (
        keyed_hash(normalized_email, lower=True) if normalized_email else None
    )
    profile.bar_enrolment_ct = encrypt(normalized_bar) if normalized_bar else None
    profile.bar_enrolment_hash = keyed_hash(normalized_bar) if normalized_bar else None
    profile.key_version = active_key_version()
    authority.registration.institution_ref = normalized_college
    if old_email_hash != profile.institutional_email_hash:
        from app.services.student_authority import AuthorityError, identity_changed
        try:
            identity_changed(session, authority.registration, "institutional_email", now)
        except AuthorityError as exc:
            raise ProfileBoundaryError(exc.status_code, exc.code) from exc
        verification = authority.verification
        if verification is None:
            session.add(
                StudentVerification(
                    registration_id=authority.registration.id,
                    method="institutional_email",
                    status="pending",
                )
            )
        else:
            verification.status = "pending"
            verification.verified_email_hash = None
    session.flush()
    return _commit_projection(
        session,
        authority,
        now=now,
        raw_session_token=raw_session_token,
        section="academic",
        idempotency_record=idempotency_record,
    )


def request_institutional_email_verification(
    session: Session,
    actor_user_id: uuid.UUID | None,
    *,
    now: datetime,
    raw_session_token: str | None = None,
) -> dict:
    """Record one non-authorizing review request for the current saved email.

    The request carries no email or owner selector.  Locking the canonical
    profile graph means an academic email change either wins first (and this
    request binds to the new current email) or wins second (and resets the
    request back to pending).  ``in_review`` is retained only as internal
    lifecycle detail; the public projection deliberately remains ``pending``.
    """

    authority = resolve_authority(
        session,
        actor_user_id,
        for_update=True,
        now=now,
        raw_session_token=raw_session_token,
    )
    if (
        authority.profile.institutional_email_ct is None
        or authority.profile.institutional_email_hash is None
    ):
        raise ProfileBoundaryError(
            422,
            "institutional_email_required",
            field="institutional_email",
        )
    verification = authority.verification
    if verification is None:
        raise ProfileBoundaryError(404, "verification_not_found")

    already_authoritative = verification_has_current_reviewer_provenance(
        session, authority, now=now
    )
    from app.models.student_authority import AuthorityState
    from app.services.student_authority import apply_transition
    state = session.get(AuthorityState, authority.registration.id)
    if state is not None and not already_authoritative and state.institutional_state in {"UNVERIFIED", "REJECTED", "EXPIRED", "REVOKED"}:
        apply_transition(session, state, machine="institutional", target="PENDING", trigger="student_review_request", authority="student", now=now)
        from datetime import timedelta
        state.review_due_at = now + timedelta(days=7)
    if not already_authoritative and verification.status != "in_review":
        verification.status = "in_review"
        verification.verified_email_hash = None
        session.add(
            AuditEvent(
                actor_user_id=authority.registration.user_id,
                actor_role="student",
                action="student.verification.email_requested",
                resource_type="student_verification_request",
                resource_id=None,
                after_state={
                    "outcome": "accepted",
                    "status": "pending",
                    "profile_version": authority.profile.profile_version,
                },
            )
        )
        session.flush()

    projected = project(
        session,
        authority,
        now=now,
        raw_session_token=raw_session_token,
    )
    session.commit()
    return projected


def update_interests(
    session: Session,
    actor_user_id: uuid.UUID | None,
    *,
    expected_profile_version: int,
    interests: Iterable[str],
    goals: Iterable[str],
    now: datetime,
    raw_session_token: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    authority = resolve_authority(
        session,
        actor_user_id,
        for_update=True,
        now=now,
        raw_session_token=raw_session_token,
    )
    normalized_interests = normalize_list(interests, field="interests")
    normalized_goals = normalize_list(goals, field="goals")
    idempotency_record, replay = _begin_profile_mutation(
        session,
        authority,
        section="interests",
        idempotency_key=idempotency_key,
        fingerprint_payload={
            "expected_profile_version": expected_profile_version,
            "interests": sorted(normalized_interests),
            "goals": sorted(normalized_goals),
        },
    )
    if replay is not None:
        session.commit()
        return replay
    _require_expected_profile_version(
        session,
        authority,
        expected_profile_version,
        now=now,
        raw_session_token=raw_session_token,
    )
    completed = _current_completion(session, authority, now=now)
    if completed[:2] != ["personal", "academic"]:
        raise ProfileBoundaryError(409, "profile_section_prerequisite_incomplete")
    _cas(
        session,
        authority,
        expected_profile_version,
        now=now,
        raw_session_token=raw_session_token,
    )
    session.execute(
        delete(StudentProfileInterest).where(
            StudentProfileInterest.profile_id == authority.profile.id
        )
    )
    session.execute(
        delete(StudentProfileGoal).where(
            StudentProfileGoal.profile_id == authority.profile.id
        )
    )
    session.add_all(
        StudentProfileInterest(profile_id=authority.profile.id, value=value)
        for value in normalized_interests
    )
    session.add_all(
        StudentProfileGoal(profile_id=authority.profile.id, value=value)
        for value in normalized_goals
    )
    session.flush()
    return _commit_projection(
        session,
        authority,
        now=now,
        raw_session_token=raw_session_token,
        section="interests",
        idempotency_record=idempotency_record,
    )


def dismiss_prompt(
    session: Session,
    actor_user_id: uuid.UUID | None,
    *,
    now: datetime,
    raw_session_token: str | None,
) -> dict:
    authority = resolve_authority(
        session,
        actor_user_id,
        for_update=True,
        now=now,
        raw_session_token=raw_session_token,
    )
    auth_session = authority.auth_session
    if auth_session is None:
        raise ProfileBoundaryError(401, "session_authority_required")
    values = {
        "auth_session_id": auth_session.id,
        "dismissed_at": _as_utc(now),
    }
    dialect = session.get_bind().dialect.name
    inserted: uuid.UUID | None
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert

        inserted = session.execute(
            dialect_insert(AuthSessionProfilePrompt)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["auth_session_id"])
            .returning(AuthSessionProfilePrompt.id)
        ).scalar_one_or_none()
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as dialect_insert

        inserted = session.execute(
            dialect_insert(AuthSessionProfilePrompt)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["auth_session_id"])
            .returning(AuthSessionProfilePrompt.id)
        ).scalar_one_or_none()
    else:  # pragma: no cover - supported production/test dialects are above.
        existing = session.scalar(
            select(AuthSessionProfilePrompt.id).where(
                AuthSessionProfilePrompt.auth_session_id == auth_session.id
            )
        )
        inserted = None
        if existing is None:
            row = AuthSessionProfilePrompt(**values)
            session.add(row)
            session.flush()
            inserted = row.id

    if inserted is not None:
        session.add(
            AuditEvent(
                actor_user_id=authority.registration.user_id,
                actor_role="student",
                action="student.profile.prompt_dismissed",
                resource_type="auth_session_profile_prompt",
                resource_id=None,
                after_state={"outcome": "succeeded", "scope": "auth_session"},
            )
        )
    projected = project(
        session,
        authority,
        now=now,
        raw_session_token=raw_session_token,
    )
    session.commit()
    return projected
