"""Focused NYAY-17 registration idempotency service/API contracts."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.v1 import auth_student as endpoint
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.retention import RetentionPolicy, purge_expired
from app.db.models.audit import AuditEvent
from app.db.session import get_session
from app.models.registration import (
    Consent,
    OtpChallenge,
    OtpFlow,
    OtpOutbox,
    OtpPurposeAuthority,
    RegistrationIdempotencyRecord,
    StudentProfile,
    StudentRegistration,
    StudentVerification,
    User,
)
from app.schemas.registration import StudentRegisterRequest
from app.services import (
    otp_flow_service,
    otp_outbox,
    otp_service,
    registration_service,
)
from app.services.otp_sender import OtpSendError
from app.workers import otp_outbox_relay
from tests import dbtemplate


NOW = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
KEY = "opaque registration key"


def _payload(**changes):
    payload = {
        "first_name": "Aditi",
        "middle_name": "Rani",
        "last_name": "Nair",
        "mobile": "9876543210",
        "dob": "2004-03-14",
        "consent": {"accepted": True, "policy_version": "dpdp-2023.v1"},
        "college": "National Law School",
        "year_of_study": "Third Year",
        "enrolment_number": "KA/1234/2023",
        "institutional_email": "aditi@nls.ac.in",
        "bar_enrolment_number": "D/1/2020",
    }
    payload.update(changes)
    return payload


def _request(**changes) -> StudentRegisterRequest:
    return StudentRegisterRequest(**_payload(**changes))


class CapturingSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self._receipts: dict[str, tuple[str, str, str]] = {}

    def send_idempotent(
        self, destination: str, code: str, *, idempotency_token: str
    ) -> str:
        existing = self._receipts.get(idempotency_token)
        if existing is not None:
            assert existing[:2] == (destination, code)
            return existing[2]
        receipt = f"test-{len(self._receipts) + 1}"
        self._receipts[idempotency_token] = (destination, code, receipt)
        self.sent.append((destination, code))
        return receipt


class FailingSender:
    def __init__(self) -> None:
        self.attempts = 0

    def send_idempotent(
        self, destination: str, code: str, *, idempotency_token: str
    ) -> None:
        self.attempts += 1
        raise OtpSendError("provider unavailable")


@pytest.fixture()
def http_ctx():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    dbtemplate.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

    def production_session():
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    sender = CapturingSender()
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(endpoint.router, prefix="/api/v1")
    app.dependency_overrides[get_session] = production_session
    app.dependency_overrides[endpoint.get_otp_sender] = lambda: sender
    app.dependency_overrides[endpoint.get_outbox_session_factory] = lambda: factory
    client = TestClient(
        app,
        raise_server_exceptions=False,
        headers={"Origin": settings.cors_origins[0]},
    )
    yield client, factory, sender, app
    engine.dispose()


def _counts(session: Session) -> tuple[int, ...]:
    models = (
        User,
        StudentRegistration,
        Consent,
        StudentProfile,
        StudentVerification,
        OtpChallenge,
        OtpOutbox,
        RegistrationIdempotencyRecord,
        AuditEvent,
    )
    return tuple(
        int(session.scalar(select(func.count()).select_from(model)) or 0)
        for model in models
    )


def _attach_signup_flow(
    session: Session,
    result: registration_service.RegistrationResult,
    *,
    now: datetime = NOW,
) -> None:
    endpoint._signup_flow(
        session,
        result,
        raw_token=otp_flow_service.deterministic_signup_token(KEY),
        destination=_request().mobile,
        now=now,
    )


MUTATIONS = (
    ("first_name", "Meera"),
    ("middle_name", None),
    ("last_name", "Shah"),
    ("mobile", "9876543211"),
    ("dob", "2003-03-14"),
    ("consent", {"accepted": False, "policy_version": "dpdp-2023.v1"}),
    ("consent", {"accepted": True, "policy_version": "dpdp-2023.v2"}),
    ("college", "Another Law School"),
    ("year_of_study", "Fourth Year"),
    ("enrolment_number", "KA/9999/2023"),
    ("institutional_email", "other@nls.ac.in"),
    ("bar_enrolment_number", "D/2/2020"),
)


@pytest.mark.parametrize(("field", "value"), MUTATIONS)
def test_v1_fingerprint_binds_every_canonical_leaf(field, value):
    original = registration_service.registration_request_fingerprint(_request())
    assert (
        registration_service.registration_request_fingerprint(
            _request(**{field: value})
        )
        != original
    )


def test_v1_normalization_and_schema_defaults_are_pinned():
    canonical = _request(
        first_name="Aditi",
        college="National Law School",
        year_of_study="Third Year",
        institutional_email="aditi@nls.ac.in",
    )
    equivalent = _request(
        first_name="  Aditi  ",
        college=" National   Law\tSchool ",
        year_of_study=" Third   Year ",
        enrolment_number=" KA/1234/2023 ",
        institutional_email=" ADITI@NLS.AC.IN ",
        bar_enrolment_number=" D/1/2020 ",
    )
    assert registration_service.registration_request_fingerprint(
        equivalent
    ) == registration_service.registration_request_fingerprint(canonical)
    assert set(StudentRegisterRequest.model_fields) == set(
        registration_service.REGISTRATION_REQUEST_V1_FIELDS
    )
    assert StudentRegisterRequest.model_fields["college"].default is None
    assert canonical.consent.__class__.model_fields["policy_version"].default == (
        "dpdp-2023.v1"
    )


def test_ascii_mobile_and_exact_opaque_key_boundary():
    with pytest.raises(ValidationError):
        _request(mobile="９８７６５４３２１０")
    for valid in ("k", "opaque internal space", "<opaque>", "x" * 200):
        assert registration_service.validate_idempotency_key(valid) == valid
    for invalid in ("", " edge", "edge ", "a\x00b", "a\x7fb", "x" * 201):
        with pytest.raises(registration_service.RegistrationError) as caught:
            registration_service.validate_idempotency_key(invalid)
        assert (caught.value.status_code, caught.value.code) == (
            422,
            "invalid_idempotency_key",
        )


def test_exact_replay_and_all_mutations_have_zero_delta(http_ctx):
    client, factory, sender, _app = http_ctx
    first = client.post(
        "/api/v1/auth/student/register",
        headers={"Idempotency-Key": KEY},
        json=_payload(),
    )
    assert first.status_code == 201
    with factory() as session:
        baseline = _counts(session)
        record = session.scalar(select(RegistrationIdempotencyRecord))
        registration = session.scalar(select(StudentRegistration))
        assert record is not None and record.state == "succeeded"
        assert registration is not None and registration.idempotency_key is None
        assert KEY not in record.idempotency_key_hash
        assert record.request_fingerprint not in first.text

    replay = client.post(
        "/api/v1/auth/student/register",
        headers={"Idempotency-Key": KEY},
        json=_payload(),
    )
    assert replay.status_code == 201
    assert replay.json() == first.json()
    assert replay.json()["status"] == "pending"
    assert len(sender.sent) == 1

    for field, value in MUTATIONS:
        conflict = client.post(
            "/api/v1/auth/student/register",
            headers={"Idempotency-Key": KEY},
            json=_payload(**{field: value}),
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "idempotency_conflict"
        assert conflict.json()["detail"]["field"] == "Idempotency-Key"
    with factory() as session:
        assert _counts(session) == baseline
    assert len(sender.sent) == 1


def test_duplicate_and_invalid_headers_fail_before_db_or_provider(http_ctx):
    client, factory, sender, _app = http_ctx
    for values in (("same", "same"), ("one", "two")):
        response = client.post(
            "/api/v1/auth/student/register",
            headers=[
                ("Idempotency-Key", values[0]),
                ("Idempotency-Key", values[1]),
            ],
            json=_payload(),
        )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "invalid_idempotency_key"
    oversized = client.post(
        "/api/v1/auth/student/register",
        headers={"Idempotency-Key": "x" * 201},
        json=_payload(),
    )
    assert oversized.status_code == 422
    with factory() as session:
        assert _counts(session) == (0,) * 9
    assert sender.sent == []


def test_provider_failure_preserves_key_and_retryable_graph_with_mismatch_409(
    http_ctx,
):
    client, factory, sender, app = http_ctx
    failing = FailingSender()
    app.dependency_overrides[endpoint.get_otp_sender] = lambda: failing
    first = client.post(
        "/api/v1/auth/student/register",
        headers={"Idempotency-Key": KEY},
        json=_payload(),
    )
    assert first.status_code == 201
    with factory() as session:
        record = session.scalar(select(RegistrationIdempotencyRecord))
        assert record is not None and record.state == "pending"
        assert record.registration_id is not None and record.outbox_id is not None
        outbox = session.get(OtpOutbox, record.outbox_id)
        assert outbox is not None and outbox.status == "failed"
        assert session.scalar(select(StudentRegistration)) is not None
        baseline = _counts(session)

    app.dependency_overrides[endpoint.get_otp_sender] = lambda: sender
    exact = client.post(
        "/api/v1/auth/student/register",
        headers={"Idempotency-Key": KEY},
        json=_payload(),
    )
    mismatch = client.post(
        "/api/v1/auth/student/register",
        headers={"Idempotency-Key": KEY},
        json=_payload(last_name="Shah"),
    )
    assert exact.status_code == 201
    assert exact.json() == first.json()
    assert mismatch.status_code == 409
    assert failing.attempts == 1 and sender.sent == []
    with factory() as session:
        assert _counts(session) == baseline
        record = session.scalar(select(RegistrationIdempotencyRecord))
        outbox = session.get(OtpOutbox, record.outbox_id)
        outbox.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()

    retried = client.post(
        "/api/v1/auth/student/register",
        headers={"Idempotency-Key": KEY},
        json=_payload(),
    )
    assert retried.status_code == 201
    assert retried.json() == first.json()
    assert len(sender.sent) == 1
    with factory() as session:
        record = session.scalar(select(RegistrationIdempotencyRecord))
        assert record is not None and record.state == "succeeded"
        assert record.outbox_id is None


def test_activation_retires_and_removes_match_oracle(http_ctx):
    client, factory, sender, _app = http_ctx
    created = client.post(
        "/api/v1/auth/student/register",
        headers={"Idempotency-Key": KEY},
        json=_payload(),
    )
    assert created.status_code == 201
    with factory() as session:
        registration_id = session.scalar(select(StudentRegistration.id))
    assert registration_id is not None
    verified = client.post(
        "/api/v1/auth/student/otp/verify",
        json={"code": sender.sent[0][1]},
    )
    assert verified.status_code == 200
    with factory() as session:
        record = session.scalar(select(RegistrationIdempotencyRecord))
        assert record is not None and record.state == "retired"
        assert record.request_fingerprint is None
        assert record.registration_id is None and record.outbox_id is None
        baseline = _counts(session)

    signatures = []
    for body in (_payload(), _payload(last_name="Shah")):
        replay = client.post(
            "/api/v1/auth/student/register",
            headers={"Idempotency-Key": KEY},
            json=body,
        )
        signatures.append((replay.status_code, replay.json()))
    assert signatures[0] == signatures[1]
    assert signatures[0][0] == 409
    assert signatures[0][1]["detail"]["code"] == "registration_replay_expired"
    with factory() as session:
        assert _counts(session) == baseline
    assert len(sender.sent) == 1


@pytest.mark.parametrize("mode", ("anonymise", "delete"))
def test_pending_otp_retention_is_uniform_erased_tombstone(db_session, mode):
    request = _request()
    result = registration_service.register_student(
        db_session, request, idempotency_key=KEY, now=NOW
    )
    _attach_signup_flow(db_session, result)
    registration_id = result.registration.id
    challenge = db_session.scalar(
        select(OtpChallenge).where(OtpChallenge.registration_id == registration_id)
    )
    assert challenge is not None
    challenge.created_at = NOW - timedelta(days=10)
    flow = db_session.scalar(select(OtpFlow))
    assert flow is not None
    flow.expires_at = NOW - timedelta(seconds=1)
    db_session.commit()

    counts = purge_expired(
        db_session,
        now=NOW,
        policy=RetentionPolicy(None, None, 1, None, None, mode),
    )
    db_session.commit()
    record = db_session.scalar(select(RegistrationIdempotencyRecord))
    assert counts["registrations"] == 1
    assert counts["otp_flows"] == 1
    assert counts["otp_expired_registrations"] == 1
    assert counts["otp_challenges"] == 0
    assert db_session.scalar(select(OtpChallenge)) is None
    assert db_session.scalar(select(OtpOutbox)) is None
    assert db_session.scalar(select(OtpFlow)) is None
    assert record is not None and record.state == "erased"
    assert record.request_fingerprint is None and record.registration_id is None
    if mode == "delete":
        assert db_session.get(StudentRegistration, registration_id) is None
    else:
        assert db_session.get(StudentRegistration, registration_id).status == "deleted"
    audit = db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "student.registration.otp_retention_expired"
        )
    )
    assert audit is not None and audit.after_state == {"mode": mode}

    for candidate in (request, _request(last_name="Shah")):
        with pytest.raises(registration_service.RegistrationError) as caught:
            registration_service.resolve_idempotent_replay(
                db_session, KEY, candidate, now=NOW
            )
        assert (caught.value.status_code, caught.value.code) == (
            409,
            "registration_replay_expired",
        )


def test_succeeded_otp_retention_preserves_registration_and_ledger(db_session):
    request = _request()
    result = registration_service.register_student(
        db_session, request, idempotency_key=KEY, now=NOW
    )
    _attach_signup_flow(db_session, result)
    db_session.commit()
    sender = CapturingSender()
    registration_service.finalize_pending_registration(
        db_session,
        registration_service.registration_idempotency_key_hash(KEY),
        sender,
        now=NOW,
    )
    registration_id = result.registration.id
    challenge = db_session.scalar(
        select(OtpChallenge).where(OtpChallenge.registration_id == registration_id)
    )
    challenge.created_at = NOW - timedelta(days=10)
    db_session.commit()

    counts = purge_expired(
        db_session,
        now=NOW,
        policy=RetentionPolicy(None, None, 1, None, None, "delete"),
    )
    db_session.commit()
    record = db_session.scalar(select(RegistrationIdempotencyRecord))
    assert counts["registrations"] == 0 and counts["otp_challenges"] == 1
    assert record is not None and record.state == "succeeded"
    assert db_session.get(StudentRegistration, registration_id) is not None
    replay = registration_service.resolve_idempotent_replay(
        db_session, KEY, request, now=NOW
    )
    assert replay is not None and replay.delivery is None


def test_registration_relay_does_not_count_concurrent_terminal_observation(
    http_ctx,
    monkeypatch,
):
    _client, factory, _request_sender, _app = http_ctx
    operation_now = datetime.now(timezone.utc)
    with factory() as session:
        result = registration_service.register_student(
            session,
            _request(),
            idempotency_key=KEY,
            now=operation_now,
        )
        _attach_signup_flow(session, result, now=operation_now)
        outbox_id = result.delivery.outbox_id
        session.commit()

    class ConcurrentWinner:
        newly_delivered = False

    def observe_concurrent_winner(session, key_hash, _sender):
        record = session.scalar(
            select(RegistrationIdempotencyRecord).where(
                RegistrationIdempotencyRecord.idempotency_key_hash == key_hash
            )
        )
        assert record is not None and record.outbox_id == outbox_id
        row = session.get(OtpOutbox, outbox_id)
        assert row is not None
        row.status = "sent"
        row.delivered_at = operation_now
        row.code_ct = None
        row.destination_ct = None
        record.state = "succeeded"
        record.outbox_id = None
        session.commit()
        return ConcurrentWinner()

    monkeypatch.setattr(
        registration_service,
        "finalize_pending_registration_with_result",
        observe_concurrent_winner,
        raising=False,
    )
    monkeypatch.setattr(
        registration_service,
        "finalize_pending_registration",
        observe_concurrent_winner,
    )
    relay_sender = CapturingSender()

    report = otp_outbox_relay.relay_pending(
        session_factory=factory,
        sender=relay_sender,
    )

    assert report == otp_outbox_relay.RelayResult(
        examined=1,
        delivered=0,
        failed=0,
    )
    assert relay_sender.sent == []


def test_result_finalizer_reports_only_its_actual_provider_delivery(db_session):
    result = registration_service.register_student(
        db_session,
        _request(),
        idempotency_key=KEY,
        now=NOW,
    )
    _attach_signup_flow(db_session, result)
    db_session.commit()
    sender = CapturingSender()
    key_hash = registration_service.registration_idempotency_key_hash(KEY)

    first = registration_service.finalize_pending_registration_with_result(
        db_session,
        key_hash,
        sender,
        now=NOW,
    )
    observed = registration_service.finalize_pending_registration_with_result(
        db_session,
        key_hash,
        sender,
        now=NOW,
    )
    public_result = registration_service.finalize_pending_registration(
        db_session,
        key_hash,
        sender,
        now=NOW,
    )

    assert first.registration.id == result.registration.id
    assert first.newly_delivered is True
    assert observed.registration.id == result.registration.id
    assert observed.newly_delivered is False
    assert isinstance(public_result, StudentRegistration)
    assert public_result.id == result.registration.id
    assert len(sender.sent) == 1


def test_pending_finalizer_retires_expired_flow_without_provider_io(
    db_session,
):
    result = registration_service.register_student(
        db_session, _request(), idempotency_key=KEY, now=NOW
    )
    _attach_signup_flow(db_session, result)
    flow = db_session.scalar(select(OtpFlow))
    assert flow is not None
    flow.expires_at = NOW
    db_session.commit()
    sender = CapturingSender()

    with pytest.raises(registration_service.RegistrationError) as caught:
        registration_service.finalize_pending_registration(
            db_session,
            registration_service.registration_idempotency_key_hash(KEY),
            sender,
            now=NOW,
        )
    assert (caught.value.status_code, caught.value.code) == (
        409,
        "registration_replay_expired",
    )
    assert sender.sent == []
    record = db_session.scalar(select(RegistrationIdempotencyRecord))
    assert record is not None
    assert record.state == "retired"
    assert record.registration_id is None and record.outbox_id is None
    assert record.request_fingerprint is None
    assert record.request_fingerprint_version is None
    row = db_session.scalar(select(OtpOutbox))
    assert row is not None
    assert (row.status, row.code_ct, row.destination_ct) == (
        "void",
        None,
        None,
    )
    assert flow.state == "expired"


def test_pending_finalizer_maps_prefenced_claim_race_to_expired(
    db_session,
    monkeypatch,
):
    result = registration_service.register_student(
        db_session, _request(), idempotency_key=KEY, now=NOW
    )
    _attach_signup_flow(db_session, result)
    db_session.commit()
    run_delivery = otp_outbox.run_delivery

    def pre_fence_then_claim(session, intent, sender, **kwargs):
        graph = otp_outbox._locked_graph(session, intent.outbox_id)
        assert graph is not None
        otp_outbox._fence_unavailable_delivery(
            session,
            graph,
            now=NOW,
            reason="otp_flow_expired",
        )
        session.commit()
        return run_delivery(session, intent, sender, **kwargs)

    monkeypatch.setattr(otp_outbox, "run_delivery", pre_fence_then_claim)
    sender = CapturingSender()

    with pytest.raises(registration_service.RegistrationError) as caught:
        registration_service.finalize_pending_registration(
            db_session,
            registration_service.registration_idempotency_key_hash(KEY),
            sender,
            now=NOW,
        )

    assert (caught.value.status_code, caught.value.code) == (
        409,
        "registration_replay_expired",
    )
    assert sender.sent == []
    record = db_session.scalar(select(RegistrationIdempotencyRecord))
    assert record is not None and record.state == "retired"


def test_invalid_retention_mode_rejects_before_mutation(db_session):
    registration_service.register_student(
        db_session, _request(), idempotency_key=KEY, now=NOW
    )
    db_session.commit()
    before = _counts(db_session)
    with pytest.raises(ValueError, match="retention mode"):
        purge_expired(
            db_session,
            now=NOW,
            policy=RetentionPolicy(0, 0, 0, 0, None, "unsafe"),
        )
    db_session.commit()
    assert _counts(db_session) == before


def test_pending_resend_reuses_claim_and_replay_delivers_only_once(db_session):
    result = registration_service.register_student(
        db_session, _request(), idempotency_key=KEY, now=NOW
    )
    _attach_signup_flow(db_session, result)
    original_outbox = result.delivery.outbox_id
    authority = db_session.scalar(
        select(OtpPurposeAuthority).where(
            OtpPurposeAuthority.registration_id == result.registration.id,
            OtpPurposeAuthority.purpose == "signup",
        )
    )
    assert authority is not None
    authority.cooldown_until = NOW - timedelta(seconds=1)
    db_session.commit()
    _challenge, replacement = otp_service.resend(
        db_session,
        result.registration.id,
        NOW,
        purpose="signup",
        destination="9876543210",
    )
    db_session.commit()
    record = db_session.scalar(select(RegistrationIdempotencyRecord))
    assert record.outbox_id == replacement.outbox_id == original_outbox
    assert db_session.get(OtpOutbox, original_outbox).status == "pending"

    sender = CapturingSender()
    registration_service.finalize_pending_registration(
        db_session,
        registration_service.registration_idempotency_key_hash(KEY),
        sender,
        now=NOW,
    )
    assert len(sender.sent) == 1
    assert db_session.scalar(select(RegistrationIdempotencyRecord)).state == "succeeded"


def test_http_resend_closes_crash_pending_claim_without_later_replay(http_ctx):
    client, factory, sender, app = http_ctx
    failing = FailingSender()
    app.dependency_overrides[endpoint.get_otp_sender] = lambda: failing
    registered = client.post(
        "/api/v1/auth/student/register",
        headers={"Idempotency-Key": KEY},
        json=_payload(),
    )
    assert registered.status_code == 201
    with factory() as session:
        record = session.scalar(select(RegistrationIdempotencyRecord))
        assert record is not None and record.registration_id is not None
        registration_id = record.registration_id
        authority = session.scalar(
            select(OtpPurposeAuthority).where(
                OtpPurposeAuthority.registration_id == registration_id,
                OtpPurposeAuthority.purpose == "signup",
            )
        )
        outbox = session.get(OtpOutbox, record.outbox_id)
        assert authority is not None and outbox is not None
        authority.cooldown_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        outbox.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()

    app.dependency_overrides[endpoint.get_otp_sender] = lambda: sender
    response = client.post(
        "/api/v1/auth/student/otp/resend",
        json={},
    )
    assert response.status_code == 202
    assert len(sender.sent) == 1
    with factory() as session:
        record = session.scalar(select(RegistrationIdempotencyRecord))
        assert record is not None and record.state == "succeeded"
        assert record.registration_id == registration_id
        assert record.outbox_id is None


def test_retention_reconciles_pending_sent_window_as_success(db_session):
    result = registration_service.register_student(
        db_session, _request(), idempotency_key=KEY, now=NOW
    )
    _attach_signup_flow(db_session, result)
    registration_id = result.registration.id
    challenge = db_session.scalar(
        select(OtpChallenge).where(OtpChallenge.registration_id == registration_id)
    )
    sender = CapturingSender()
    from app.services import otp_outbox

    assert otp_outbox.run_delivery(
        db_session,
        result.delivery,
        sender,
        raise_on_failure=True,
        now=NOW,
    )
    outbox = db_session.get(OtpOutbox, result.delivery.outbox_id)
    challenge.created_at = NOW - timedelta(days=10)
    outbox.delivered_at = NOW - timedelta(days=10)
    db_session.commit()

    counts = purge_expired(
        db_session,
        now=NOW,
        policy=RetentionPolicy(None, None, 1, None, None, "delete"),
    )
    db_session.commit()
    record = db_session.scalar(select(RegistrationIdempotencyRecord))
    assert counts["registrations"] == 0 and counts["otp_challenges"] == 1
    assert record is not None and record.state == "succeeded"
    assert record.registration_id == registration_id and record.outbox_id is None
    assert db_session.get(StudentRegistration, registration_id) is not None


def test_expired_crash_pending_replay_retires_and_never_sends_unusable_code(
    db_session,
):
    request = _request()
    result = registration_service.register_student(
        db_session, request, idempotency_key=KEY, now=NOW
    )
    _attach_signup_flow(db_session, result)
    challenge = db_session.scalar(
        select(OtpChallenge).where(
            OtpChallenge.registration_id == result.registration.id
        )
    )
    expired_at = NOW - timedelta(seconds=1)
    challenge.expires_at = expired_at
    flow = db_session.scalar(select(OtpFlow))
    assert flow is not None
    flow.expires_at = expired_at
    db_session.commit()
    sender = CapturingSender()
    with pytest.raises(registration_service.RegistrationError) as caught:
        registration_service.resolve_idempotent_replay(
            db_session, KEY, request, now=NOW
        )
    assert (caught.value.status_code, caught.value.code) == (
        409,
        "registration_replay_expired",
    )
    assert sender.sent == []
    record = db_session.scalar(select(RegistrationIdempotencyRecord))
    assert record is not None and record.state == "retired"
    assert record.registration_id is None and record.outbox_id is None
    outbox = db_session.scalar(select(OtpOutbox))
    assert outbox is not None and outbox.status == "void"
    assert outbox.code_ct is None and outbox.destination_ct is None


def test_retention_after_activation_preserves_retired_first_cause(db_session):
    request = _request()
    result = registration_service.register_student(
        db_session, request, idempotency_key=KEY, now=NOW
    )
    _attach_signup_flow(db_session, result)
    db_session.commit()
    sender = CapturingSender()
    registration_service.finalize_pending_registration(
        db_session,
        registration_service.registration_idempotency_key_hash(KEY),
        sender,
        now=NOW,
    )
    otp_service.verify(
        db_session,
        result.registration.id,
        sender.sent[0][1],
        NOW,
        purpose="signup",
    )
    registration = db_session.get(StudentRegistration, result.registration.id)
    registration.updated_at = NOW - timedelta(days=10)
    db_session.commit()

    purge_expired(
        db_session,
        now=NOW,
        policy=RetentionPolicy(None, 1, None, None, None, "anonymise"),
    )
    db_session.commit()
    record = db_session.scalar(select(RegistrationIdempotencyRecord))
    assert record is not None and record.state == "retired"
    assert record.registration_id is None and record.request_fingerprint is None


@pytest.mark.parametrize("winner_state", ("failed", "retired", "erased"))
def test_resend_helper_accepts_only_safe_winner_unlink(
    db_session, monkeypatch, winner_state
):
    result = registration_service.register_student(
        db_session, _request(), idempotency_key=KEY, now=NOW
    )
    db_session.commit()
    terminal = RegistrationIdempotencyRecord(
        idempotency_key_hash=registration_service.registration_idempotency_key_hash(
            KEY
        ),
        request_fingerprint=("a" * 64 if winner_state == "failed" else None),
        request_fingerprint_version=(
            registration_service.REGISTRATION_REQUEST_FINGERPRINT_VERSION
            if winner_state == "failed"
            else None
        ),
        state=winner_state,
        outcome_code=(
            "otp_delivery_failed"
            if winner_state == "failed"
            else "registration_replay_expired"
        ),
        registration_id=None,
        outbox_id=None,
    )
    monkeypatch.setattr(
        registration_service,
        "_ledger_by_key_hash",
        lambda *_args, **_kwargs: terminal,
    )
    assert (
        registration_service.finalize_pending_resend_if_claimed(
            db_session,
            result.registration.id,
            result.delivery,
            CapturingSender(),
        )
        is False
    )


def test_resend_helper_rejects_corrupt_reassignment(db_session, monkeypatch):
    result = registration_service.register_student(
        db_session, _request(), idempotency_key=KEY, now=NOW
    )
    db_session.commit()
    corrupt = db_session.scalar(select(RegistrationIdempotencyRecord))
    db_session.expunge(corrupt)
    corrupt.registration_id = uuid.uuid4()
    monkeypatch.setattr(
        registration_service,
        "_ledger_by_key_hash",
        lambda *_args, **_kwargs: corrupt,
    )
    with pytest.raises(RuntimeError):
        registration_service.finalize_pending_resend_if_claimed(
            db_session,
            result.registration.id,
            result.delivery,
            CapturingSender(),
        )


def test_resend_helper_threads_one_explicit_operation_clock(
    db_session, monkeypatch
):
    result = registration_service.register_student(
        db_session, _request(), idempotency_key=KEY, now=NOW
    )
    db_session.commit()
    observed = {}

    def finalize(_session, key_hash, _sender, *, now=None):
        observed["key_hash"] = key_hash
        observed["now"] = now

    monkeypatch.setattr(
        registration_service, "finalize_pending_registration", finalize
    )
    assert registration_service.finalize_pending_resend_if_claimed(
        db_session,
        result.registration.id,
        result.delivery,
        CapturingSender(),
        now=NOW,
    )
    assert observed == {
        "key_hash": registration_service.registration_idempotency_key_hash(KEY),
        "now": NOW,
    }


def test_resend_worker_threads_clock_to_claim_and_fallback(monkeypatch):
    observed = {}

    class Context:
        def __enter__(self):
            return object()

        def __exit__(self, *_args):
            return False

    def finalize(_session, _registration_id, _intent, _sender, *, now=None):
        observed["claim_now"] = now
        return False

    def deliver(_session, _intent, _sender, *, raise_on_failure, now=None):
        observed["delivery_now"] = now
        observed["raise_on_failure"] = raise_on_failure
        return True

    monkeypatch.setattr(
        registration_service, "finalize_pending_resend_if_claimed", finalize
    )
    monkeypatch.setattr(otp_outbox_relay.otp_outbox, "run_delivery", deliver)
    otp_outbox_relay.deliver_resend_after_response(
        uuid.uuid4(),
        uuid.uuid4(),
        CapturingSender(),
        lambda: Context(),
        now=NOW,
    )
    assert observed == {
        "claim_now": NOW,
        "delivery_now": NOW,
        "raise_on_failure": False,
    }


def test_corrupt_resend_and_finalizer_fail_without_mutation(db_session):
    a = registration_service.register_student(
        db_session, _request(), idempotency_key=KEY, now=NOW
    )
    b = registration_service.register_student(
        db_session,
        _request(mobile="9876543211", institutional_email="b@nls.ac.in"),
        now=NOW,
    )
    _attach_signup_flow(db_session, a)
    endpoint._signup_flow(
        db_session,
        b,
        raw_token="corrupt-resend-fixture-b-flow",
        destination="9876543211",
        now=NOW,
    )
    db_session.commit()
    record = db_session.scalar(select(RegistrationIdempotencyRecord))
    record.outbox_id = b.delivery.outbox_id
    db_session.commit()
    before = (
        record.state,
        record.registration_id,
        record.outbox_id,
        _counts(db_session),
    )
    with pytest.raises(RuntimeError):
        otp_service.resend(
            db_session,
            a.registration.id,
            NOW + timedelta(minutes=2),
            purpose="signup",
            destination="9876543210",
        )
    db_session.rollback()
    sender = CapturingSender()
    with pytest.raises(RuntimeError):
        registration_service.finalize_pending_registration(
            db_session,
            registration_service.registration_idempotency_key_hash(KEY),
            sender,
            now=NOW,
        )
    db_session.rollback()
    record = db_session.scalar(select(RegistrationIdempotencyRecord))
    assert (
        record.state,
        record.registration_id,
        record.outbox_id,
        _counts(db_session),
    ) == before
    assert sender.sent == []


class _Diagnostic:
    def __init__(self, name: str) -> None:
        self.constraint_name = name


class _DriverFailure(Exception):
    def __init__(self, name: str) -> None:
        super().__init__("constraint failure")
        self.diag = _Diagnostic(name)


def _integrity_error(name: str) -> IntegrityError:
    return IntegrityError("statement redacted", {}, _DriverFailure(name))


def test_integrity_recovery_resolves_both_known_constraints_and_reraises_unknown(
    db_session,
):
    request = _request()
    winner = registration_service.register_student(
        db_session, request, idempotency_key=KEY, now=NOW
    )
    _attach_signup_flow(db_session, winner)
    db_session.commit()
    for name in (
        endpoint._REGISTRATION_IDEMPOTENCY_CONSTRAINT,
        endpoint._REGISTRATION_MOBILE_CONSTRAINT,
    ):
        recovered = endpoint._recover_registration_integrity_conflict(
            db_session, request, KEY, _integrity_error(name), now=NOW
        )
        assert recovered.registration.id == winner.registration.id
        assert recovered.replayed is True

    unknown = _integrity_error("uq_unrelated_private_constraint")
    with pytest.raises(IntegrityError) as caught:
        endpoint._recover_registration_integrity_conflict(
            db_session, request, KEY, unknown, now=NOW
        )
    assert caught.value is unknown


def test_integrity_recovery_returns_typed_neutral_winner_or_conflict(
    db_session,
):
    real = registration_service.register_student(
        db_session,
        _request(),
        idempotency_key="neutral-integrity-real-seed",
        now=NOW,
    )
    assert isinstance(real, registration_service.RegistrationResult)
    endpoint._signup_flow(
        db_session,
        real,
        raw_token=otp_flow_service.deterministic_signup_token(
            "neutral-integrity-real-seed"
        ),
        destination=_request().mobile,
        now=NOW,
    )
    neutral_key = "neutral-integrity-race-key"
    neutral_request = _request(first_name="Duplicate")
    decoy = endpoint._decoy_signup_flow(
        db_session,
        payload=neutral_request,
        idempotency_key=neutral_key,
        now=NOW,
    )
    assert isinstance(decoy, tuple)
    db_session.commit()
    before = _counts(db_session)

    for name in (
        endpoint._REGISTRATION_IDEMPOTENCY_CONSTRAINT,
        endpoint._REGISTRATION_MOBILE_CONSTRAINT,
    ):
        recovered = endpoint._recover_registration_integrity_conflict(
            db_session,
            neutral_request,
            neutral_key,
            _integrity_error(name),
            now=NOW,
        )
        assert isinstance(
            recovered, registration_service.NeutralizedRegistrationReplay
        )
        db_session.rollback()

    with pytest.raises(HTTPException) as caught:
        endpoint._recover_registration_integrity_conflict(
            db_session,
            _request(first_name="Mutated"),
            neutral_key,
            _integrity_error(endpoint._REGISTRATION_IDEMPOTENCY_CONSTRAINT),
            now=NOW,
        )
    assert caught.value.status_code == 409
    assert caught.value.detail == {
        "code": "idempotency_conflict",
        "field": "Idempotency-Key",
    }
    db_session.rollback()
    assert _counts(db_session) == before


def test_second_ledger_read_dispatches_all_locked_winner_shapes(
    db_session,
    monkeypatch,
):
    original_lookup = registration_service._ledger_by_key_hash

    def resolve_from_forced_second_read(key, request):
        calls = 0

        def lookup(session, key_hash, *, for_update):
            nonlocal calls
            calls += 1
            if calls == 1:
                return None
            return original_lookup(
                session, key_hash, for_update=for_update
            )

        monkeypatch.setattr(
            registration_service, "_ledger_by_key_hash", lookup
        )
        try:
            return registration_service.resolve_idempotent_replay(
                db_session, key, request, now=NOW
            )
        finally:
            monkeypatch.setattr(
                registration_service,
                "_ledger_by_key_hash",
                original_lookup,
            )

    neutral_key = "neutral-second-ledger-read"
    neutral_request = _request(first_name="NeutralSecondRead")
    decoy = endpoint._decoy_signup_flow(
        db_session,
        payload=neutral_request,
        idempotency_key=neutral_key,
        now=NOW,
    )
    assert isinstance(decoy, tuple)
    db_session.commit()

    exact = resolve_from_forced_second_read(neutral_key, neutral_request)
    assert isinstance(
        exact, registration_service.NeutralizedRegistrationReplay
    )
    db_session.rollback()

    with pytest.raises(registration_service.RegistrationError) as mismatch:
        resolve_from_forced_second_read(
            neutral_key,
            _request(first_name="NeutralSecondReadMutation"),
        )
    assert (mismatch.value.status_code, mismatch.value.code) == (
        409,
        "idempotency_conflict",
    )
    db_session.rollback()

    record = db_session.scalar(
        select(RegistrationIdempotencyRecord).where(
            RegistrationIdempotencyRecord.idempotency_key_hash
            == registration_service.registration_idempotency_key_hash(
                neutral_key
            )
        )
    )
    flow = db_session.scalar(
        select(OtpFlow).where(
            OtpFlow.registration_idempotency_record_id == record.id
        )
    )
    flow.expires_at = NOW - timedelta(seconds=1)
    db_session.commit()
    with pytest.raises(
        registration_service.RegistrationError
    ) as expired_mutation:
        resolve_from_forced_second_read(
            neutral_key,
            _request(first_name="ExpiredFingerprintMustNotMatter"),
        )
    assert (expired_mutation.value.status_code, expired_mutation.value.code) == (
        409,
        "registration_replay_expired",
    )
    record = db_session.scalar(
        select(RegistrationIdempotencyRecord).where(
            RegistrationIdempotencyRecord.idempotency_key_hash
            == registration_service.registration_idempotency_key_hash(
                neutral_key
            )
        )
    )
    assert record.state == "retired"
    db_session.rollback()

    real_key = "real-second-ledger-read"
    real_request = _request(
        mobile="9876543212",
        institutional_email="second-read@nls.ac.in",
    )
    real = registration_service.register_student(
        db_session,
        real_request,
        idempotency_key=real_key,
        now=NOW,
    )
    assert isinstance(real, registration_service.RegistrationResult)
    endpoint._signup_flow(
        db_session,
        real,
        raw_token=otp_flow_service.deterministic_signup_token(real_key),
        destination=real_request.mobile,
        now=NOW,
    )
    db_session.commit()
    replay = resolve_from_forced_second_read(real_key, real_request)
    assert isinstance(replay, registration_service.RegistrationResult)
    assert replay.registration.id == real.registration.id
    assert replay.replayed is True


def test_decoy_flush_and_commit_losers_resolve_exact_or_typed_mismatch(
    db_session,
    monkeypatch,
):
    neutral_key = "neutral-decoy-flush-commit-race"
    neutral_request = _request(first_name="NeutralWinner")
    seeded = endpoint._decoy_signup_flow(
        db_session,
        payload=neutral_request,
        idempotency_key=neutral_key,
        now=NOW,
    )
    assert isinstance(seeded, tuple)
    db_session.commit()
    raw_token = otp_flow_service.deterministic_signup_token(neutral_key)
    graph = otp_flow_service.resolve_flow(db_session, raw_token)
    assert graph is not None
    existing_tuple = (raw_token, graph[1])
    db_session.rollback()
    before = (
        _counts(db_session),
        db_session.scalar(select(func.count(OtpFlow.id))),
    )

    def flush_loser(*args, **kwargs):
        del args, kwargs
        raise _integrity_error(endpoint._REGISTRATION_IDEMPOTENCY_CONSTRAINT)

    monkeypatch.setattr(endpoint, "_decoy_signup_flow", flush_loser)
    exact_flush = endpoint._commit_decoy_or_resolve_winner(
        db_session,
        neutral_request,
        neutral_key,
        now=NOW,
    )
    assert isinstance(
        exact_flush, registration_service.NeutralizedRegistrationReplay
    )
    db_session.rollback()
    with pytest.raises(HTTPException) as mismatch_flush:
        endpoint._commit_decoy_or_resolve_winner(
            db_session,
            _request(first_name="FlushMutation"),
            neutral_key,
            now=NOW,
        )
    assert mismatch_flush.value.status_code == 409
    assert mismatch_flush.value.detail["code"] == "idempotency_conflict"
    db_session.rollback()

    monkeypatch.setattr(
        endpoint,
        "_decoy_signup_flow",
        lambda *args, **kwargs: existing_tuple,
    )
    original_commit = db_session.commit

    def commit_loser():
        raise _integrity_error(endpoint._REGISTRATION_IDEMPOTENCY_CONSTRAINT)

    monkeypatch.setattr(db_session, "commit", commit_loser)
    exact_commit = endpoint._commit_decoy_or_resolve_winner(
        db_session,
        neutral_request,
        neutral_key,
        now=NOW,
    )
    assert isinstance(
        exact_commit, registration_service.NeutralizedRegistrationReplay
    )
    db_session.rollback()
    with pytest.raises(HTTPException) as mismatch_commit:
        endpoint._commit_decoy_or_resolve_winner(
            db_session,
            _request(first_name="CommitMutation"),
            neutral_key,
            now=NOW,
        )
    assert mismatch_commit.value.status_code == 409
    assert mismatch_commit.value.detail["code"] == "idempotency_conflict"
    db_session.rollback()
    monkeypatch.setattr(db_session, "commit", original_commit)
    assert (
        _counts(db_session),
        db_session.scalar(select(func.count(OtpFlow.id))),
    ) == before


def test_legacy_terminalization_ambiguity_has_zero_partial_mutation(db_session):
    first = registration_service.register_student(
        db_session, _request(), idempotency_key=KEY, now=NOW
    )
    second = registration_service.register_student(
        db_session,
        _request(mobile="9876543211", institutional_email="second@nls.ac.in"),
        now=NOW,
    ).registration
    second.idempotency_key = KEY
    second.idempotency_key_legacy = True
    db_session.commit()
    record = db_session.scalar(select(RegistrationIdempotencyRecord))
    before = (record.state, record.registration_id, record.outbox_id, second.idempotency_key)

    with pytest.raises(RuntimeError):
        registration_service.terminalize_registration_idempotency(
            db_session, second, state="erased"
        )
    # Even a caller that catches and commits cannot persist a partial raw-key clear.
    db_session.commit()
    record = db_session.scalar(select(RegistrationIdempotencyRecord))
    second = db_session.get(StudentRegistration, second.id)
    assert (record.state, record.registration_id, record.outbox_id, second.idempotency_key) == before
    assert first.registration.id == record.registration_id
