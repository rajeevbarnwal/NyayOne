"""Server-owned guardian/institutional state machines (NYAY-11 policy 14714).

Public handlers accept commands, never states or authority labels. Registration
locks precede proof/session locks. Ordinary commands are caller-owned
transactions. Email-proof delivery intentionally commits its pending state
before external delivery and its receipt afterward; denied email-proof
verification commits attempt accounting and audit before raising. These
explicit exceptions preserve fail-closed delivery and retry accounting.
"""
from __future__ import annotations

import calendar
import hmac
import json
import re
import secrets
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.crypto import decrypt, encrypt, keyed_hash
from app.models.registration import GuardianConsent, StudentProfile, StudentRegistration, StudentVerification, User
from app.models.student_authority import (
    GUARDIAN_STATES, INSTITUTIONAL_STATES, AuthorityAuditEvent,
    AuthorityMutationRecord, AuthorityNotification, AuthorityState,
    GuardianInvitation, InstitutionalEmailProof, InstitutionalReviewerAssignment,
)
from app.services import login_service, otp_service

POLICY_VERSION = "NYAY-11-v1"
GUARDIAN_MAP = {"pending": "REQUIRED_PENDING", "sent": "REQUIRED_PENDING", "verified": "VERIFIED", "rejected": "REJECTED", "revoked": "REVOKED"}
INSTITUTIONAL_MAP = {"pending": "UNVERIFIED", "in_review": "PENDING", "verified": "VERIFIED", "rejected": "REJECTED", "expired": "EXPIRED", "revoked": "REVOKED"}
# Each trigger has exactly one authority class, except immediate revocation.
EDGES = {
    "guardian": {
        ("NOT_REQUIRED", "REQUIRED_PENDING"): {"adult_to_minor": {"server_age_policy"}},
        ("REQUIRED_PENDING", "NOT_REQUIRED"): {"minor_to_adult": {"server_age_policy"}},
        ("REQUIRED_PENDING", "VERIFIED"): {"guardian_proof_completed": {"server_attested_guardian"}},
        ("REQUIRED_PENDING", "REJECTED"): {"guardian_declined": {"server_attested_guardian"}},
        ("REQUIRED_PENDING", "REVOKED"): {"guardian_or_owner_revocation": {"guardian", "owner"}},
        ("VERIFIED", "NOT_REQUIRED"): {"minor_to_adult": {"server_age_policy"}},
        ("VERIFIED", "REQUIRED_PENDING"): {"proof_expired": {"server_clock"}, "dependent_identity_changed": {"server_profile_policy"}},
        ("VERIFIED", "REVOKED"): {"guardian_or_owner_revocation": {"guardian", "owner"}},
        ("REJECTED", "NOT_REQUIRED"): {"minor_to_adult": {"server_age_policy"}},
        ("REJECTED", "REQUIRED_PENDING"): {"new_guardian_request": {"student"}},
        ("REVOKED", "NOT_REQUIRED"): {"minor_to_adult": {"server_age_policy"}},
        ("REVOKED", "REQUIRED_PENDING"): {"new_guardian_request": {"student"}},
    },
    "institutional": {
        ("UNVERIFIED", "PENDING"): {"student_review_request": {"student"}},
        ("PENDING", "VERIFIED"): {"assigned_review_approved": {"assigned_institutional_reviewer"}},
        ("PENDING", "REJECTED"): {"assigned_review_rejected": {"assigned_institutional_reviewer"}},
        ("VERIFIED", "PENDING"): {"dependent_identity_changed": {"server_profile_policy"}},
        ("VERIFIED", "EXPIRED"): {"verification_expired": {"server_clock"}},
        ("VERIFIED", "REVOKED"): {"owner_break_glass": {"platform_owner"}},
        ("REJECTED", "PENDING"): {"student_review_request": {"student"}},
        ("EXPIRED", "PENDING"): {"student_review_request": {"student"}},
        ("REVOKED", "PENDING"): {"student_review_request": {"student"}},
    },
}


class AuthorityError(RuntimeError):
    def __init__(self, code="authority_denied", status_code=403, *, current_profile_version=None):
        super().__init__(code)
        self.code, self.status_code = code, status_code
        self.current_profile_version = current_profile_version


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def is_minor(born: date, today: date) -> bool:
    if born > today:
        raise AuthorityError("invalid_date_of_birth", 422)
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day)) < 18


def guardian_deadline(now: datetime) -> datetime:
    # P12M is a calendar period; Feb 29 clamps to Feb 28 in the next year.
    return now.replace(year=now.year + 1, day=min(now.day, calendar.monthrange(now.year + 1, now.month)[1]))


def map_legacy(machine: str, state: str) -> str:
    mapping = {"guardian": GUARDIAN_MAP, "institutional": INSTITUTIONAL_MAP}.get(machine, {})
    if state not in mapping:
        raise AuthorityError("legacy_authority_unmapped", 409)
    return mapping[state]


