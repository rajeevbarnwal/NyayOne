"""Server-owned proof fixtures for inherited native gates; never evidence data.

These rows stand for already completed provider delivery and admin assignment.
NYAY-11's dedicated native gate separately exercises the actual proof ceremony.
No client field, mutable legacy status, or review call grants fixture authority.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.crypto import encrypt, keyed_hash
from app.models.registration import StudentProfile, StudentRegistration, User
from app.models.student_authority import (
    InstitutionalEmailProof,
    InstitutionalReviewerAssignment,
)
from app.services import student_authority


def fixture_validity_anchor(request_time, creation_time):
    """DOB clocks may be historical; proof liveness is anchored at creation."""
    return max(request_time, creation_time)


def prepare_institutional_review(factory, *, registration_id, reviewer_id, now):
    anchor = fixture_validity_anchor(now, datetime.now(timezone.utc))
    with factory.begin() as session:
        registration = session.get(StudentRegistration, registration_id)
        profile = session.scalar(select(StudentProfile).where(StudentProfile.registration_id == registration_id))
        if registration is None or profile is None or not profile.institutional_email_hash or reviewer_id == registration.user_id:
            raise AssertionError("NYAY11_REVIEW_FIXTURE_INVALID")
        institution = registration.institution_ref or profile.college
        if not institution:
            raise AssertionError("NYAY11_REVIEW_INSTITUTION_MISSING")
        registration.institution_ref = institution
        reviewer = session.get(User, reviewer_id)
        reviewer_email_hash = keyed_hash("nyay11-fixture-reviewer-email:" + str(reviewer_id))
        if reviewer is not None and reviewer.role == "student":
            reviewer_registration = session.scalar(select(StudentRegistration).where(StudentRegistration.user_id == reviewer_id))
            if reviewer_registration is None:
                raise AssertionError("NYAY11_REVIEWER_CANONICAL_PROFILE_MISSING")
            reviewer_profile = session.scalar(select(StudentProfile).where(StudentProfile.registration_id == reviewer_registration.id))
            if reviewer_profile is None:
                raise AssertionError("NYAY11_REVIEWER_CANONICAL_PROFILE_MISSING")
            reviewer_registration.institution_ref = institution
            reviewer_profile.institutional_email_hash = reviewer_email_hash
            reviewer_profile.institutional_email_ct = encrypt("nyay11-fixture-reviewer-email:" + str(reviewer_id))
        for actor_id, email_hash in (
            (registration.user_id, profile.institutional_email_hash),
            (reviewer_id, reviewer_email_hash),
        ):
            proof = session.get(InstitutionalEmailProof, actor_id)
            if proof is None:
                proof = InstitutionalEmailProof(user_id=actor_id)
                session.add(proof)
            proof.email_hash = email_hash
            proof.institution = institution
            proof.state = "verified"
            proof.provider_receipt_hash = keyed_hash("nyay11-fixture-provider-receipt:" + str(actor_id))
            proof.code_hash = None
            proof.attempts = 0
            proof.issued_at, proof.expires_at = now, anchor + timedelta(days=30)
        assignment = session.scalar(select(InstitutionalReviewerAssignment).where(
            InstitutionalReviewerAssignment.user_id == reviewer_id,
            InstitutionalReviewerAssignment.institution == institution,
            InstitutionalReviewerAssignment.operation == "review",
        ))
        if assignment is None:
            assignment = InstitutionalReviewerAssignment(user_id=reviewer_id, institution=institution, operation="review")
            session.add(assignment)
        assignment.active, assignment.expires_at = True, anchor + timedelta(days=7)
        state = student_authority.get_or_create_state(session, registration, now)
        if state.institutional_state != "PENDING":
            student_authority.apply_transition(session, state, machine="institutional", target="PENDING", trigger="student_review_request", authority="student", now=now)
        state.review_due_at = anchor + timedelta(days=7)
        student_authority._sync_legacy(session, registration, state)
