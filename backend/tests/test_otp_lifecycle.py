"""SAATHI-448 Workstream B — OTP verify/resend/lockout tests (service level).

Uses the new outbox-based issue_challenge, which returns (challenge, intent) and
never delivers synchronously. The raw code is read from the returned intent
(in-memory only) — it is never persisted.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import decrypt
import app.models  # noqa: F401  (register tables on Base.metadata)
from app.models.registration import OtpChallenge, OtpOutbox
from app.schemas.registration import StudentRegisterRequest
from app.services import otp_service
from app.services.registration_service import register_student

NOW = datetime(2026, 7, 26, 9, 0, tzinfo=timezone.utc)


def _reg(session: Session, mobile: str = "9876543210"):
    req = StudentRegisterRequest(
        first_name="Aditi", last_name="Nair", mobile=mobile, dob="2004-03-14",
        consent={"accepted": True},
    )
    return register_student(session, req, now=NOW).registration


def _issue(session, reg_id, now=NOW, purpose="signup"):
    _, intent = otp_service.issue_challenge(
        session, reg_id, now, purpose=purpose, destination="9876543210"
    )
    outbox = session.get(OtpOutbox, intent.outbox_id)
    assert outbox is not None and outbox.code_ct is not None
    return decrypt(outbox.code_ct)


def test_verify_correct_marks_consumed_and_status(db_session: Session):
    reg = _reg(db_session)
    code = _issue(db_session, reg.id)
    ch = otp_service.verify(db_session, reg.id, code, NOW)
    assert ch.consumed_at is not None
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
    with pytest.raises(otp_service.OtpError) as e:
        otp_service.verify(db_session, reg.id, code, NOW)
    assert e.value.code == "no_active_challenge"


def test_resend_cooldown_then_supersede(db_session: Session):
    reg = _reg(db_session)
    _issue(db_session, reg.id, NOW)
    with pytest.raises(otp_service.OtpError) as e:
        otp_service.resend(db_session, reg.id, NOW + timedelta(seconds=10), destination="9876543210")
    assert e.value.code == "resend_cooldown"
    otp_service.resend(db_session, reg.id, NOW + timedelta(seconds=31), destination="9876543210")
    active = db_session.scalars(
        select(OtpChallenge).where(
            OtpChallenge.registration_id == reg.id,
            OtpChallenge.purpose == "signup",
            OtpChallenge.consumed_at.is_(None),
        )
    ).all()
    assert len(active) == 1  # only one active challenge after supersede


def test_issue_writes_pending_outbox_no_raw_code(db_session: Session):
    reg = _reg(db_session)
    _, intent = otp_service.issue_challenge(db_session, reg.id, NOW, purpose="signup", destination="9876543210")
    ob = db_session.scalar(select(OtpOutbox).order_by(OtpOutbox.created_at.desc()))
    assert ob is not None and ob.status == "pending"
    code = decrypt(ob.code_ct or "")
    blob = f"{ob.destination_ct}{ob.code_ct}{ob.last_error}{ob.metadata_json}"
    assert code not in blob
    assert ob.destination_ct != "9876543210"  # encrypted, never plaintext


def test_no_raw_otp_in_challenge_row(db_session: Session):
    reg = _reg(db_session)
    code = _issue(db_session, reg.id)
    ch = db_session.scalar(
        select(OtpChallenge).where(OtpChallenge.registration_id == reg.id, OtpChallenge.consumed_at.is_(None))
    )
    blob = f"{ch.verifier_hash}{ch.metadata_json}"
    assert code not in blob
    assert len(ch.verifier_hash) == 64 and not ch.verifier_hash.isdigit()


def test_recovery_and_signup_challenges_independent(db_session: Session):
    """A recovery OTP must not supersede the active signup challenge."""
    reg = _reg(db_session)
    signup_code = _issue(db_session, reg.id, NOW, purpose="signup")
    _issue(db_session, reg.id, NOW, purpose="recovery")
    ch = otp_service.verify(db_session, reg.id, signup_code, NOW, purpose="signup")
    assert ch.consumed_at is not None


def test_activated_registration_cannot_reopen_signup_otp_lifecycle(
    db_session: Session,
):
    reg = _reg(db_session)
    active_signup = db_session.scalar(
        select(OtpChallenge).where(
            OtpChallenge.registration_id == reg.id,
            OtpChallenge.purpose == "signup",
            OtpChallenge.consumed_at.is_(None),
        )
    )
    outbox = db_session.scalar(
        select(OtpOutbox).where(OtpOutbox.challenge_id == active_signup.id)
    )
    signup_code = decrypt(outbox.code_ct or "")
    otp_service.verify(db_session, reg.id, signup_code, NOW)
    reg.status = "active"
    db_session.commit()
    challenge_before = [
        (row.id, row.consumed_at, row.attempts, row.locked_until)
        for row in db_session.scalars(
            select(OtpChallenge).order_by(OtpChallenge.id)
        )
    ]
    outbox_before = [
        (row.id, row.status, row.code_ct, row.attempts)
        for row in db_session.scalars(select(OtpOutbox).order_by(OtpOutbox.id))
    ]

    for operation in (
        lambda: otp_service.issue_challenge(
            db_session,
            reg.id,
            NOW + timedelta(minutes=1),
            purpose="signup",
            destination="9876543210",
        ),
        lambda: otp_service.resend(
            db_session,
            reg.id,
            NOW + timedelta(minutes=1),
            purpose="signup",
            destination="9876543210",
        ),
        lambda: otp_service.verify(
            db_session,
            reg.id,
            signup_code,
            NOW + timedelta(minutes=1),
            purpose="signup",
        ),
    ):
        with pytest.raises(otp_service.OtpError) as error:
            operation()
        assert (error.value.status_code, error.value.code) == (
            404,
            "no_active_challenge",
        )

    assert reg.status == "active"
    assert [
        (row.id, row.consumed_at, row.attempts, row.locked_until)
        for row in db_session.scalars(
            select(OtpChallenge).order_by(OtpChallenge.id)
        )
    ] == challenge_before
    assert [
        (row.id, row.status, row.code_ct, row.attempts)
        for row in db_session.scalars(select(OtpOutbox).order_by(OtpOutbox.id))
    ] == outbox_before

    # Activation closes only the signup capability; authenticated login and
    # recovery purpose issuance remain available.
    otp_service.issue_challenge(
        db_session,
        reg.id,
        NOW + timedelta(minutes=2),
        purpose="login",
        destination="9876543210",
    )
    otp_service.issue_challenge(
        db_session,
        reg.id,
        NOW + timedelta(minutes=2),
        purpose="recovery",
        destination="9876543210",
    )