def evaluate_transition(machine: str, source: str, target: str, trigger: str, authority: str) -> str:
    states = {"guardian": GUARDIAN_STATES, "institutional": INSTITUTIONAL_STATES}.get(machine, ())
    if source not in states or target not in states:
        raise AuthorityError()
    if source == target:
        if authority == "server" and (trigger == "exact_idempotent_replay" or (machine == "institutional" and source == "PENDING" and trigger == "reviewer_timeout_return_to_queue")):
            return "STATE_STABLE"
        raise AuthorityError()
    if authority not in EDGES[machine].get((source, target), {}).get(trigger, set()):
        raise AuthorityError()
    return "ALLOWED"


def _audit(session, purpose, code, authority, now):
    actors = {"student": "student", "server_attested_guardian": "guardian", "guardian": "guardian", "owner": "owner", "platform_owner": "owner", "assigned_institutional_reviewer": "reviewer", "admin": "admin"}
    # All strings originate from the closed registry in this module.
    session.add(AuthorityAuditEvent(actor_class=actors.get(authority, "server"), authority_class=authority, purpose_code=purpose, transition_code=code, policy_version=POLICY_VERSION, occurred_at=now))


def apply_transition(session: Session, row: AuthorityState, *, machine: str, target: str, trigger: str, authority: str, now: datetime) -> str:
    """Internal transition primitive; wire APIs cannot supply these parameters."""
    attr = "guardian_state" if machine == "guardian" else "institutional_state"
    source = getattr(row, attr)
    disposition = evaluate_transition(machine, source, target, trigger, authority)
    if disposition == "ALLOWED":
        setattr(row, attr, target)
        row.version += 1
        if machine == "guardian" and target != "VERIFIED":
            row.guardian_verified_at = row.guardian_expires_at = row.guardian_dob_hash = None
            row.guardian_identity_hash = None
            row.relationship = row.consent_version = None
        if machine == "institutional" and target != "VERIFIED":
            row.institutional_email_hash = row.institutional_expires_at = None
        _audit(session, machine, f"{source}_TO_{target}", authority, now)
    elif trigger == "reviewer_timeout_return_to_queue":
        row.version += 1
        row.review_due_at = None
        session.add(AuthorityNotification(registration_id=row.registration_id, state_version=row.version))
        _audit(session, machine, "REVIEW_RETURNED_TO_QUEUE", "server", now)
    return disposition


def _invalidate_server_proofs(session, row, *, now, erased_user_id=None):
    """Retire lost proofs, not an actor-authorized state-machine command.

    No target state or actor/authority label is accepted. Without NYAY-19's
    internal erased-subject selector, only a demonstrably non-current guardian
    proof is eligible. With it, only proofs linked to that exact subject are
    eligible. Current/unrelated proofs cannot be changed by this path.
    """
    guardian_lost = row.guardian_state == "VERIFIED" and (
        row.guardian_user_id == erased_user_id if erased_user_id is not None
        else not guardian_is_current(session, row.registration_id, now=now)
    )
    reviewer_erased = erased_user_id is not None and row.institutional_state == "VERIFIED" and row.reviewer_user_id == erased_user_id
    if guardian_lost:
        row.guardian_state = "REVOKED"
        row.guardian_verified_at = row.guardian_expires_at = row.guardian_dob_hash = row.guardian_identity_hash = None
        row.relationship = row.consent_version = None
        row.reproof_guardian = True
        row.version += 1
        _audit(session, "guardian", "PROOF_REVOKED", "server_profile_policy", now)
    if reviewer_erased:
        row.institutional_state = "REVOKED"
        row.institutional_email_hash = row.institutional_expires_at = None
        row.reproof_institutional = True
        row.version += 1
        _audit(session, "institutional", "PROOF_REVOKED", "server_profile_policy", now)
    return guardian_lost or reviewer_erased


def _registration(session, *, user_id=None, registration_id=None):
    query = select(StudentRegistration).where(*otp_service.registration_authority_filters())
    query = query.where(StudentRegistration.user_id == user_id) if user_id else query.where(StudentRegistration.id == registration_id)
    rows = list(session.scalars(query.with_for_update().execution_options(populate_existing=True).limit(2)))
    if len(rows) != 1 or rows[0].status != "active":
        raise AuthorityError()
    return rows[0]


def get_or_create_state(session: Session, registration: StudentRegistration, now: datetime) -> AuthorityState:
    """Called under registration lock; legacy flags are mapped but never proofs."""
    row = session.get(AuthorityState, registration.id, populate_existing=True)
    if row is not None:
        return row
    guardian = session.scalar(select(GuardianConsent).where(GuardianConsent.registration_id == registration.id))
    ver = session.scalar(select(StudentVerification).where(StudentVerification.registration_id == registration.id))
    gs = map_legacy("guardian", guardian.status) if guardian else ("REQUIRED_PENDING" if registration.is_minor else "NOT_REQUIRED")
    ins = map_legacy("institutional", ver.status) if ver else "UNVERIFIED"
    # Legacy VERIFIED is retained in the append-only mapping event, then
    # explicitly invalidated: legacy mutable flags confer no NYAY-11 proof.
    _audit(session, "legacy_mapping", f"GUARDIAN_{gs}", "server", now)
    _audit(session, "legacy_mapping", f"INSTITUTIONAL_{ins}", "server", now)
    if gs == "VERIFIED":
        _audit(session, "guardian", "VERIFIED_TO_REQUIRED_PENDING", "server_profile_policy", now)
    if ins == "VERIFIED":
        _audit(session, "institutional", "VERIFIED_TO_PENDING", "server_profile_policy", now)
    row = AuthorityState(registration_id=registration.id, guardian_state=("REQUIRED_PENDING" if gs == "VERIFIED" else gs), institutional_state=("PENDING" if ins == "VERIFIED" else ins), version=1, reproof_guardian=gs == "VERIFIED", reproof_institutional=ins == "VERIFIED")
    session.add(row)
    session.flush()
    return row


