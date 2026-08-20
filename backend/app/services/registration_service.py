"""Server-authoritative student registration (SAATHI-421/448).

Transactional persistence of a registration + consent + OTP challenge (verifier
only) + outbox delivery intent + audit event. Sensitive fields are keyed-hashed
for uniqueness and Fernet-encrypted (version-stamped) for display; raw
mobile/DOB/OTP/enrolment never touch plaintext columns, logs or the audit
snapshot.

This function performs all writes and FLUSHES but does NOT commit — the caller
(endpoint) commits and then delivers the OTP via the outbox, so an OTP is never
handed to a provider before the transaction commits. It returns a
``RegistrationResult`` carrying the registration and an optional DeliveryIntent
(absent after finalized success; a crash-pending exact replay carries the same
persisted intent into the serialized finalizer, never a second outbox row).
"""
from __future__ import annotations

import hmac
import json
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import active_key_version, encrypt, keyed_hash
from app.db.models.audit import AuditEvent
from app.models.registration import (
    Consent,
    GuardianConsent,
    OtpChallenge,
    OtpOutbox,
    RegistrationIdempotencyRecord,
    StudentProfile,
    StudentRegistration,
    StudentVerification,
    User,
)
from app.schemas.registration import StudentRegisterRequest
from app.services import otp_outbox
from app.services.otp_sender import OtpSendError, OtpSender

AGE_OF_MAJORITY = 18
REGISTRATION_REQUEST_FINGERPRINT_VERSION = "v1"
_REGISTRATION_REQUEST_FINGERPRINT_CONTRACT = "student-registration-request"
REGISTRATION_REQUEST_V1_FIELDS = frozenset(
    {
        "first_name",
        "middle_name",
        "last_name",
        "mobile",
        "dob",
        "consent",
        "college",
        "year_of_study",
        "enrolment_number",
        "institutional_email",
        "bar_enrolment_number",
    }
)
REGISTRATION_REQUEST_V1_CONSENT_FIELDS = frozenset(
    {"accepted", "policy_version"}
)
_REGISTRATION_REQUEST_V1_REQUIRED_FIELDS = frozenset(
    {"first_name", "last_name", "mobile", "dob", "consent"}
)
_REGISTRATION_REQUEST_V1_NULL_DEFAULT_FIELDS = (
    REGISTRATION_REQUEST_V1_FIELDS - _REGISTRATION_REQUEST_V1_REQUIRED_FIELDS
)
_IDEMPOTENCY_UNSAFE = re.compile(r"[\x00-\x1f\x7f]")


class RegistrationError(Exception):
    def __init__(self, status_code: int, code: str, field: str | None = None) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.field = field


@dataclass
class RegistrationResult:
    registration: StudentRegistration
    delivery: otp_outbox.DeliveryIntent | None
    idempotency_record: RegistrationIdempotencyRecord | None = None
    replayed: bool = False


def _is_minor(dob: date, today: date | None = None) -> bool:
    today = today or date.today()
    years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return years < AGE_OF_MAJORITY


def validate_idempotency_key(key: str | None) -> str | None:
    """Validate the optional wire token before it can reach ``VARCHAR(200)``.

    The key is opaque and therefore is not trimmed or otherwise rewritten. It
    must contain 1..200 characters. Edge whitespace and C0/DEL controls are
    rejected; ordinary internal characters remain exact opaque content. Invalid
    keys fail with a typed, non-echoing error before the database can observe
    the value.
    """

    if key is None:
        return None
    if (
        not 1 <= len(key) <= 200
        or key != key.strip()
        or _IDEMPOTENCY_UNSAFE.search(key)
    ):
        raise RegistrationError(422, "invalid_idempotency_key", "Idempotency-Key")
    return key


def registration_idempotency_key_hash(key: str) -> str:
    """Return the domain-separated keyed HMAC used as the ledger lookup key."""

    return keyed_hash(f"registration-idempotency-key:v1:{key}")


