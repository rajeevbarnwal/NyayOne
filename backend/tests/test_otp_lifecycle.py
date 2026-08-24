"""SAATHI-448 Workstream B — OTP verify/resend/lockout tests (service level).

Uses the new outbox-based issue_challenge, which returns (challenge, intent) and
never delivers synchronously. The raw code is read from the returned intent
(in-memory only) — it is never persisted.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import decrypt
import app.models  # noqa: F401  (register tables on Base.metadata)
from app.models.registration import (
    OtpChallenge,
    OtpFlow,
    OtpOutbox,
    OtpPurposeAuthority,
)
from app.schemas.registration import StudentRegisterRequest
from app.services import otp_flow_service, otp_outbox, otp_service, recovery_service
from app.services.otp_sender import CapturingSender, OtpSendError
from app.services.registration_service import register_student

NOW = datetime(2026, 7, 26, 9, 0, tzinfo=timezone.utc)


def _reg(
    session: Session,
    mobile: str = "9876543210",
    *,
    now: datetime = NOW,
):
    req = StudentRegisterRequest(
        first_name="Aditi", last_name="Nair", mobile=mobile, dob="2004-03-14",
        terms_accepted=True, terms_version="terms.v1",
        privacy_notice_acknowledged=True,
        privacy_notice_version="privacy.v1",
    )
    return register_student(session, req, now=now).registration


def _attach_flow(
    session: Session,
    challenge: OtpChallenge,
    *,
    now: datetime,
) -> OtpFlow:
    authority = session.get(OtpPurposeAuthority, challenge.authority_id)
    assert authority is not None
    _, flow = otp_flow_service.create_flow(
        session,
        authority,
        now=now,
        destination="9876543210",
        challenge=challenge,
        registration_id=challenge.registration_id,
    )
    return flow


def _utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def _current_flow(
    session: Session,
    registration_id: uuid.UUID,
    *,
    purpose: str = "signup",
) -> OtpFlow:
    flow = session.scalar(
        select(OtpFlow).where(
            OtpFlow.registration_id == registration_id,
            OtpFlow.purpose == purpose,
            OtpFlow.state.in_(("pending", "code_sent", "locked")),
        )
    )
    assert flow is not None
    return flow


def _issue(session, reg_id, now=NOW, purpose="signup"):
    challenge, intent = otp_service.issue_challenge(
        session, reg_id, now, purpose=purpose, destination="9876543210"
    )
    _attach_flow(session, challenge, now=now)
    outbox = session.get(OtpOutbox, intent.outbox_id)
    assert outbox is not None and outbox.code_ct is not None
    code = decrypt(outbox.code_ct)
    delivered = otp_outbox.run_delivery(
        session,
        intent,
        CapturingSender(),
        raise_on_failure=True,
        now=now,
    )
    assert delivered is True
    return code


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
    issued_at = datetime.now(timezone.utc)
    reg = _reg(db_session, now=issued_at)
    code = _issue(db_session, reg.id, issued_at)
    with pytest.raises(otp_service.OtpError) as e:
        otp_service.verify(
            db_session,
            reg.id,
            code,
            issued_at + timedelta(seconds=301),
        )
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
    flow = db_session.scalar(
        select(OtpFlow).where(
            OtpFlow.registration_id == reg.id,
            OtpFlow.purpose == "signup",
            OtpFlow.state.in_(("pending", "code_sent", "locked")),
        )
    )
    assert flow is not None
    prior_challenge_id = flow.challenge_id
    candidate, intent = otp_service.resend(
        db_session,
        reg.id,
        NOW + timedelta(seconds=31),
        destination="9876543210",
    )
    assert flow.challenge_id == prior_challenge_id
    assert flow.challenge_id != candidate.id
    assert otp_outbox.run_delivery(
        db_session,
        intent,
        CapturingSender(),
        raise_on_failure=True,
        now=NOW + timedelta(seconds=31),
    )
    assert flow.challenge_id == candidate.id
    active = db_session.scalars(
        select(OtpChallenge).where(
            OtpChallenge.registration_id == reg.id,
            OtpChallenge.purpose == "signup",
            OtpChallenge.consumed_at.is_(None),
        )
    ).all()
    assert len(active) == 1  # only one active challenge after supersede


def test_resend_candidate_and_activation_never_outlive_authorized_flow(
    db_session: Session,
):
    reg = _reg(db_session)
    _issue(db_session, reg.id, NOW)
    flow = _current_flow(db_session, reg.id)
    authorized_deadline = NOW + timedelta(seconds=35)
    flow.expires_at = authorized_deadline
    db_session.commit()

    candidate, intent = otp_service.resend(
        db_session,
        reg.id,
        NOW + timedelta(seconds=31),
        destination="9876543210",
    )

    assert flow.challenge_id != candidate.id
    assert _utc(candidate.expires_at) == authorized_deadline
    assert otp_outbox.run_delivery(
        db_session,
        intent,
        CapturingSender(),
        raise_on_failure=True,
        now=NOW + timedelta(seconds=32),
    )
    authority = db_session.get(OtpPurposeAuthority, candidate.authority_id)
    assert authority is not None
    assert candidate.delivery_state == "active"
    assert _utc(candidate.expires_at) == authorized_deadline
    assert authority.active_expires_at is not None
    assert _utc(authority.active_expires_at) == authorized_deadline


def test_activation_uses_full_challenge_ttl_when_flow_lives_longer(
    db_session: Session,
):
    reg = _reg(db_session)
    candidate, intent = otp_service.issue_challenge(
        db_session,
        reg.id,
        NOW,
        purpose="signup",
        destination="9876543210",
    )
    flow = _attach_flow(db_session, candidate, now=NOW)
    expected_deadline = NOW + timedelta(
        seconds=settings.otp_challenge_ttl_seconds
    )
    assert _utc(flow.expires_at) > expected_deadline

    assert otp_outbox.run_delivery(
        db_session,
        intent,
        CapturingSender(),
        raise_on_failure=True,
        now=NOW,
    )
    authority = db_session.get(OtpPurposeAuthority, candidate.authority_id)
    assert authority is not None
    assert _utc(candidate.expires_at) == expected_deadline
    assert authority.active_expires_at is not None
    assert _utc(authority.active_expires_at) == expected_deadline


def test_resend_fails_closed_without_a_live_authority_flow(
    db_session: Session,
):
    reg = _reg(db_session)
    candidate, _ = otp_service.issue_challenge(
        db_session,
        reg.id,
        NOW,
        purpose="signup",
        destination="9876543210",
    )
    authority = db_session.get(OtpPurposeAuthority, candidate.authority_id)
    assert authority is not None
    before = (
        candidate.expires_at,
        authority.resend_count,
        authority.generation,
        authority.cooldown_until,
    )

    with pytest.raises(otp_service.OtpError) as error:
        otp_service.resend(
            db_session,
            reg.id,
            NOW + timedelta(seconds=31),
            destination="9876543210",
        )

    assert (error.value.status_code, error.value.code) == (
        401,
        "otp_flow_unavailable",
    )
    assert (
        candidate.expires_at,
        authority.resend_count,
        authority.generation,
        authority.cooldown_until,
    ) == before


def test_resend_fails_closed_when_authority_flow_is_expired(
    db_session: Session,
):
    reg = _reg(db_session)
    _issue(db_session, reg.id, NOW)
    flow = _current_flow(db_session, reg.id)
    flow.expires_at = NOW + timedelta(seconds=30)
    authority = db_session.get(OtpPurposeAuthority, flow.authority_id)
    assert authority is not None
    db_session.commit()
    before = (authority.resend_count, authority.generation)

    with pytest.raises(otp_service.OtpError) as error:
        otp_service.resend(
            db_session,
            reg.id,
            NOW + timedelta(seconds=31),
            destination="9876543210",
        )

    assert (error.value.status_code, error.value.code) == (
        401,
        "otp_flow_unavailable",
    )
    assert (authority.resend_count, authority.generation) == before
    assert db_session.scalar(
        select(OtpChallenge).where(
            OtpChallenge.authority_id == authority.id,
            OtpChallenge.delivery_state == "pending_delivery",
        )
    ) is None


def test_resend_fails_closed_when_authority_flow_is_ambiguous(
    db_session: Session,
):
    reg = _reg(db_session)
    _issue(db_session, reg.id, NOW)
    flow = _current_flow(db_session, reg.id)
    authority = db_session.get(OtpPurposeAuthority, flow.authority_id)
    assert authority is not None
    flow.subject_hash = "0" * 64
    assert flow.subject_hash != authority.subject_hash
    db_session.commit()
    before = (authority.resend_count, authority.generation)

    with pytest.raises(otp_service.OtpError) as error:
        otp_service.resend(
            db_session,
            reg.id,
            NOW + timedelta(seconds=31),
            destination="9876543210",
        )

    assert (error.value.status_code, error.value.code) == (
        401,
        "otp_flow_unavailable",
    )
    assert (authority.resend_count, authority.generation) == before
    assert db_session.scalar(
        select(OtpChallenge).where(
            OtpChallenge.authority_id == authority.id,
            OtpChallenge.delivery_state == "pending_delivery",
        )
    ) is None


def test_issue_writes_pending_outbox_no_raw_code(db_session: Session):
    reg = _reg(db_session)
    _, intent = otp_service.issue_challenge(db_session, reg.id, NOW, purpose="signup", destination="9876543210")
    ob = db_session.scalar(select(OtpOutbox).order_by(OtpOutbox.created_at.desc()))
    assert ob is not None and ob.status == "pending"
    code = decrypt(ob.code_ct or "")
    blob = f"{ob.destination_ct}{ob.code_ct}{ob.last_error}{ob.metadata_json}"
    assert code not in blob
    assert ob.destination_ct != "9876543210"  # encrypted, never plaintext


def test_missing_flow_voids_and_erases_without_provider_io(
    db_session: Session,
):
    reg = _reg(db_session)
    challenge, intent = otp_service.issue_challenge(
        db_session,
        reg.id,
        NOW,
        purpose="signup",
        destination="9876543210",
    )
    sender = CapturingSender()

    assert not otp_outbox.run_delivery(
        db_session,
        intent,
        sender,
        raise_on_failure=False,
        now=NOW,
    )
    assert sender.sent == []
    row = db_session.get(OtpOutbox, intent.outbox_id)
    assert row is not None
    assert (row.status, row.code_ct, row.destination_ct) == (
        "void",
        None,
        None,
    )
    assert row.last_error == "otp_flow_missing"
    assert challenge.delivery_state == "void"


def test_expired_flow_voids_and_erases_without_provider_io(
    db_session: Session,
):
    reg = _reg(db_session)
    challenge, intent = otp_service.issue_challenge(
        db_session,
        reg.id,
        NOW,
        purpose="signup",
        destination="9876543210",
    )
    flow = _attach_flow(db_session, challenge, now=NOW)
    flow.expires_at = NOW
    db_session.commit()
    sender = CapturingSender()

    assert not otp_outbox.run_delivery(
        db_session,
        intent,
        sender,
        raise_on_failure=False,
        now=NOW,
    )
    assert sender.sent == []
    row = db_session.get(OtpOutbox, intent.outbox_id)
    assert row is not None
    assert (row.status, row.code_ct, row.destination_ct) == (
        "void",
        None,
        None,
    )
    assert row.last_error == "otp_flow_expired"
    assert challenge.delivery_state == "void"
    assert (flow.state, flow.destination_masked_ct, flow.key_version) == (
        "expired",
        None,
        None,
    )


def test_ambiguous_flow_voids_and_erases_without_provider_io(
    db_session: Session,
):
    reg = _reg(db_session)
    challenge, intent = otp_service.issue_challenge(
        db_session,
        reg.id,
        NOW,
        purpose="signup",
        destination="9876543210",
    )
    flow = _attach_flow(db_session, challenge, now=NOW)
    flow.purpose = "login"
    db_session.commit()
    sender = CapturingSender()

    assert not otp_outbox.run_delivery(
        db_session,
        intent,
        sender,
        raise_on_failure=False,
        now=NOW,
    )
    assert sender.sent == []
    row = db_session.get(OtpOutbox, intent.outbox_id)
    assert row is not None
    assert (row.status, row.code_ct, row.destination_ct) == (
        "void",
        None,
        None,
    )
    assert row.last_error == "otp_flow_ambiguous"
    assert challenge.delivery_state == "void"
    assert (flow.state, flow.destination_masked_ct, flow.key_version) == (
        "expired",
        None,
        None,
    )


def test_flow_expiring_during_provider_io_never_activates_candidate(
    db_session: Session,
):
    reg = _reg(db_session)
    challenge, intent = otp_service.issue_challenge(
        db_session,
        reg.id,
        NOW,
        purpose="signup",
        destination="9876543210",
    )
    flow = _attach_flow(db_session, challenge, now=NOW)

    class ExpiringSender(CapturingSender):
        def send_idempotent(
            self,
            destination: str,
            code: str,
            *,
            idempotency_token: str,
        ) -> str:
            receipt = super().send_idempotent(
                destination,
                code,
                idempotency_token=idempotency_token,
            )
            flow.expires_at = NOW
            db_session.commit()
            return receipt

    sender = ExpiringSender()
    assert not otp_outbox.run_delivery(
        db_session,
        intent,
        sender,
        raise_on_failure=False,
        now=NOW,
    )
    assert len(sender.sent) == 1
    row = db_session.get(OtpOutbox, intent.outbox_id)
    assert row is not None
    assert row.status == "void" and row.last_error == "otp_flow_expired"
    assert row.code_ct is None and row.destination_ct is None
    assert challenge.delivery_state == "void"
    assert flow.state == "expired"


@pytest.mark.parametrize("provider_succeeds", (True, False))
def test_stale_recovery_resend_callback_preserves_verified_proof(
    db_session: Session,
    *,
    provider_succeeds: bool,
):
    """Verification wins while resend provider I/O is blocked.

    Success and failure callbacks are both stale once the original verifier has
    produced a recovery proof.  They may fence their candidate/outbox, but must
    not revoke the independently verified browser capability.
    """

    reg = _reg(db_session)
    signup_code = _issue(db_session, reg.id)
    otp_service.verify(db_session, reg.id, signup_code, NOW)
    assert reg.status == "otp_verified"

    recovery_now = NOW + timedelta(seconds=1)
    raw_token, flow, first_intent = recovery_service.start_flow(
        db_session,
        "9876543210",
        recovery_now,
    )
    assert first_intent is not None
    first_outbox = db_session.get(OtpOutbox, first_intent.outbox_id)
    assert first_outbox is not None and first_outbox.code_ct is not None
    recovery_code = decrypt(first_outbox.code_ct)
    db_session.commit()
    assert otp_outbox.run_delivery(
        db_session,
        first_intent,
        CapturingSender(),
        raise_on_failure=True,
        now=recovery_now,
    )
    assert flow.state == "code_sent"

    resend_now = recovery_now + timedelta(
        seconds=settings.otp_resend_cooldown_seconds + 1
    )
    candidate, resend_intent = otp_service.resend(
        db_session,
        reg.id,
        resend_now,
        purpose="recovery",
        destination="9876543210",
    )
    db_session.commit()
    assert candidate.delivery_state == "pending_delivery"

    class VerifyWhileProviderIsBlocked:
        calls = 0

        def send_idempotent(
            self,
            destination: str,
            code: str,
            *,
            idempotency_token: str,
        ) -> str:
            del destination, code, idempotency_token
            self.calls += 1
            recovery_service.verify_flow(
                db_session,
                raw_token,
                recovery_code,
                resend_now,
            )
            current = db_session.get(OtpFlow, flow.id)
            assert current is not None and current.state == "verified"
            if not provider_succeeds:
                raise OtpSendError("provider rejected stale resend")
            return "stale-resend-accepted"

    sender = VerifyWhileProviderIsBlocked()
    assert not otp_outbox.run_delivery(
        db_session,
        resend_intent,
        sender,
        raise_on_failure=False,
        now=resend_now,
    )
    assert sender.calls == 1
    db_session.expire_all()

    current = db_session.get(OtpFlow, flow.id)
    stale_candidate = db_session.get(OtpChallenge, candidate.id)
    stale_outbox = db_session.get(OtpOutbox, resend_intent.outbox_id)
    assert current is not None
    assert current.state == "verified" and current.consumed_at is None
    assert _utc(current.expires_at) == resend_now + timedelta(
        seconds=settings.otp_recovery_proof_ttl_seconds
    )
    assert stale_candidate is not None
    assert stale_candidate.delivery_state == "void"
    assert stale_outbox is not None
    assert (stale_outbox.status, stale_outbox.last_error) == (
        "void",
        "otp_flow_unavailable",
    )
    assert stale_outbox.code_ct is None and stale_outbox.destination_ct is None

    recovery_service.complete_flow(
        db_session,
        raw_token,
        resend_now + timedelta(seconds=1),
    )
    db_session.refresh(current)
    assert current.state == "consumed"


@pytest.mark.parametrize("provider_succeeds", (True, False))
@pytest.mark.parametrize("graph_disappears", (True, False))
def test_delivery_finalizers_release_owned_transaction_after_claim_race(
    db_session: Session,
    *,
    provider_succeeds: bool,
    graph_disappears: bool,
):
    reg = _reg(db_session)
    challenge, intent = otp_service.issue_challenge(
        db_session,
        reg.id,
        NOW,
        purpose="signup",
        destination="9876543210",
    )
    _attach_flow(db_session, challenge, now=NOW)

    class RacingSender:
        calls = 0

        def send_idempotent(
            self,
            destination: str,
            code: str,
            *,
            idempotency_token: str,
        ) -> str:
            del destination, code, idempotency_token
            self.calls += 1
            row = db_session.get(OtpOutbox, intent.outbox_id)
            assert row is not None
            if graph_disappears:
                db_session.delete(row)
            else:
                row.claim_token_hash = "a" * 64
            db_session.commit()
            if not provider_succeeds:
                raise OtpSendError("provider rejected delivery")
            return "accepted"

    sender = RacingSender()
    assert not otp_outbox.run_delivery(
        db_session,
        intent,
        sender,
        raise_on_failure=False,
        now=NOW,
    )
    assert sender.calls == 1
    assert not db_session.in_transaction()


def test_stale_success_finalizer_is_not_a_second_delivery(
    db_session: Session,
):
    """A reclaimed lease has one delivery winner and one terminal observer."""

    reg = _reg(db_session)
    challenge, intent = otp_service.issue_challenge(
        db_session,
        reg.id,
        NOW,
        purpose="signup",
        destination="9876543210",
    )
    _attach_flow(db_session, challenge, now=NOW)

    first = otp_outbox._claim(  # noqa: SLF001 - lease-race regression
        db_session,
        intent,
        now=NOW,
        commit=True,
    )
    assert isinstance(first, otp_outbox._DeliveryClaim)  # noqa: SLF001
    reclaim_now = NOW + timedelta(
        seconds=settings.otp_outbox_lease_seconds + 1
    )
    second = otp_outbox._claim(  # noqa: SLF001 - lease-race regression
        db_session,
        intent,
        now=reclaim_now,
        commit=True,
    )
    assert isinstance(second, otp_outbox._DeliveryClaim)  # noqa: SLF001
    assert first.token_hash != second.token_hash

    assert otp_outbox._finalize_success(  # noqa: SLF001
        db_session,
        second,
        receipt="winning-receipt",
        now=reclaim_now,
        commit=True,
    )
    assert not db_session.in_transaction()
    assert not otp_outbox._finalize_success(  # noqa: SLF001
        db_session,
        first,
        receipt="stale-receipt",
        now=reclaim_now,
        commit=True,
    )
    assert not db_session.in_transaction()

    row = db_session.get(OtpOutbox, intent.outbox_id)
    assert row is not None
    assert row.status == "sent" and row.attempts == 2
    assert row.provider_receipt_hash is not None


@pytest.mark.parametrize("status", ("claimed", "failed"))
def test_unavailable_flow_explicitly_voids_inactive_relay_target(
    db_session: Session,
    status: str,
):
    reg = _reg(db_session)
    challenge, intent = otp_service.issue_challenge(
        db_session,
        reg.id,
        NOW,
        purpose="signup",
        destination="9876543210",
    )
    flow = _attach_flow(db_session, challenge, now=NOW)
    row = db_session.get(OtpOutbox, intent.outbox_id)
    assert row is not None
    challenge.delivery_state = "superseded"
    challenge.consumed_at = NOW
    flow.expires_at = NOW
    row.status = status
    if status == "claimed":
        row.claim_token_hash = "b" * 64
        row.claimed_at = NOW - timedelta(seconds=1)
        row.lease_expires_at = NOW + timedelta(seconds=30)
    else:
        row.next_attempt_at = NOW + timedelta(seconds=30)
        row.last_error = "provider_send_failed"
    db_session.commit()

    assert not otp_outbox.run_delivery(
        db_session,
        intent,
        CapturingSender(),
        raise_on_failure=False,
        now=NOW,
    )
    assert (row.status, row.last_error) == ("void", "otp_flow_expired")
    assert row.code_ct is None and row.destination_ct is None
    assert row.claim_token_hash is None
    assert row.claimed_at is None and row.lease_expires_at is None
    assert row.next_attempt_at is None
    assert challenge.delivery_state == "superseded"


@pytest.mark.parametrize(
    ("reason", "is_flow_boundary"),
    (("otp_flow_expired", True), ("challenge_inactive", False)),
)
def test_prevoided_delivery_preserves_typed_flow_boundary(
    db_session: Session,
    reason: str,
    is_flow_boundary: bool,
):
    reg = _reg(db_session)
    challenge, intent = otp_service.issue_challenge(
        db_session,
        reg.id,
        NOW,
        purpose="signup",
        destination="9876543210",
    )
    _attach_flow(db_session, challenge, now=NOW)
    row = db_session.get(OtpOutbox, intent.outbox_id)
    assert row is not None
    challenge.delivery_state = "void"
    challenge.consumed_at = NOW
    row.status = "void"
    row.last_error = reason
    row.code_ct = None
    row.destination_ct = None
    db_session.commit()
    sender = CapturingSender()

    with pytest.raises(OtpSendError) as error:
        otp_outbox.run_delivery(
            db_session,
            intent,
            sender,
            raise_on_failure=True,
            now=NOW,
        )

    assert isinstance(error.value, otp_outbox.OtpFlowUnavailable) is (
        is_flow_boundary
    )
    assert sender.sent == []
    assert not db_session.in_transaction()


def test_terminal_delivery_observations_release_owned_claim_transactions(
    db_session: Session,
):
    """Already-sent and absent intents must not leak graph row locks."""

    reg = _reg(db_session)
    challenge, sent_intent = otp_service.issue_challenge(
        db_session,
        reg.id,
        NOW,
        purpose="signup",
        destination="9876543210",
    )
    _attach_flow(db_session, challenge, now=NOW)
    assert otp_outbox.run_delivery(
        db_session,
        sent_intent,
        CapturingSender(),
        raise_on_failure=True,
        now=NOW,
    )
    assert not db_session.in_transaction()

    assert not otp_outbox.run_delivery(
        db_session,
        sent_intent,
        CapturingSender(),
        raise_on_failure=True,
        now=NOW,
    )
    assert not db_session.in_transaction()

    missing_intent = otp_outbox.DeliveryIntent(outbox_id=uuid.uuid4())
    assert not otp_outbox.run_delivery(
        db_session,
        missing_intent,
        CapturingSender(),
        raise_on_failure=False,
        now=NOW,
    )
    assert not db_session.in_transaction()


def test_terminal_sent_delivery_is_unchanged_after_flow_expiry(
    db_session: Session,
):
    reg = _reg(db_session)
    challenge, intent = otp_service.issue_challenge(
        db_session,
        reg.id,
        NOW,
        purpose="signup",
        destination="9876543210",
    )
    flow = _attach_flow(db_session, challenge, now=NOW)
    assert otp_outbox.run_delivery(
        db_session,
        intent,
        CapturingSender(),
        raise_on_failure=True,
        now=NOW,
    )
    row = db_session.get(OtpOutbox, intent.outbox_id)
    assert row is not None
    terminal_before = (
        row.status,
        row.delivered_at.replace(tzinfo=None),
        row.provider_receipt_hash,
        challenge.delivery_state,
        challenge.expires_at.replace(tzinfo=None),
    )
    flow.expires_at = NOW
    db_session.commit()
    sender = CapturingSender()

    assert not otp_outbox.run_delivery(
        db_session,
        intent,
        sender,
        raise_on_failure=True,
        now=NOW,
    )
    assert sender.sent == []
    assert (
        row.status,
        row.delivered_at.replace(tzinfo=None),
        row.provider_receipt_hash,
        challenge.delivery_state,
        challenge.expires_at.replace(tzinfo=None),
    ) == terminal_before


def test_production_delivery_clock_is_captured_after_each_graph_lock(
    db_session: Session,
    monkeypatch,
):
    reg = _reg(db_session)
    challenge, intent = otp_service.issue_challenge(
        db_session,
        reg.id,
        NOW,
        purpose="signup",
        destination="9876543210",
    )
    _attach_flow(db_session, challenge, now=NOW)
    events: list[str] = []
    instants = iter(
        (NOW + timedelta(seconds=1), NOW + timedelta(seconds=2))
    )
    locked_graph = otp_outbox._locked_graph

    def observe_locked_graph(*args, **kwargs):
        graph = locked_graph(*args, **kwargs)
        events.append("locked")
        return graph

    class ObservedClock:
        @classmethod
        def now(cls, tz):
            assert tz is timezone.utc
            events.append("clock")
            return next(instants)

    monkeypatch.setattr(otp_outbox, "_locked_graph", observe_locked_graph)
    monkeypatch.setattr(otp_outbox, "datetime", ObservedClock)
    assert otp_outbox.run_delivery(
        db_session,
        intent,
        CapturingSender(),
        raise_on_failure=True,
    )
    row = db_session.get(OtpOutbox, intent.outbox_id)
    assert row is not None and row.delivered_at is not None
    assert row.delivered_at.replace(tzinfo=timezone.utc) == NOW + timedelta(
        seconds=2
    )
    assert events == ["locked", "clock", "locked", "clock"]


def test_explicit_delivery_clock_never_reads_wall_time(
    db_session: Session,
    monkeypatch,
):
    reg = _reg(db_session)
    challenge, intent = otp_service.issue_challenge(
        db_session,
        reg.id,
        NOW,
        purpose="signup",
        destination="9876543210",
    )
    _attach_flow(db_session, challenge, now=NOW)

    class ForbiddenClock:
        @classmethod
        def now(cls, _tz):
            raise AssertionError("explicit delivery clock read wall time")

    monkeypatch.setattr(otp_outbox, "datetime", ForbiddenClock)
    assert otp_outbox.run_delivery(
        db_session,
        intent,
        CapturingSender(),
        raise_on_failure=True,
        now=NOW,
    )
    row = db_session.get(OtpOutbox, intent.outbox_id)
    assert row is not None and row.delivered_at is not None
    assert row.delivered_at.replace(tzinfo=timezone.utc) == NOW


def test_claim_without_commit_preserves_callers_transaction_ownership(
    db_session: Session,
):
    """The internal compositional mode keeps its transaction caller-owned."""

    reg = _reg(db_session)
    challenge, sent_intent = otp_service.issue_challenge(
        db_session,
        reg.id,
        NOW,
        purpose="signup",
        destination="9876543210",
    )
    _attach_flow(db_session, challenge, now=NOW)
    assert otp_outbox.run_delivery(
        db_session,
        sent_intent,
        CapturingSender(),
        raise_on_failure=True,
        now=NOW,
    )

    assert otp_outbox._claim(  # noqa: SLF001 - transaction boundary regression
        db_session,
        sent_intent,
        now=NOW,
        commit=False,
    ) is True
    assert db_session.in_transaction()
    db_session.rollback()

    missing_intent = otp_outbox.DeliveryIntent(outbox_id=uuid.uuid4())
    assert otp_outbox._claim(  # noqa: SLF001 - transaction boundary regression
        db_session,
        missing_intent,
        now=NOW,
        commit=False,
    ) is False
    assert db_session.in_transaction()
    db_session.rollback()


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
    signup_code = _issue(db_session, reg.id)
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
    assert outbox is not None and outbox.code_ct is None
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