def _presented(session, actor_id, raw_token, now, roles=frozenset({"student"})):
    if actor_id is None or not raw_token:
        raise AuthorityError("authentication_required", 401)
    proof = login_service.lock_presented_session_for_effect(session, raw_token, expected_user_id=actor_id, now=now, allowed_roles=roles)
    if proof is None:
        raise AuthorityError("authentication_required", 401)
    return proof


def settle_state(session, reg, row, now):
    born = date.fromisoformat(decrypt(reg.dob_ct))
    minor = is_minor(born, now.date())
    reg.is_minor = minor
    if not minor and row.guardian_state != "NOT_REQUIRED":
        apply_transition(session, row, machine="guardian", target="NOT_REQUIRED", trigger="minor_to_adult", authority="server_age_policy", now=now)
    elif minor and row.guardian_state == "NOT_REQUIRED":
        apply_transition(session, row, machine="guardian", target="REQUIRED_PENDING", trigger="adult_to_minor", authority="server_age_policy", now=now)
    if row.guardian_state == "VERIFIED" and (row.guardian_user_id is None or row.guardian_expires_at is None or utc(row.guardian_expires_at) <= utc(now)):
        apply_transition(session, row, machine="guardian", target="REQUIRED_PENDING", trigger="proof_expired", authority="server_clock", now=now)
        row.reproof_guardian = True
    if row.guardian_state == "VERIFIED" and row.guardian_dob_hash != reg.dob_hash:
        apply_transition(session, row, machine="guardian", target="REQUIRED_PENDING", trigger="dependent_identity_changed", authority="server_profile_policy", now=now)
        row.reproof_guardian = True
    if row.guardian_state == "VERIFIED":
        guardian_reg = session.scalar(select(StudentRegistration).where(StudentRegistration.user_id == row.guardian_user_id, *otp_service.registration_authority_filters()))
        if guardian_reg is not None and row.guardian_identity_hash != keyed_hash("nyay11:guardian-identity:" + guardian_reg.dob_hash):
            apply_transition(session, row, machine="guardian", target="REQUIRED_PENDING", trigger="dependent_identity_changed", authority="server_profile_policy", now=now)
            row.reproof_guardian = True
    if row.guardian_state == "VERIFIED" and not guardian_is_current(session, reg.id, now=now):
        _invalidate_server_proofs(session, row, now=now)
    if row.institutional_state == "VERIFIED" and utc(row.institutional_expires_at) <= utc(now):
        apply_transition(session, row, machine="institutional", target="EXPIRED", trigger="verification_expired", authority="server_clock", now=now)
    profile = session.scalar(select(StudentProfile).where(StudentProfile.registration_id == reg.id))
    if row.institutional_state == "VERIFIED" and (profile is None or row.institutional_email_hash != profile.institutional_email_hash):
        apply_transition(session, row, machine="institutional", target="PENDING", trigger="dependent_identity_changed", authority="server_profile_policy", now=now)
        row.reproof_institutional = True
    if row.institutional_state == "VERIFIED":
        reviewer_proof = session.get(InstitutionalEmailProof, row.reviewer_user_id) if row.reviewer_user_id else None
        if reviewer_proof is not None and not _email_identity_matches(session, reviewer_proof):
            apply_transition(session, row, machine="institutional", target="PENDING", trigger="dependent_identity_changed", authority="server_profile_policy", now=now)
            row.reproof_institutional = True
    if row.institutional_state == "VERIFIED" and not institutional_is_current(session, reg.id, now=now):
        apply_transition(session, row, machine="institutional", target="EXPIRED", trigger="verification_expired", authority="server_clock", now=now)
    if row.institutional_state == "PENDING" and row.review_due_at is not None and utc(row.review_due_at) <= utc(now):
        apply_transition(session, row, machine="institutional", target="PENDING", trigger="reviewer_timeout_return_to_queue", authority="server", now=now)
    _sync_legacy(session, reg, row)
    return row


def projection(row):
    return {"policy_version": POLICY_VERSION, "guardian_state": row.guardian_state, "institutional_state": row.institutional_state, "version": row.version, "access_mode": "full" if row.guardian_state in {"NOT_REQUIRED", "VERIFIED"} else "limited", "reverification_required": row.reproof_guardian or row.reproof_institutional}


def read_authority(session, actor_id, raw_token, now):
    reg = _registration(session, user_id=actor_id)
    _presented(session, actor_id, raw_token, now)
    row = settle_state(session, reg, get_or_create_state(session, reg, now), now)
    return projection(row)


