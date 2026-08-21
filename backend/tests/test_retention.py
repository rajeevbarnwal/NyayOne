"""SAATHI-366 C5 — config-driven retention / deletion / anonymisation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.retention import ANONYMISED, RetentionPolicy, anonymise_registration, purge_expired
from app.models.registration import RegistrationDobReconciliation, StudentRegistration
from app.schemas.registration import StudentRegisterRequest
from app.services.registration_service import register_student

NOW = datetime(2026, 7, 26, 9, 0, tzinfo=timezone.utc)


def _reg(session: Session, mobile="9876543210"):
    req = StudentRegisterRequest(
        first_name="Aditi", last_name="Nair", mobile=mobile, dob="2004-03-14",
        consent={"accepted": True},
    )
    return register_student(session, req, now=NOW).registration


def test_no_window_is_noop(db_session: Session):
    _reg(db_session)
    policy = RetentionPolicy(None, None, None, None, None, "anonymise")
    counts = purge_expired(db_session, now=NOW, policy=policy)
    assert counts == {
        "registrations": 0,
        "otp_challenges": 0,
        "recovery_sessions": 0,
        "otp_flows": 0,
        "otp_terminal_flows": 0,
        "otp_authorities": 0,
        "otp_terminal_challenges": 0,
        "otp_terminal_outboxes": 0,
        "otp_expired_registrations": 0,
        "otp_rate_limit_buckets": 0,
        "otp_legacy_destinations": 0,
    }
    assert db_session.scalar(select(StudentRegistration)) is not None


def test_pending_registration_anonymised_after_window(db_session: Session):
    reg = _reg(db_session)
    reg.created_at = NOW - timedelta(days=40)
    db_session.flush()
    policy = RetentionPolicy(
        registration_pending_days=30, registration_inactive_days=None,
        otp_challenge_days=None, recovery_session_days=None, audit_events_days=None, mode="anonymise",
    )
    counts = purge_expired(db_session, now=NOW, policy=policy)
    assert counts["registrations"] == 1
    refreshed = db_session.get(StudentRegistration, reg.id)
    assert refreshed.mobile_ct == ANONYMISED and refreshed.first_name == ANONYMISED
    assert refreshed.status == "deleted" and refreshed.deleted_at is not None


def test_delete_mode_removes_row(db_session: Session):
    reg = _reg(db_session)
    db_session.add(
        RegistrationDobReconciliation(
            registration_id=reg.id,
            outcome="reconciled",
            reason_code="verified_source",
            source_key_version="v1",
            source_ciphertext_sha256="a" * 64,
        )
    )
    reg.created_at = NOW - timedelta(days=40)
    db_session.flush()
    policy = RetentionPolicy(30, None, None, None, None, "delete")
    purge_expired(db_session, now=NOW, policy=policy)
    assert db_session.get(StudentRegistration, reg.id) is None
    assert db_session.get(RegistrationDobReconciliation, reg.id) is None


def test_direct_anonymise_hook(db_session: Session):
    reg = _reg(db_session)
    anonymise_registration(db_session, reg)
    db_session.flush()
    assert reg.mobile_ct == ANONYMISED and reg.dob_ct == ANONYMISED