def registration_request_fingerprint(req: StudentRegisterRequest) -> str:
    """Return the v1 keyed fingerprint of the complete validated request.

    ``mode='json'`` provides stable JSON-native date values, explicit nulls
    preserve optional-field meaning, and the envelope versions the canonical
    contract independently of encryption-key rotation. Only the keyed HMAC is
    stored; neither these canonical bytes nor any raw request value is retained.
    """

    # This assertion deliberately prevents a future request-schema field from
    # silently changing v1 bytes. Adding a field requires an explicit mapping,
    # reviewed version decision, and replay-compatibility tests.
    if set(StudentRegisterRequest.model_fields) != REGISTRATION_REQUEST_V1_FIELDS:
        raise RuntimeError("registration request fingerprint v1 schema mismatch")
    if set(req.consent.__class__.model_fields) != REGISTRATION_REQUEST_V1_CONSENT_FIELDS:
        raise RuntimeError("registration consent fingerprint v1 schema mismatch")
    request_fields = StudentRegisterRequest.model_fields
    if any(
        not request_fields[name].is_required()
        for name in _REGISTRATION_REQUEST_V1_REQUIRED_FIELDS
    ) or any(
        request_fields[name].default is not None
        for name in _REGISTRATION_REQUEST_V1_NULL_DEFAULT_FIELDS
    ):
        raise RuntimeError("registration request fingerprint v1 defaults mismatch")
    consent_fields = req.consent.__class__.model_fields
    if (
        not consent_fields["accepted"].is_required()
        or consent_fields["policy_version"].default != "dpdp-2023.v1"
    ):
        raise RuntimeError("registration consent fingerprint v1 defaults mismatch")

    payload = {
        "bar_enrolment_number": req.bar_enrolment_number,
        "college": req.college,
        "consent": {
            "accepted": req.consent.accepted,
            "policy_version": req.consent.policy_version,
        },
        "dob": req.dob.isoformat(),
        "enrolment_number": req.enrolment_number,
        "first_name": req.first_name,
        "institutional_email": req.institutional_email,
        "last_name": req.last_name,
        "middle_name": req.middle_name,
        "mobile": req.mobile,
        "year_of_study": req.year_of_study,
    }
    canonical = json.dumps(
        {
            "contract": _REGISTRATION_REQUEST_FINGERPRINT_CONTRACT,
            "payload": payload,
            "version": REGISTRATION_REQUEST_FINGERPRINT_VERSION,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return keyed_hash(canonical)


def _ledger_by_key_hash(
    session: Session,
    key_hash: str,
    *,
    for_update: bool,
) -> RegistrationIdempotencyRecord | None:
    statement = select(RegistrationIdempotencyRecord).where(
        RegistrationIdempotencyRecord.idempotency_key_hash == key_hash
    )
    if for_update:
        statement = statement.with_for_update().execution_options(
            populate_existing=True
        )
    return session.scalar(statement)


def _ledger_is_safely_unlinked(record: RegistrationIdempotencyRecord) -> bool:
    """True only for a complete winner-unlinked terminal representation."""

    return bool(
        record.registration_id is None
        and record.outbox_id is None
        and (
            (
                record.state in {"retired", "erased"}
                and record.request_fingerprint is None
                and record.request_fingerprint_version is None
                and record.outcome_code == "registration_replay_expired"
            )
            or (
                record.state == "failed"
                and record.request_fingerprint is not None
                and record.request_fingerprint_version
                == REGISTRATION_REQUEST_FINGERPRINT_VERSION
                and record.outcome_code == "otp_delivery_failed"
            )
        )
    )


def resolve_idempotent_replay(
    session: Session,
    key: str,
    req: StudentRegisterRequest,
) -> RegistrationResult | None:
    """Return an exact-content replay or fail closed on key reuse.

    A pre-0018 row can carry an idempotency key without a verifiable request
    fingerprint. Treating it as a replay would recreate NYAY-17, so it is a
    typed conflict instead of an unsafe best-effort comparison.
    """

    key_hash = registration_idempotency_key_hash(key)
    record = _ledger_by_key_hash(session, key_hash, for_update=True)
    if record is None:
        # The raw column is historical-only after 0018. It has no trustworthy
        # request fingerprint, so it can reserve the key but never replay.
        legacy = session.scalar(
            select(StudentRegistration)
            .where(
                StudentRegistration.idempotency_key == key,
                StudentRegistration.idempotency_key_legacy.is_(True),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if legacy is None:
            # A concurrent activation/erasure can replace a raw legacy key with
            # a HMAC tombstone while this request waits on the registration
            # lock. Re-read the ledger before concluding the key is unused.
            record = _ledger_by_key_hash(session, key_hash, for_update=True)
            if record is None:
                return None
            if record.state in {"retired", "erased"}:
                raise RegistrationError(
                    409, "registration_replay_expired", "Idempotency-Key"
                )
            raise RegistrationError(
                409, "idempotency_conflict", "Idempotency-Key"
            )
        if (
            legacy.status != "otp_pending"
            or legacy.deleted_at is not None
            or legacy.dob_hash_state != "verified"
        ):
            raise RegistrationError(
                409, "registration_replay_expired", "Idempotency-Key"
            )
        raise RegistrationError(409, "idempotency_conflict", "Idempotency-Key")

    if record.state in {"retired", "erased"}:
        raise RegistrationError(
            409, "registration_replay_expired", "Idempotency-Key"
        )

    if record.state == "failed":
        expected = registration_request_fingerprint(req)
        if not hmac.compare_digest(record.request_fingerprint or "", expected):
            raise RegistrationError(
                409, "idempotency_conflict", "Idempotency-Key"
            )
        raise RegistrationError(502, "otp_delivery_failed")

    existing = session.scalar(
        select(StudentRegistration)
        .where(StudentRegistration.id == record.registration_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        existing is None
        or existing.status != "otp_pending"
        or existing.deleted_at is not None
        or existing.dob_hash_state != "verified"
    ):
        # Lifecycle is checked before content so stale bootstrap requests never
        # become a fingerprint-match oracle. Activation retires atomically;
        # this branch is a mutation-free defensive fallback for corrupt state.
        raise RegistrationError(
            409, "registration_replay_expired", "Idempotency-Key"
        )
    expected = registration_request_fingerprint(req)
    stored = record.request_fingerprint or ""
    if (
        record.request_fingerprint_version
        != REGISTRATION_REQUEST_FINGERPRINT_VERSION
        or len(stored) != 64
        or not hmac.compare_digest(stored, expected)
    ):
        raise RegistrationError(409, "idempotency_conflict", "Idempotency-Key")
    if record.state == "succeeded":
        return RegistrationResult(
            registration=existing,
            delivery=None,
            idempotency_record=record,
            replayed=True,
        )
    if record.state != "pending" or record.outbox_id is None:
        raise RuntimeError("registration idempotency ledger state is invalid")
    return RegistrationResult(
        registration=existing,
        delivery=otp_outbox.DeliveryIntent(outbox_id=record.outbox_id),
        idempotency_record=record,
        replayed=True,
    )


def lock_registration_with_idempotency(
    session: Session,
    registration_id: uuid.UUID,
) -> tuple[StudentRegistration | None, RegistrationIdempotencyRecord | None]:
    """Lock the ledger before its registration for lifecycle operations."""

    record_id = session.scalar(
        select(RegistrationIdempotencyRecord.id).where(
            RegistrationIdempotencyRecord.registration_id == registration_id
        )
    )
    record = None
    if record_id is not None:
        record = session.scalar(
            select(RegistrationIdempotencyRecord)
            .where(RegistrationIdempotencyRecord.id == record_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if record is not None and record.registration_id != registration_id:
            if not _ledger_is_safely_unlinked(record):
                raise RuntimeError("registration idempotency authority is ambiguous")
            # A lifecycle winner unlinked the ledger while this transaction
            # waited. Preserve its first terminal cause; it is no longer the
            # requested registration's mutable authority.
            record = None
    registration = session.scalar(
        select(StudentRegistration)
        .where(StudentRegistration.id == registration_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return registration, record


def terminalize_registration_idempotency(
    session: Session,
    registration: StudentRegistration,
    *,
    state: str,
    locked_record: RegistrationIdempotencyRecord | None = None,
) -> RegistrationIdempotencyRecord | None:
    """Retain a non-PII key tombstone while retiring bootstrap capability."""

    if state not in {"retired", "erased"}:
        raise ValueError("registration idempotency terminal state is invalid")
    record = locked_record
    if record is None:
        record = session.scalar(
            select(RegistrationIdempotencyRecord)
            .where(
                RegistrationIdempotencyRecord.registration_id
                == registration.id
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    if record is None and registration.idempotency_key:
        key_hash = registration_idempotency_key_hash(
            registration.idempotency_key
        )
        record = _ledger_by_key_hash(session, key_hash, for_update=True)
        if record is None:
            record = RegistrationIdempotencyRecord(
                idempotency_key_hash=key_hash,
                request_fingerprint=None,
                request_fingerprint_version=None,
                state=state,
                outcome_code="registration_replay_expired",
                registration_id=None,
                outbox_id=None,
            )
            session.add(record)
    if record is None:
        return None
    if record.state in {"retired", "erased"}:
        if (
            record.registration_id is not None
            or record.outbox_id is not None
            or record.request_fingerprint is not None
            or record.request_fingerprint_version is not None
            or record.outcome_code != "registration_replay_expired"
        ):
            raise RuntimeError("registration idempotency terminal state is invalid")
        # Preserve the first lifecycle terminal cause. Retention after
        # activation must not rewrite retired to erased (or vice versa).
        if registration.idempotency_key:
            registration.idempotency_key = None
            registration.idempotency_key_legacy = False
        return record
    if (
        record.registration_id != registration.id
    ):
        # A colliding/mixed-version authority must never be reassigned to a
        # different registration during retention. Preserve both graphs and
        # fail closed for operator investigation.
        raise RuntimeError("registration idempotency authority is ambiguous")
    if registration.idempotency_key:
        registration.idempotency_key = None
        registration.idempotency_key_legacy = False
    record.state = state
    record.outcome_code = "registration_replay_expired"
    record.request_fingerprint = None
    record.request_fingerprint_version = None
    record.registration_id = None
    record.outbox_id = None
    record.updated_at = datetime.now(timezone.utc)
    return record


def find_by_mobile(session: Session, mobile: str) -> StudentRegistration | None:
    return session.scalar(
        select(StudentRegistration).where(StudentRegistration.mobile_hash == keyed_hash(mobile))
    )


def compensate_delete(
    session: Session,
    registration_id: uuid.UUID,
    *,
    idempotency_record: RegistrationIdempotencyRecord | None = None,
    commit: bool = True,
) -> None:
    """Undo a just-committed registration after OTP delivery fails.

    Dialect-safe explicit teardown (does not rely on ON DELETE cascade being
    enabled on SQLite). Leaves the append-only audit row in place. HTTP delivery
    failure uses the default committed transaction so the observable end state
    has no committed-but-unusable challenge. ``commit=False`` remains available
    to compose the teardown into an already serialized outer transaction.
    """
    from app.models.registration import (
        Consent as _C,
        GuardianConsent as _G,
        OtpChallenge as _Ch,
        OtpOutbox as _O,
        StudentProfile as _P,
        StudentVerification as _V,
    )

    if idempotency_record is not None:
        idempotency_record.state = "failed"
        idempotency_record.outcome_code = "otp_delivery_failed"
        idempotency_record.registration_id = None
        idempotency_record.outbox_id = None
        idempotency_record.updated_at = datetime.now(timezone.utc)
        # Make the ledger row independently valid before deleting either FK
        # target. The keyed request fingerprint is deliberately retained.
        session.flush()
    reg = session.get(StudentRegistration, registration_id)
    if reg is None:
        if idempotency_record is not None and commit:
            session.commit()
        elif idempotency_record is not None:
            session.flush()
        return
    ch_ids = [c.id for c in session.scalars(select(_Ch).where(_Ch.registration_id == registration_id))]
    if ch_ids:
        for o in session.scalars(select(_O).where(_O.challenge_id.in_(ch_ids))):
            session.delete(o)
    for model in (_Ch, _C, _P, _V, _G):
        for row in session.scalars(select(model).where(model.registration_id == registration_id)):
            session.delete(row)
    user_id = reg.user_id
    session.delete(reg)
    session.flush()
    user = session.get(User, user_id)
    if user is not None:
        session.delete(user)
    # Record the failed-delivery compensation for auditability (non-PII).
    session.add(
        AuditEvent(
            actor_role="system",
            action="student.register.delivery_failed_rollback",
            resource_type="student_registration",
            resource_id=registration_id,
            after_state={"result": "rolled_back"},
        )
    )
    if commit:
        session.commit()
    else:
        session.flush()


def finalize_pending_registration(
    session: Session,
    key_hash: str,
    sender: OtpSender,
) -> StudentRegistration:
    """Finalize exactly one committed pending ledger row under row locks.

    The lock order is ledger -> registration -> challenge -> outbox. Concurrent
    same-key callers therefore wait for the first finalizer and observe only a
    terminal success/failure. A crash before delivery leaves ``pending`` and the
    persisted outbox link lets the next exact caller resume safely.
    """

    record = _ledger_by_key_hash(session, key_hash, for_update=True)
    if record is None:
        raise RuntimeError("registration idempotency ledger row disappeared")
    if record.state == "failed":
        raise RegistrationError(502, "otp_delivery_failed")
    if record.state in {"retired", "erased"}:
        raise RegistrationError(
            409, "registration_replay_expired", "Idempotency-Key"
        )
    registration = session.scalar(
        select(StudentRegistration)
        .where(StudentRegistration.id == record.registration_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        registration is None
        or registration.status != "otp_pending"
        or registration.deleted_at is not None
        or registration.dob_hash_state != "verified"
    ):
        raise RegistrationError(
            409, "registration_replay_expired", "Idempotency-Key"
        )
    if record.state == "succeeded":
        return registration
    if record.state != "pending" or record.outbox_id is None:
        raise RuntimeError("registration idempotency pending state is invalid")

    outbox_snapshot = session.get(OtpOutbox, record.outbox_id)
    challenge = None
    if outbox_snapshot is not None:
        challenge = session.scalar(
            select(OtpChallenge)
            .where(OtpChallenge.id == outbox_snapshot.challenge_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    if (
        challenge is None
        or outbox_snapshot is None
        or challenge.registration_id != registration.id
        or challenge.purpose != "signup"
        or outbox_snapshot.purpose != "signup"
    ):
        # Structural drift is not a provider failure. Do not mutate or delete
        # an otherwise valid graph while reporting a recoverable 502.
        raise RuntimeError("registration idempotency delivery graph is invalid")
    try:
        otp_outbox.run_delivery(
            session,
            otp_outbox.DeliveryIntent(outbox_id=record.outbox_id),
            sender,
            raise_on_failure=True,
            commit=False,
        )
    except OtpSendError as exc:
        compensate_delete(
            session,
            registration.id,
            idempotency_record=record,
        )
        raise RegistrationError(502, "otp_delivery_failed") from exc

    record.state = "succeeded"
    record.outcome_code = None
    record.outbox_id = None
    record.updated_at = datetime.now(timezone.utc)
    session.commit()
    return registration


def finalize_pending_resend_if_claimed(
    session: Session,
    registration_id: uuid.UUID,
    intent: otp_outbox.DeliveryIntent,
    sender: OtpSender,
) -> bool:
    """Finalize a replacement outbox through the pending registration claim.

    Returns ``False`` when this registration has no pending ledger (the caller
    must use ordinary outbox delivery). A pending ledger is delivered and
    marked succeeded by the common serialized finalizer in one transaction.
    """

    key_hash = session.scalar(
        select(RegistrationIdempotencyRecord.idempotency_key_hash).where(
            RegistrationIdempotencyRecord.registration_id == registration_id
        )
    )
    if key_hash is None:
        return False
    record = _ledger_by_key_hash(session, key_hash, for_update=True)
    if record is None:
        raise RuntimeError("registration idempotency resend state is invalid")
    if record.registration_id != registration_id:
        if _ledger_is_safely_unlinked(record):
            # A finalizer/activation/retention winner unlinked the claim while
            # this resend waited. Let the ordinary outbox path observe the
            # winner's void/missing child without turning the race into a 500.
            return False
        raise RuntimeError("registration idempotency resend state is invalid")
    if record.state == "succeeded":
        return False
    if record.state != "pending" or record.outbox_id != intent.outbox_id:
        raise RuntimeError("registration idempotency resend state is invalid")
    finalize_pending_registration(session, key_hash, sender)
    return True


def register_student(
    session: Session,
    req: StudentRegisterRequest,
    idempotency_key: str | None = None,
    now: datetime | None = None,
) -> RegistrationResult:
    now = now or datetime.now(timezone.utc)
    idempotency_key = validate_idempotency_key(idempotency_key)

    # Resolve a replay before any validation-dependent write. A valid key is
    # bound to the entire original accepted request, so changing even consent
    # under that key is an idempotency conflict rather than a new operation.
    if idempotency_key:
        existing = resolve_idempotent_replay(session, idempotency_key, req)
        if existing is not None:
            return existing

    if not req.consent.accepted:
        raise RegistrationError(422, "consent_required", "consent")

    mobile_hash = keyed_hash(req.mobile)
    if session.scalar(select(StudentRegistration).where(StudentRegistration.mobile_hash == mobile_hash)):
        raise RegistrationError(409, "mobile_already_registered", "mobile")

    minor = _is_minor(req.dob)
    key_version = active_key_version()
    user = User(role="student", status="pending")
    session.add(user)
    session.flush()

    reg = StudentRegistration(
        user_id=user.id,
        first_name=req.first_name,
        middle_name=req.middle_name,
        last_name=req.last_name,
        mobile_hash=mobile_hash,
        mobile_ct=encrypt(req.mobile),
        dob_hash=keyed_hash(req.dob.isoformat()),
        dob_ct=encrypt(req.dob.isoformat()),
        dob_hash_state="verified",
        key_version=key_version,
        institution_ref=req.college,
        status="otp_pending",
        is_minor=minor,
        idempotency_key=None,
        idempotency_key_legacy=False,
    )
    session.add(reg)
    session.flush()

    session.add(
        Consent(
            registration_id=reg.id,
            purpose="registration",
            accepted=True,
            policy_version=req.consent.policy_version,
            accepted_at=now,
        )
    )

    # OTP challenge via the shared lifecycle service (persists a keyed verifier
    # plus a pending outbox row with a short-lived encrypted delivery payload).
    # Imported lazily so OTP lifecycle code can reuse the ledger-first
    # registration lock without a module-import cycle.
    from app.services import otp_service

    _, intent = otp_service.issue_challenge(
        session, reg.id, now, purpose="signup", destination=req.mobile
    )

    if minor:
        session.add(GuardianConsent(registration_id=reg.id, status="pending", verified=False))

    # Academic profile (SAATHI-421) — encrypted + keyed hash for sensitive
    # identifiers; plain college/year for display; version-stamped.
    session.add(
        StudentProfile(
            registration_id=reg.id,
            college=req.college,
            year_of_study=req.year_of_study,
            key_version=key_version,
            enrolment_ct=encrypt(req.enrolment_number) if req.enrolment_number else None,
            enrolment_hash=keyed_hash(req.enrolment_number) if req.enrolment_number else None,
            institutional_email_ct=encrypt(req.institutional_email) if req.institutional_email else None,
            institutional_email_hash=keyed_hash(req.institutional_email, lower=True) if req.institutional_email else None,
            bar_enrolment_ct=encrypt(req.bar_enrolment_number) if req.bar_enrolment_number else None,
            bar_enrolment_hash=keyed_hash(req.bar_enrolment_number) if req.bar_enrolment_number else None,
        )
    )
    session.add(StudentVerification(registration_id=reg.id, method="institutional_email", status="pending"))

    # Redacted, non-PII audit snapshot on the shared audit_events table.
    session.add(
        AuditEvent(
            actor_role="student",
            action="student.register",
            resource_type="student_registration",
            resource_id=reg.id,
            after_state={"status": reg.status, "is_minor": minor, "key_version": key_version},
        )
    )
    idempotency_record = None
    if idempotency_key:
        idempotency_record = RegistrationIdempotencyRecord(
            idempotency_key_hash=registration_idempotency_key_hash(
                idempotency_key
            ),
            request_fingerprint=registration_request_fingerprint(req),
            request_fingerprint_version=REGISTRATION_REQUEST_FINGERPRINT_VERSION,
            state="pending",
            outcome_code=None,
            registration_id=reg.id,
            outbox_id=intent.outbox_id,
        )
        # Insert the ledger last: a concurrent loser rolls back its complete
        # graph when the exact key-hash UNIQUE is reported.
        session.add(idempotency_record)
    session.flush()
    return RegistrationResult(
        registration=reg,
        delivery=intent,
        idempotency_record=idempotency_record,
        replayed=False,
    )