def read_notifications(session, actor_id, raw_token, *, now):
    """Owner-only in-app notification history; no delivery or email claim.

    State versions are owner-local cursors, not cross-tenant identifiers. Reads
    settle elapsed reviewer time before projecting the durable queue events.
    """
    reg = _registration(session, user_id=actor_id)
    _presented(session, actor_id, raw_token, now)
    settle_state(session, reg, get_or_create_state(session, reg, now), now)
    session.flush()
    notices = session.scalars(select(AuthorityNotification).where(
        AuthorityNotification.registration_id == reg.id,
    ).order_by(AuthorityNotification.state_version))
    return {"notifications": [{"code": notice.code, "state_version": notice.state_version} for notice in notices]}


def _replay(session, reg, actor_id, operation, key, payload):
    if not isinstance(key, str) or re.fullmatch(r"[A-Za-z0-9._~-]{16,200}", key) is None:
        raise AuthorityError("idempotency_key_required", 422)
    key_hash = keyed_hash("nyay11:key:" + key)
    fingerprint = keyed_hash("nyay11:payload:" + json.dumps({"scope": str(reg.id) if reg else None, "payload": payload}, sort_keys=True, separators=(",", ":")))
    record = session.scalar(select(AuthorityMutationRecord).where(AuthorityMutationRecord.actor_id == actor_id, AuthorityMutationRecord.operation == operation, AuthorityMutationRecord.key_hash == key_hash))
    if record is not None:
        if not hmac.compare_digest(record.fingerprint, fingerprint):
            raise AuthorityError("authority_idempotency_conflict", 409)
        return record, json.loads(decrypt(record.outcome_ct))
    return AuthorityMutationRecord(registration_id=reg.id if reg else None, actor_id=actor_id, operation=operation, key_hash=key_hash, fingerprint=fingerprint), None


def _finish(session, record, result):
    record.outcome_ct = encrypt(json.dumps(result, sort_keys=True, separators=(",", ":")))
    session.add(record)
    session.flush()
    return result


def guardian_request(session, actor_id, raw_token, *, key, now):
    reg = _registration(session, user_id=actor_id)
    _presented(session, actor_id, raw_token, now)
    row = settle_state(session, reg, get_or_create_state(session, reg, now), now)
    record, replay = _replay(session, reg, actor_id, "guardian_request", key, {})
    if replay is not None:
        return replay
    if row.guardian_state in {"REJECTED", "REVOKED"}:
        apply_transition(session, row, machine="guardian", target="REQUIRED_PENDING", trigger="new_guardian_request", authority="student", now=now)
    elif row.guardian_state != "REQUIRED_PENDING":
        raise AuthorityError("authority_state_conflict", 409)
    session.execute(update(GuardianInvitation).where(GuardianInvitation.registration_id == reg.id, GuardianInvitation.state == "pending").values(state="revoked"))
    row.version += 1
    token = secrets.token_urlsafe(32)
    session.add(GuardianInvitation(registration_id=reg.id, token_hash=keyed_hash("nyay11:invitation:" + token), generation=row.version, state="pending", expires_at=now + timedelta(hours=24)))
    return _finish(session, record, {**projection(row), "invitation": token})


def guardian_consent(session, actor_id, raw_token, *, invitation, relationship, accepted, key, now):
    if relationship not in {"parent", "legal_guardian"} or type(accepted) is not bool or not isinstance(invitation, str) or not 32 <= len(invitation) <= 128:
        raise AuthorityError()
    token_hash = keyed_hash("nyay11:invitation:" + invitation)
    locator = session.scalar(select(GuardianInvitation).where(GuardianInvitation.token_hash == token_hash))
    if locator is None:
        raise AuthorityError()
    # Lock both registration rows in UUID order, before any auth/proof lock.
    candidates = list(session.scalars(select(StudentRegistration).where((StudentRegistration.id == locator.registration_id) | (StudentRegistration.user_id == actor_id)).order_by(StudentRegistration.id).with_for_update().execution_options(populate_existing=True)))
    owners = [r for r in candidates if r.id == locator.registration_id]
    guardians = [r for r in candidates if r.user_id == actor_id]
    if len(owners) != 1 or len(guardians) != 1 or any(r.status != "active" or not otp_service.registration_is_authorizable(r) for r in candidates):
        raise AuthorityError()
    reg, guardian_reg = owners[0], guardians[0]
    if actor_id == reg.user_id:
        raise AuthorityError()
    _presented(session, actor_id, raw_token, now)
    if is_minor(date.fromisoformat(decrypt(guardian_reg.dob_ct)), now.date()):
        raise AuthorityError()
    row = settle_state(session, reg, get_or_create_state(session, reg, now), now)
    record, replay = _replay(session, reg, actor_id, "guardian_consent", key, {"invitation_hash": token_hash, "relationship": relationship, "accepted": accepted})
    if replay is not None:
        # Replaying a response never re-grants the current authority.
        return replay
    invitation_row = session.scalar(select(GuardianInvitation).where(GuardianInvitation.id == locator.id).with_for_update().execution_options(populate_existing=True))
    if invitation_row.state != "pending" or utc(invitation_row.expires_at) <= utc(now) or invitation_row.generation != row.version:
        raise AuthorityError()
    target = "VERIFIED" if accepted else "REJECTED"
    apply_transition(session, row, machine="guardian", target=target, trigger="guardian_proof_completed" if accepted else "guardian_declined", authority="server_attested_guardian", now=now)
    invitation_row.state = "consumed"
    row.guardian_user_id = actor_id
    if accepted:
        row.guardian_verified_at, row.guardian_expires_at = now, guardian_deadline(now)
        row.guardian_dob_hash, row.relationship, row.consent_version = reg.dob_hash, relationship, "guardian-consent.v1"
        row.guardian_identity_hash = keyed_hash("nyay11:guardian-identity:" + guardian_reg.dob_hash)
        row.reproof_guardian = False
    _sync_legacy(session, reg, row)
    return _finish(session, record, projection(row))


