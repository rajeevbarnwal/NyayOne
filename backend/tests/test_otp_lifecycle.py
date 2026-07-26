"""SAATHI-448 Workstream B — OTP verify/resend/lockout/recovery tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.models  # noqa: F401  (register tables on Base.metadata)
from app.models.registration import OtpChallenge
from app.schemas.registration import StudentRegisterRequest
from app.services import otp_service
from app.services.registration_service import register_student

NOW = datetime(2026, 7, 26, 9, 0, tzinfo=timezone.utc)


def _reg(session: Session, mobile: str = "9876543210"):
    req = StudentRegisterRequest(
        first_name="Aditi", last_name="Nair", mobile=mobile, dob="2004-03-14",
        consent={"accepted": True},
    )
    return register_student(session, req, now=NOW)


def _issue(session, reg_id, now=NOW):
    box: dict[str, str] = {}
    otp_service.issue_challenge(session, reg_id, now, send=lambda c: box.__setitem__("code", c))
    return box["code"]


def test_verify_correct_marks_consumed_and_status(db_session: Session):
    reg = _reg(db_session)
    code = _issue(db_session, reg.id)
    ch = otp_service.verify(db_session, reg.id, code, NOW)
    assert ch.consumed_at is not None
    # verify() mutates the in-session registration; assert without a DB refresh
    # (the transaction isn't committed in this unit-level test).
    assert reg.status == "otp_verified"


def test_wrong_code_then_lockout(db_session: Session):
    reg = _reg(db_session)
    code = _issue(db_session, reg.id)
    wrong = f"{(int(code) + 1) % 1_000_000:06d}"
    for _ in range(2):
        with pytest.raises(otp_service.OtpError) as e:
            otp_service.verify(db_session, reg.id, wrong, NOW)
        assert e.value.code == "incorrect_otp" and e.value.attempts_left >= 1
    with pytest.raises(otp_service.OtpError) as e:
        otp_service.verify(db_session, reg.id, wrong, NOW)
    assert e.value.code == "locked"
    # Lockout is authoritative on the next attempt too.
    with pytest.raises(otp_service.OtpError) as e:
        otp_service.verify(db_session, reg.id, code, NOW)
    assert e.value.code == "locked"


def test_expired(db_session: Session):
    reg = _reg(db_session)
    code = _issue(db_session, reg.id)
    with pytest.raises(otp_service.OtpError) as e:
        otp_service.verify(db_session, reg.id, code, NOW + timedelta(seconds=301))
    assert e.value.code == "expired"


def test_consumed_replay(db_session: Session):
    reg = _reg(db_session)
    code = _issue(db_session, reg.id)
    otp_service.verify(db_session, reg.id, code, NOW)
    with pytest.raises(otp_service.OtpError) as e:  # replay after consume → no active challenge
        otp_service.verify(db_session, reg.id, code, NOW)
    assert e.value.code == "no_active_challenge"


def test_resend_cooldown_then_supersede(db_session: Session):
    reg = _reg(db_session)
    _issue(db_session, reg.id, NOW)
    with pytest.raises(otp_service.OtpError) as e:
        otp_service.resend(db_session, reg.id, NOW + timedelta(seconds=10))
    assert e.value.code == "resend_cooldown"
    otp_service.resend(db_session, reg.id, NOW + timedelta(seconds=31))
    active = db_session.scalars(
        select(OtpChallenge).where(OtpChallenge.registration_id == reg.id, OtpChallenge.consumed_at.is_(None))
    ).all()
    assert len(active) == 1  # only one active challenge after supersede


def test_recovery_opaque_and_anti_enumeration(db_session: Session):
    reg = _reg(db_session)
    known = otp_service.start_recovery(db_session, "9876543210", NOW)
    assert known == str(reg.id)
    unknown = otp_service.start_recovery(db_session, "9999999999", NOW)
    assert unknown != str(reg.id)  # opaque id, no existence leak
    # No registration exists for the unknown mobile.
    from app.core.crypto import keyed_hash
    from app.models.registration import StudentRegistration
    assert db_session.scalar(
        select(StudentRegistration).where(StudentRegistration.mobile_hash == keyed_hash("9999999999"))
    ) is None


def test_no_raw_otp_in_challenge_row(db_session: Session):
    reg = _reg(db_session)
    code = _issue(db_session, reg.id)
    ch = db_session.scalar(
        select(OtpChallenge).where(OtpChallenge.registration_id == reg.id, OtpChallenge.consumed_at.is_(None))
    )
    blob = f"{ch.verifier_hash}{ch.metadata_json}"
    assert code not in blob
    assert len(ch.verifier_hash) == 64 and not ch.verifier_hash.isdigit()
