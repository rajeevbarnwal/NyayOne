"""SAATHI-366 C4/C6/C7 — CHECK constraints, uniqueness, append-only audit.

SQLite enforces CHECK constraints when a table is created with them, so these
run against the same DDL the models declare (mirrored by migration 0002).
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.models.audit import AuditEvent, AuditImmutableError
from app.models.registration import (
    Consent,
    OtpChallenge,
    StudentProfile,
    StudentRegistration,
    StudentVerification,
    User,
)
from app.schemas.registration import StudentRegisterRequest
from app.services.registration_service import register_student


def _reg(session: Session, mobile="9876543210"):
    req = StudentRegisterRequest(
        first_name="Aditi", last_name="Nair", mobile=mobile, dob="2004-03-14",
        consent={"accepted": True},
    )
    return register_student(session, req).registration


def test_user_role_check_constraint(db_session: Session):
    db_session.add(User(role="martian", status="pending"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_registration_status_check_constraint(db_session: Session):
    reg = _reg(db_session)
    reg.status = "not_a_status"
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_verification_status_check_constraint(db_session: Session):
    reg = _reg(db_session)
    ver = db_session.scalar(select(StudentVerification).where(StudentVerification.registration_id == reg.id))
    ver.status = "bogus"
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_consent_must_be_affirmative(db_session: Session):
    reg = _reg(db_session)
    db_session.add(Consent(registration_id=reg.id, purpose="x", accepted=False, policy_version="v1"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_otp_attempts_not_negative(db_session: Session):
    reg = _reg(db_session)
    ch = db_session.scalar(select(OtpChallenge).where(OtpChallenge.registration_id == reg.id))
    ch.attempts = -1
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_one_profile_per_registration(db_session: Session):
    reg = _reg(db_session)
    db_session.add(StudentProfile(registration_id=reg.id, college="Second"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_audit_events_are_append_only_no_update(db_session: Session):
    reg = _reg(db_session)
    ev = db_session.scalar(select(AuditEvent).where(AuditEvent.resource_id == reg.id))
    ev.action = "tampered"
    with pytest.raises(AuditImmutableError):
        db_session.flush()


def test_audit_events_are_append_only_no_delete(db_session: Session):
    reg = _reg(db_session)
    ev = db_session.scalar(select(AuditEvent).where(AuditEvent.resource_id == reg.id))
    db_session.delete(ev)
    with pytest.raises(AuditImmutableError):
        db_session.flush()