def guardian_revoke(session, actor_id, raw_token, *, registration_id=None, key, now):
    reg = _registration(session, registration_id=registration_id) if registration_id else _registration(session, user_id=actor_id)
    _presented(session, actor_id, raw_token, now)
    row = get_or_create_state(session, reg, now)
    if actor_id == reg.user_id:
        authority = "owner"
    elif actor_id == row.guardian_user_id:
        authority = "guardian"
    else:
        raise AuthorityError()
    record, replay = _replay(session, reg, actor_id, "guardian_revoke", key, {})
    if replay is not None:
        return replay
    apply_transition(session, row, machine="guardian", target="REVOKED", trigger="guardian_or_owner_revocation", authority=authority, now=now)
    session.execute(update(GuardianInvitation).where(GuardianInvitation.registration_id == reg.id, GuardianInvitation.state == "pending").values(state="revoked"))
    _sync_legacy(session, reg, row)
    return _finish(session, record, projection(row))


def _sync_legacy(session, reg, row):
    guardian = session.scalar(select(GuardianConsent).where(GuardianConsent.registration_id == reg.id).with_for_update())
    if guardian is None and row.guardian_state != "NOT_REQUIRED":
        guardian = GuardianConsent(registration_id=reg.id)
        session.add(guardian)
    if guardian is not None:
        guardian.status = {"NOT_REQUIRED": "revoked", "REQUIRED_PENDING": "pending", "VERIFIED": "verified", "REJECTED": "rejected", "REVOKED": "revoked"}[row.guardian_state]
        guardian.verified = row.guardian_state == "VERIFIED"
    verification = session.scalar(select(StudentVerification).where(StudentVerification.registration_id == reg.id).with_for_update())
    if verification is None:
        verification = StudentVerification(registration_id=reg.id, method="institutional_email")
        session.add(verification)
    if verification is not None:
        verification.status = {"UNVERIFIED": "pending", "PENDING": "in_review", "VERIFIED": "verified", "REJECTED": "rejected", "EXPIRED": "expired", "REVOKED": "revoked"}[row.institutional_state]
        verification.verified_email_hash = row.institutional_email_hash if row.institutional_state == "VERIFIED" else None


def identity_changed(session, reg, field, now):
    if field not in {"date_of_birth", "institutional_email"}:
        raise AuthorityError("identity_dependency_unknown", 409)
    row = session.get(AuthorityState, reg.id)
    if row is None:
        return
    if (field == "date_of_birth" and row.reproof_guardian) or (field == "institutional_email" and row.reproof_institutional):
        raise AuthorityError("identity_reproof_required", 409)
    if field == "date_of_birth" and row.guardian_state == "VERIFIED":
        apply_transition(session, row, machine="guardian", target="REQUIRED_PENDING", trigger="dependent_identity_changed", authority="server_profile_policy", now=now)
        row.reproof_guardian = True
        session.execute(update(GuardianInvitation).where(GuardianInvitation.registration_id == reg.id, GuardianInvitation.state == "pending").values(state="revoked"))
    if field == "institutional_email" and row.institutional_state == "VERIFIED":
        apply_transition(session, row, machine="institutional", target="PENDING", trigger="dependent_identity_changed", authority="server_profile_policy", now=now)
        row.reproof_institutional = True
    _audit(session, "identity", "DEPENDENT_PROOF_INVALIDATED", "server_profile_policy", now)


def request_review(session, actor_id, raw_token, *, key, now):
    reg = _registration(session, user_id=actor_id)
    _presented(session, actor_id, raw_token, now)
    row = settle_state(session, reg, get_or_create_state(session, reg, now), now)
    record, replay = _replay(session, reg, actor_id, "institutional_request", key, {})
    if replay is not None:
        return replay
    if row.institutional_state != "PENDING":
        apply_transition(session, row, machine="institutional", target="PENDING", trigger="student_review_request", authority="student", now=now)
    row.review_due_at = now + timedelta(days=7)
    _sync_legacy(session, reg, row)
    return _finish(session, record, projection(row))


def _email_identity_matches(session, proof):
    """Canonical student identity cannot change beneath a provider receipt."""
    user = session.get(User, proof.user_id)
    if user is None or user.status != "active":
        return False
    if user.role != "student":
        return user.role in {"admin", "legal_reviewer"}
    registration = session.scalar(select(StudentRegistration).where(StudentRegistration.user_id == user.id, *otp_service.registration_authority_filters()))
    if registration is None or registration.institution_ref != proof.institution:
        return False
    profile = session.scalar(select(StudentProfile).where(StudentProfile.registration_id == registration.id))
    return profile is not None and profile.institutional_email_hash == proof.email_hash


def _email_proof(session, user_id, institution, now, *, for_update=True):
    query = select(InstitutionalEmailProof).where(InstitutionalEmailProof.user_id == user_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    proof = session.scalar(query)
    if proof is None or proof.state != "verified" or proof.institution != institution or utc(proof.expires_at) <= utc(now) or proof.provider_receipt_hash is None or not _email_identity_matches(session, proof):
        raise AuthorityError()
    return proof


def assign_reviewer(session, admin_id, raw_token, *, reviewer_id, institution, expires_at, now, key):
    _presented(session, admin_id, raw_token, now, frozenset({"admin"}))
    if not institution or utc(expires_at) <= utc(now) or utc(expires_at) > utc(now + timedelta(days=365)):
        raise AuthorityError()
    proof = _email_proof(session, reviewer_id, institution, now)
    record, replay = _replay(session, None, admin_id, "reviewer_assignment", key, {"reviewer_id": str(reviewer_id), "institution": institution, "expires_at": expires_at.isoformat()})
    if replay is not None:
        return replay
    if utc(expires_at) > utc(proof.expires_at):
        raise AuthorityError()
    row = session.scalar(select(InstitutionalReviewerAssignment).where(InstitutionalReviewerAssignment.user_id == reviewer_id, InstitutionalReviewerAssignment.institution == institution, InstitutionalReviewerAssignment.operation == "review").with_for_update())
    if row is None:
        row = InstitutionalReviewerAssignment(user_id=reviewer_id, institution=institution, operation="review")
        session.add(row)
    row.active, row.expires_at = True, expires_at
    _audit(session, "institutional", "REVIEWER_ASSIGNED", "admin", now)
    session.flush()
    return _finish(session, record, {"status": "assigned"})


def review(session, actor_id, raw_token, *, registration_id, approve, key, now, expected_profile_version=None):
    reg = _registration(session, registration_id=registration_id)
    _presented(session, actor_id, raw_token, now, frozenset({"student", "admin", "legal_reviewer"}))
    if actor_id == reg.user_id or type(approve) is not bool or not reg.institution_ref:
        raise AuthorityError()
    if expected_profile_version is not None and (type(expected_profile_version) is not int or expected_profile_version < 1):
        raise AuthorityError("authority_request_invalid", 422)
    # Cross-review A→B / B→A must acquire the same proof order.
    list(session.scalars(select(InstitutionalEmailProof).where(InstitutionalEmailProof.user_id.in_((actor_id, reg.user_id))).order_by(InstitutionalEmailProof.user_id).with_for_update().execution_options(populate_existing=True)))
    reviewer_proof = _email_proof(session, actor_id, reg.institution_ref, now, for_update=False)
    assignment = session.scalar(select(InstitutionalReviewerAssignment).where(InstitutionalReviewerAssignment.user_id == actor_id, InstitutionalReviewerAssignment.institution == reg.institution_ref, InstitutionalReviewerAssignment.operation == "review", InstitutionalReviewerAssignment.active.is_(True), InstitutionalReviewerAssignment.expires_at > now).with_for_update())
    if assignment is None:
        raise AuthorityError()
    row = settle_state(session, reg, get_or_create_state(session, reg, now), now)
    operation = "institutional_review" if expected_profile_version is None else "institutional_review_legacy"
    payload = {"approve": approve}
    if expected_profile_version is not None:
        payload["expected_profile_version"] = expected_profile_version
    record, replay = _replay(session, reg, actor_id, operation, key, payload)
    if replay is not None:
        return replay
    profile = session.scalar(select(StudentProfile).where(StudentProfile.registration_id == reg.id))
    if profile is None:
        raise AuthorityError()
    if expected_profile_version is not None and profile.profile_version != expected_profile_version:
        raise AuthorityError("profile_version_conflict", 409, current_profile_version=profile.profile_version)
    owner_proof = _email_proof(session, reg.user_id, reg.institution_ref, now, for_update=False)
    if owner_proof.email_hash != profile.institutional_email_hash:
        raise AuthorityError()
    apply_transition(session, row, machine="institutional", target="VERIFIED" if approve else "REJECTED", trigger="assigned_review_approved" if approve else "assigned_review_rejected", authority="assigned_institutional_reviewer", now=now)
    row.review_due_at = None
    if approve:
        row.institutional_email_hash = owner_proof.email_hash
        row.reviewer_user_id = actor_id
        row.institutional_expires_at = min(utc(owner_proof.expires_at), utc(reviewer_proof.expires_at), utc(assignment.expires_at))
        row.reproof_institutional = False
    _sync_legacy(session, reg, row)
    if expected_profile_version is not None:
        return _finish(session, record, {
            "status": row.institutional_state.lower(),
            "profile_version": profile.profile_version,
            "owner_projection_invalidated": True,
        })
    return _finish(session, record, projection(row))


def reviewer_timeout(session, registration_id, *, now):
    reg = _registration(session, registration_id=registration_id)
    row = get_or_create_state(session, reg, now)
    if row.institutional_state != "PENDING" or row.review_due_at is None or utc(row.review_due_at) > utc(now):
        return False
    apply_transition(session, row, machine="institutional", target="PENDING", trigger="reviewer_timeout_return_to_queue", authority="server", now=now)
    return True


def owner_break_glass(session, actor_id, raw_token, *, registration_id, key, now):
    from app.core.config import settings
    if not settings.authority_platform_owner_id or str(actor_id) != settings.authority_platform_owner_id:
        raise AuthorityError()
    reg = _registration(session, registration_id=registration_id)
    _presented(session, actor_id, raw_token, now, frozenset({"admin"}))
    row = get_or_create_state(session, reg, now)
    record, replay = _replay(session, reg, actor_id, "institutional_breakglass", key, {})
    if replay is not None:
        return replay
    apply_transition(session, row, machine="institutional", target="REVOKED", trigger="owner_break_glass", authority="platform_owner", now=now)
    _sync_legacy(session, reg, row)
    return _finish(session, record, projection(row))


def request_email_proof(session, actor_id, raw_token, *, email, institution, sender, now, key):
    """Persist challenge before delivery; delivery receipt is required to verify.

    Destination must match the student's saved institutional address. Staff
    addresses require an institution domain that matches the claimed address;
    the domain is subsequently bound by an administrator's assignment.
    """
    from app.core.institutional_email import normalize_institutional_email
    from app.services.otp_sender import OtpSendError
    normalized = normalize_institutional_email(email)
    if normalized is None or not institution or sender is None:
        raise AuthorityError("authority_provider_unavailable", 503)
    user = session.get(User, actor_id)
    if user is None or user.status != "active":
        raise AuthorityError()
    reg = None
    if user.role == "student":
        reg = _registration(session, user_id=actor_id)
        profile = session.scalar(select(StudentProfile).where(StudentProfile.registration_id == reg.id))
        if profile is None or reg.institution_ref != institution or profile.institutional_email_hash != keyed_hash(normalized):
            raise AuthorityError()
    from app.core.config import settings
    approved_domains = settings.authority_institution_domains.get(institution, [])
    if normalized.rsplit("@", 1)[-1] not in approved_domains:
        raise AuthorityError()
    _presented(session, actor_id, raw_token, now, frozenset({"student", "admin", "legal_reviewer"}))
    record, replay = _replay(session, reg, actor_id, "email_request", key, {"email_hash": keyed_hash(normalized), "institution": institution})
    if replay is not None:
        if replay.get("status") != "code_sent":
            raise AuthorityError("authority_delivery_pending", 503)
        return replay
    row = session.scalar(select(InstitutionalEmailProof).where(InstitutionalEmailProof.user_id == actor_id).with_for_update())
    if row is not None and utc(now) < utc(row.issued_at) + timedelta(minutes=1):
        raise AuthorityError("authority_rate_limited", 429)
    code = f"{secrets.randbelow(1_000_000):06d}"
    code_hash = keyed_hash(f"nyay11:email-code:{actor_id}:{code}")
    if row is None:
        row = InstitutionalEmailProof(user_id=actor_id)
        session.add(row)
    row.email_hash, row.institution = keyed_hash(normalized), institution
    row.code_hash, row.provider_receipt_hash, row.state = code_hash, None, "pending_delivery"
    row.attempts, row.issued_at, row.expires_at = 0, now, now + timedelta(minutes=10)
    _finish(session, record, {"status": "delivery_pending"})
    session.commit()
    try:
        receipt = sender.send_idempotent(normalized, code, idempotency_token=keyed_hash(f"nyay11:email-delivery:{actor_id}:{code_hash}"))
    except OtpSendError:
        receipt = None
    if reg is not None:
        _registration(session, user_id=actor_id)
    _presented(session, actor_id, raw_token, now, frozenset({"student", "admin", "legal_reviewer"}))
    row = session.scalar(select(InstitutionalEmailProof).where(InstitutionalEmailProof.user_id == actor_id).with_for_update().execution_options(populate_existing=True))
    if row is None or row.code_hash != code_hash:
        raise AuthorityError("authority_delivery_superseded", 409)
    row.state = "active" if receipt else "failed"
    row.provider_receipt_hash = keyed_hash("nyay11:email-receipt:" + receipt) if receipt else None
    _finish(session, record, {"status": "code_sent" if receipt else "delivery_failed"})
    session.commit()
    if not receipt:
        raise AuthorityError("authority_provider_unavailable", 503)
    return {"status": "code_sent"}


def verify_email_proof(session, actor_id, raw_token, *, code, now, key):
    _presented(session, actor_id, raw_token, now, frozenset({"student", "admin", "legal_reviewer"}))
    record, replay = _replay(session, None, actor_id, "email_verify", key, {"code_hash": keyed_hash(f"nyay11:verify:{code}")})
    if replay is not None:
        if replay.get("status") == "denied":
            raise AuthorityError()
        return replay
    row = session.scalar(select(InstitutionalEmailProof).where(InstitutionalEmailProof.user_id == actor_id).with_for_update().execution_options(populate_existing=True))
    if row is None or row.state != "active" or row.attempts >= 5 or utc(row.expires_at) <= utc(now) or not row.provider_receipt_hash:
        raise AuthorityError()
    row.attempts += 1
    if not isinstance(code, str) or re.fullmatch(r"[0-9]{6}", code) is None or not hmac.compare_digest(row.code_hash or "", keyed_hash(f"nyay11:email-code:{actor_id}:{code}")):
        if row.attempts >= 5:
            row.state, row.code_hash = "failed", None
        _audit(session, "institutional", "EMAIL_PROOF_DENIED", "server", now)
        _finish(session, record, {"status": "denied"})
        session.commit()  # Failed attempts remain durable; route must not undo.
        raise AuthorityError()
    row.state, row.code_hash = "verified", None
    row.expires_at = now + timedelta(days=365)
    _audit(session, "institutional", "EMAIL_PROOF_VERIFIED", "server", now)
    return _finish(session, record, {"status": "verified"})


def guardian_is_current(session, registration_id, *, now):
    row = session.get(AuthorityState, registration_id)
    reg = session.get(StudentRegistration, registration_id)
    if row is None or reg is None or row.guardian_state != "VERIFIED" or row.guardian_user_id is None or row.guardian_dob_hash != reg.dob_hash or row.guardian_expires_at is None or utc(row.guardian_expires_at) <= utc(now):
        return False
    guardian = session.get(User, row.guardian_user_id)
    guardian_reg = session.scalar(select(StudentRegistration).where(StudentRegistration.user_id == row.guardian_user_id, *otp_service.registration_authority_filters()))
    if guardian is None or guardian.status != "active" or guardian_reg is None or row.guardian_identity_hash != keyed_hash("nyay11:guardian-identity:" + guardian_reg.dob_hash):
        return False
    return not is_minor(date.fromisoformat(decrypt(guardian_reg.dob_ct)), now.date())


def institutional_is_current(session, registration_id, *, now):
    row = session.get(AuthorityState, registration_id)
    reg = session.get(StudentRegistration, registration_id)
    if row is None or reg is None or row.institutional_state != "VERIFIED" or row.reviewer_user_id is None or row.institutional_expires_at is None or utc(row.institutional_expires_at) <= utc(now):
        return False
    profile = session.scalar(select(StudentProfile).where(StudentProfile.registration_id == registration_id))
    if profile is None or row.institutional_email_hash != profile.institutional_email_hash:
        return False
    reviewer = session.get(User, row.reviewer_user_id)
    if reviewer is None or reviewer.status != "active":
        return False
    try:
        owner_proof = _email_proof(session, reg.user_id, reg.institution_ref, now, for_update=False)
        _email_proof(session, row.reviewer_user_id, reg.institution_ref, now, for_update=False)
    except AuthorityError:
        return False
    assignment = session.scalar(select(InstitutionalReviewerAssignment).where(InstitutionalReviewerAssignment.user_id == row.reviewer_user_id, InstitutionalReviewerAssignment.institution == reg.institution_ref, InstitutionalReviewerAssignment.operation == "review", InstitutionalReviewerAssignment.active.is_(True), InstitutionalReviewerAssignment.expires_at > now))
    return assignment is not None and owner_proof.email_hash == profile.institutional_email_hash


def erase_owner_authority(session, user_id, *, now):
    """NYAY-19 caller owns the transaction; sever proof links before deletion."""
    from sqlalchemy import delete
    reg_ids = list(session.scalars(select(StudentRegistration.id).where(StudentRegistration.user_id == user_id)))
    for row in session.scalars(select(AuthorityState).where((AuthorityState.guardian_user_id == user_id) | (AuthorityState.reviewer_user_id == user_id)).order_by(AuthorityState.registration_id).with_for_update()):
        _invalidate_server_proofs(session, row, erased_user_id=user_id, now=now)
        if row.guardian_user_id == user_id:
            row.guardian_user_id = None
        if row.reviewer_user_id == user_id:
            row.reviewer_user_id = None
    for model in (GuardianInvitation, AuthorityNotification, AuthorityMutationRecord, AuthorityState):
        session.execute(delete(model).where(model.registration_id.in_(reg_ids)))
    session.execute(delete(AuthorityMutationRecord).where(AuthorityMutationRecord.actor_id == user_id))
    session.execute(delete(InstitutionalEmailProof).where(InstitutionalEmailProof.user_id == user_id))
    session.execute(delete(InstitutionalReviewerAssignment).where(InstitutionalReviewerAssignment.user_id == user_id))
    # Aggregate audit rows contain no identifiers or PII and remain immutable.


def export_owner_authority(session, user_id):
    reg_ids = list(session.scalars(select(StudentRegistration.id).where(StudentRegistration.user_id == user_id)))
    return [{"guardian_state": r.guardian_state, "institutional_state": r.institutional_state, "policy_version": r.policy_version, "guardian_relationship": r.relationship, "guardian_consent_version": r.consent_version, "guardian_verified_at": r.guardian_verified_at.isoformat() if r.guardian_verified_at else None, "guardian_expires_at": r.guardian_expires_at.isoformat() if r.guardian_expires_at else None, "institutional_expires_at": r.institutional_expires_at.isoformat() if r.institutional_expires_at else None} for r in session.scalars(select(AuthorityState).where(AuthorityState.registration_id.in_(reg_ids)))]
