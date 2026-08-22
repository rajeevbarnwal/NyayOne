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
from app.services import otp_outbox
from app.services.otp_sender import IdempotentOtpSender, OtpSendError

AGE_OF_MAJORITY = 18
REGISTRATION_REQUEST_FINGERPRINT_VERSION = "v1"
_OTP_AUTHORITY_ID_NAMESPACE = uuid.UUID(
    "d4bd542f-dd07-4512-ac24-c7d789287708"
)
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


@dataclass(frozen=True)
class PendingRegistrationFinalization:
    """One serialized ledger outcome and this invocation's provider effect."""

    registration: StudentRegistration
    newly_delivered: bool


@dataclass(frozen=True)
class NeutralizedRegistrationReplay:
    """Typed winner for an anti-enumerating registration reservation.

    The marker deliberately carries no registration or delivery handle.  A
    caller can only reconstruct the already-bound deterministic browser flow;
    it cannot accidentally enqueue provider work for a neutralized request.
    """

    pass


RegistrationReplayResolution = (
    RegistrationResult | NeutralizedRegistrationReplay
)


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


def _signup_flow_token_hash(key: str) -> str:
    raw_token = keyed_hash(f"nyayone:otp-flow-bearer:v1:{key}")
    return keyed_hash(f"nyayone:otp-flow-storage:v1:{raw_token}")


def _locked_signup_flow(
    session: Session, key: str
) -> tuple[OtpPurposeAuthority, OtpFlow] | None:
    token_hash = _signup_flow_token_hash(key)
    authority_id = session.scalar(
        select(OtpFlow.authority_id).where(OtpFlow.token_hash == token_hash)
    )
    if authority_id is None:
        return None
    authority = session.scalar(
        select(OtpPurposeAuthority)
        .where(OtpPurposeAuthority.id == authority_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    flow = session.scalar(
        select(OtpFlow)
        .where(OtpFlow.token_hash == token_hash)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        authority is None
        or flow is None
        or flow.authority_id != authority.id
        or flow.subject_hash != authority.subject_hash
        or flow.purpose != "signup"
        or authority.purpose != "signup"
    ):
        raise RuntimeError("registration OTP flow graph is invalid")
    return authority, flow


def _flow_is_live(flow: OtpFlow, now: datetime) -> bool:
    expires = flow.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    else:
        expires = expires.astimezone(timezone.utc)
    return flow.state in {"pending", "code_sent", "locked"} and expires > now


def _locked_migrated_signup_authority(
    session: Session,
    registration: StudentRegistration,
) -> OtpPurposeAuthority | None:
    """Recognize only the deterministic authority IDs minted by 0019 backfill.

    Runtime authorities derive their UUID from subject_hash+purpose.  Revision
    0019 deliberately used registration_id+purpose for pre-existing challenges,
    giving us a non-secret, collision-resistant compatibility marker without
    mutating historical metadata or minting a bearer during migration.
    """

    authority_ids = {
        uuid.uuid5(
            _OTP_AUTHORITY_ID_NAMESPACE,
            f"{registration.id}:signup",
        ),
        # SQLite's 0018 UUID text projection is the canonical 32-hex form;
        # PostgreSQL returns the hyphenated UUID. Revision 0019 intentionally
        # preserves both dialects' existing row bytes, so recognize either
        # deterministic backfill ID at runtime.
        uuid.uuid5(
            _OTP_AUTHORITY_ID_NAMESPACE,
            f"{registration.id.hex}:signup",
        ),
    }
    authority = session.scalar(
        select(OtpPurposeAuthority)
        .where(
            OtpPurposeAuthority.id.in_(authority_ids),
            OtpPurposeAuthority.registration_id == registration.id,
            OtpPurposeAuthority.purpose == "signup",
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if authority is None:
        return None
    challenge = session.scalar(
        select(OtpChallenge.id)
        .where(
            OtpChallenge.authority_id == authority.id,
            OtpChallenge.registration_id == registration.id,
            OtpChallenge.purpose == "signup",
        )
        .limit(1)
    )
    return authority if challenge is not None else None


def _expire_flow(flow: OtpFlow, now: datetime) -> None:
    flow.state = "expired"
    flow.consumed_at = now
    flow.destination_masked_ct = None
    flow.key_version = None


def close_expired_signup_delivery(
    session: Session,
    record: RegistrationIdempotencyRecord | None,
    flow_graph: tuple[OtpPurposeAuthority, OtpFlow] | None,
    *,
    now: datetime,
) -> None:
    """Fence every relayable child before retiring an unusable bootstrap."""

    sentinel = uuid.UUID(int=0)
    outbox_id = record.outbox_id if record is not None else None
    challenge_id = (
        session.scalar(
            select(OtpOutbox.challenge_id).where(
                OtpOutbox.id == (outbox_id or sentinel)
            )
        )
        if outbox_id is not None
        else (flow_graph[1].challenge_id if flow_graph is not None else None)
    )
    if outbox_id is None and challenge_id is not None:
        discovered_outboxes = list(
            session.scalars(
                select(OtpOutbox.id)
                .where(OtpOutbox.challenge_id == challenge_id)
                .order_by(OtpOutbox.id)
                .limit(2)
            )
        )
        if len(discovered_outboxes) > 1:
            raise RuntimeError("expired registration outbox is ambiguous")
        outbox_id = discovered_outboxes[0] if discovered_outboxes else None
    authority_id = (
        session.scalar(
            select(OtpChallenge.authority_id).where(
                OtpChallenge.id == (challenge_id or sentinel)
            )
        )
        if challenge_id is not None
        else (flow_graph[0].id if flow_graph is not None else None)
    )
    authority = flow_graph[0] if flow_graph is not None else None
    if authority is None and authority_id is not None:
        authority = session.scalar(
            select(OtpPurposeAuthority)
            .where(OtpPurposeAuthority.id == authority_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    challenge = session.scalar(
        select(OtpChallenge)
        .where(OtpChallenge.id == (challenge_id or sentinel))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    outbox = session.scalar(
        select(OtpOutbox)
        .where(OtpOutbox.id == (outbox_id or sentinel))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if outbox_id is not None and (
        authority is None
        or challenge is None
        or outbox is None
        or challenge.authority_id != authority.id
        or outbox.challenge_id != challenge.id
        or challenge.purpose != "signup"
        or outbox.purpose != "signup"
    ):
        raise RuntimeError("expired registration delivery graph is invalid")
    if outbox is not None and outbox.status in {"pending", "claimed", "failed"}:
        outbox.status = "void"
        outbox.code_ct = None
        outbox.destination_ct = None
        outbox.legacy_destination_retained = False
        outbox.claim_token_hash = None
        outbox.claimed_at = None
        outbox.lease_expires_at = None
        outbox.next_attempt_at = None
        outbox.last_error = "registration_flow_expired"
        outbox.delivered_at = None
    if challenge is not None and challenge.delivery_state in {
        "pending_delivery",
        "active",
    }:
        was_active = challenge.delivery_state == "active"
        challenge.delivery_state = "void"
        challenge.consumed_at = challenge.consumed_at or now
        if was_active and authority is not None:
            authority.active_expires_at = None
    if flow_graph is not None:
        _expire_flow(flow_graph[1], now)


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
    *,
    now: datetime | None = None,
) -> RegistrationReplayResolution | None:
    """Return an exact-content replay or fail closed on key reuse.

    A pre-0018 row can carry an idempotency key without a verifiable request
    fingerprint. Treating it as a replay would recreate NYAY-17, so it is a
    typed conflict instead of an unsafe best-effort comparison.
    """

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)
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
            # any real or neutral HMAC authority while this request waits on
            # the registration lock. Re-read and dispatch the locked winner
            # through the exact same lifecycle/fingerprint authority used by
            # the initial lookup.
            record = _ledger_by_key_hash(session, key_hash, for_update=True)
            if record is None:
                return None
            return _resolve_locked_idempotency_record(
                session, record, key, req, now=now
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

    return _resolve_locked_idempotency_record(
        session, record, key, req, now=now
    )


def _resolve_locked_idempotency_record(
    session: Session,
    record: RegistrationIdempotencyRecord,
    key: str,
    req: StudentRegisterRequest,
    *,
    now: datetime,
) -> RegistrationReplayResolution:
    """Dispatch one locked real, neutral, or terminal key authority."""

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

    if record.state == "neutralized":
        _validate_locked_neutralized_replay(
            session, record, key, req, now=now
        )
        return NeutralizedRegistrationReplay()

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
    flow_graph = _locked_signup_flow(session, key)
    if flow_graph is None:
        migrated_authority = _locked_migrated_signup_authority(
            session, existing
        )
        if migrated_authority is not None:
            expected = registration_request_fingerprint(req)
            stored = record.request_fingerprint or ""
            if (
                record.request_fingerprint_version
                != REGISTRATION_REQUEST_FINGERPRINT_VERSION
                or len(stored) != 64
                or not hmac.compare_digest(stored, expected)
            ):
                raise RegistrationError(
                    409, "idempotency_conflict", "Idempotency-Key"
                )
            # Migration never mints a raw flow bearer. An exact-key replay is
            # the only party able to reconstruct the deterministic HttpOnly
            # token. Recreate only that browser capability; identifier-free
            # resend then stages one fresh provider delivery under the existing
            # stable authority.
            from app.core.crypto import decrypt
            from app.services import otp_flow_service

            challenge = session.scalar(
                select(OtpChallenge)
                .where(
                    OtpChallenge.authority_id == migrated_authority.id,
                    OtpChallenge.delivery_state == "active",
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            raw_token = otp_flow_service.deterministic_signup_token(key)
            otp_flow_service.create_flow(
                session,
                migrated_authority,
                now=now,
                destination=decrypt(existing.mobile_ct),
                challenge=challenge,
                registration_id=existing.id,
                registration_idempotency_record_id=record.id,
                raw_token=raw_token,
            )
            session.flush()
            return RegistrationResult(
                registration=existing,
                delivery=None,
                idempotency_record=record,
                replayed=True,
            )
    if flow_graph is None or not _flow_is_live(flow_graph[1], now):
        close_expired_signup_delivery(
            session, record, flow_graph, now=now
        )
        # Match neutralized expiry with the same bounded ledger+flow update on
        # the response path. Divergent graph teardown is left to scheduled
        # retention, avoiding an account-existence timing oracle.
        record.state = "retired"
        record.request_fingerprint = None
        record.request_fingerprint_version = None
        record.outcome_code = "registration_replay_expired"
        record.registration_id = None
        record.outbox_id = None
        record.updated_at = now
        session.commit()
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


def _validate_locked_neutralized_replay(
    session: Session,
    record: RegistrationIdempotencyRecord,
    key: str,
    req: StudentRegisterRequest,
    *,
    now: datetime,
) -> None:
    """Validate one already-locked neutralized winner.

    Lifecycle always precedes fingerprint comparison so expired or removed
    browser capabilities cannot become an exact-vs-mismatch oracle.
    """

    if record.state != "neutralized":
        raise RuntimeError("neutralized registration state changed under lock")
    flow_graph = _locked_signup_flow(session, key)
    if flow_graph is None or not _flow_is_live(flow_graph[1], now):
        close_expired_signup_delivery(session, record, flow_graph, now=now)
        record.state = "retired"
        record.request_fingerprint = None
        record.request_fingerprint_version = None
        record.outcome_code = "registration_replay_expired"
        record.updated_at = now
        session.commit()
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
    if (
        record.registration_id is not None
        or record.outbox_id is not None
        or record.outcome_code != "registration_neutralized"
    ):
        raise RuntimeError("neutralized registration reservation is invalid")


def reserve_neutralized_registration(
    session: Session,
    key: str,
    req: StudentRegisterRequest,
    *,
    now: datetime,
) -> RegistrationIdempotencyRecord | RegistrationReplayResolution:
    """Durably reserve one anti-enumerating duplicate signup key."""

    existing = resolve_idempotent_replay(session, key, req, now=now)
    if existing is not None:
        return existing
    record = RegistrationIdempotencyRecord(
        idempotency_key_hash=registration_idempotency_key_hash(key),
        request_fingerprint=registration_request_fingerprint(req),
        request_fingerprint_version=REGISTRATION_REQUEST_FINGERPRINT_VERSION,
        state="neutralized",
        outcome_code="registration_neutralized",
        registration_id=None,
        outbox_id=None,
        created_at=now,
        updated_at=now,
    )
    session.add(record)
    session.flush()
    return record


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
        OtpFlow as _F,
        OtpOutbox as _O,
        OtpPurposeAuthority as _A,
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
    for flow in session.scalars(
        select(_F).where(_F.registration_id == registration_id)
    ):
        session.delete(flow)
    if ch_ids:
        for o in session.scalars(select(_O).where(_O.challenge_id.in_(ch_ids))):
            session.delete(o)
    for model in (_Ch, _C, _P, _V, _G):
        for row in session.scalars(select(model).where(model.registration_id == registration_id)):
            session.delete(row)
    for authority in session.scalars(
        select(_A).where(_A.registration_id == registration_id)
    ):
        session.delete(authority)
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


def _locked_registration_delivery_graph(
    session: Session,
    registration: StudentRegistration,
    outbox_id: uuid.UUID,
) -> otp_outbox._LockedDeliveryGraph | None:
    """Lock a registration delivery in the canonical domain order.

    The caller already owns ledger -> registration. The common relay seam then
    acquires authority -> flow -> challenge -> outbox and revalidates all
    immutable links, preventing either finalizer from bypassing flow liveness.
    """

    graph = otp_outbox._locked_graph(session, outbox_id)
    if graph is None:
        return None
    authority, challenge, outbox = (
        graph.authority,
        graph.challenge,
        graph.row,
    )
    if (
        authority.registration_id != registration.id
        or challenge.authority_id != authority.id
        or challenge.registration_id != registration.id
        or outbox.challenge_id != challenge.id
        or challenge.purpose != authority.purpose
        or outbox.purpose != authority.purpose
    ):
        return None
    return graph


def _retire_pending_delivery_record(
    record: RegistrationIdempotencyRecord,
    *,
    now: datetime,
) -> None:
    record.state = "retired"
    record.request_fingerprint = None
    record.request_fingerprint_version = None
    record.outcome_code = "registration_replay_expired"
    record.registration_id = None
    record.outbox_id = None
    record.updated_at = now


def _reconcile_unavailable_pending_delivery(
    session: Session,
    key_hash: str,
    outbox_id: uuid.UUID,
    *,
    reason: str,
    now: datetime | None,
) -> StudentRegistration:
    """Retire one provider-fenced signup flow or return a committed winner."""

    record = _ledger_by_key_hash(session, key_hash, for_update=True)
    if record is None:
        raise RuntimeError("registration idempotency ledger row disappeared")
    if record.state in {"retired", "erased"}:
        session.commit()
        raise RegistrationError(
            409, "registration_replay_expired", "Idempotency-Key"
        )
    registration = session.scalar(
        select(StudentRegistration)
        .where(StudentRegistration.id == record.registration_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if record.state == "succeeded" and registration is not None:
        session.commit()
        return registration
    if (
        record.state != "pending"
        or record.outbox_id != outbox_id
        or registration is None
        or record.registration_id != registration.id
    ):
        raise RuntimeError("registration idempotency finalization is ambiguous")
    graph = _locked_registration_delivery_graph(
        session,
        registration,
        outbox_id,
    )
    if graph is None:
        raise RuntimeError("registration idempotency delivery graph disappeared")
    operation_now = now or datetime.now(timezone.utc)
    current_reason = otp_outbox._flow_unavailability_reason(
        graph,
        now=operation_now,
    )
    if current_reason is None:
        raise RuntimeError("registration OTP flow boundary changed under lock")
    otp_outbox._fence_unavailable_delivery(
        session,
        graph,
        now=operation_now,
        reason=reason or current_reason,
    )
    _retire_pending_delivery_record(record, now=operation_now)
    session.commit()
    raise RegistrationError(
        409, "registration_replay_expired", "Idempotency-Key"
    )


def finalize_pending_registration_with_result(
    session: Session,
    key_hash: str,
    sender: IdempotentOtpSender,
    *,
    now: datetime | None = None,
) -> PendingRegistrationFinalization:
    """Durably claim/send first, then reconcile the NYAY-17 ledger.

    No registration/ledger/challenge lock is held during provider I/O. Provider
    failure leaves the exact pending graph retryable under the same stable
    provider key; it never deletes the only usable registration flow.
    ``newly_delivered`` comes directly from the fenced outbox operation; it is
    never inferred from unlocked before/after snapshots of terminal state.
    ``now`` is a deterministic operation-clock override for tests and certified
    probes; production background callers intentionally use fresh wall time.
    """

    if now is not None:
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        else:
            now = now.astimezone(timezone.utc)

    record = _ledger_by_key_hash(session, key_hash, for_update=True)
    if record is None:
        raise RuntimeError("registration idempotency ledger row disappeared")
    if record.state == "failed":
        raise RegistrationError(503, "otp_delivery_retryable")
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
        session.commit()
        return PendingRegistrationFinalization(registration, False)
    if record.state != "pending" or record.outbox_id is None:
        raise RuntimeError("registration idempotency pending state is invalid")

    outbox_id = record.outbox_id
    graph = _locked_registration_delivery_graph(
        session, registration, outbox_id
    )
    challenge = graph.challenge if graph is not None else None
    outbox_snapshot = graph.row if graph is not None else None
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
    operation_now = now or datetime.now(timezone.utc)
    unavailable_reason = otp_outbox._flow_unavailability_reason(
        graph,
        now=operation_now,
    )
    if unavailable_reason is not None:
        otp_outbox._fence_unavailable_delivery(
            session,
            graph,
            now=operation_now,
            reason=unavailable_reason,
        )
        _retire_pending_delivery_record(record, now=operation_now)
        session.commit()
        raise RegistrationError(
            409, "registration_replay_expired", "Idempotency-Key"
        )
    # Release every graph lock before the outbox creates and commits its own
    # hashed fencing lease. The provider call occurs only after this commit.
    session.commit()
    try:
        newly_delivered = otp_outbox.run_delivery(
            session,
            otp_outbox.DeliveryIntent(outbox_id=outbox_id),
            sender,
            raise_on_failure=True,
            now=now,
        )
    except otp_outbox.OtpFlowUnavailable as exc:
        return PendingRegistrationFinalization(
            _reconcile_unavailable_pending_delivery(
                session,
                key_hash,
                outbox_id,
                reason=exc.reason,
                now=now,
            ),
            False,
        )
    except OtpSendError as exc:
        winner = _ledger_by_key_hash(session, key_hash, for_update=True)
        if winner is not None and winner.state in {"retired", "erased"}:
            session.commit()
            raise RegistrationError(
                409, "registration_replay_expired", "Idempotency-Key"
            ) from exc
        session.rollback()
        raise RegistrationError(503, "otp_delivery_retryable") from exc

    record = _ledger_by_key_hash(session, key_hash, for_update=True)
    if record is None:
        raise RuntimeError("registration idempotency ledger row disappeared")
    if record.state in {"retired", "erased"}:
        session.commit()
        raise RegistrationError(
            409, "registration_replay_expired", "Idempotency-Key"
        )
    registration = session.scalar(
        select(StudentRegistration)
        .where(StudentRegistration.id == record.registration_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if registration is None:
        raise RuntimeError("registration idempotency registration disappeared")
    if record.state == "succeeded":
        session.commit()
        return PendingRegistrationFinalization(
            registration,
            newly_delivered,
        )
    if (
        record.state != "pending"
        or record.outbox_id != outbox_id
        or record.registration_id != registration.id
    ):
        raise RuntimeError("registration idempotency finalization is ambiguous")
    graph = _locked_registration_delivery_graph(
        session, registration, outbox_id
    )
    challenge = graph.challenge if graph is not None else None
    outbox_snapshot = graph.row if graph is not None else None
    operation_now = now or datetime.now(timezone.utc)
    unavailable_reason = (
        otp_outbox._flow_unavailability_reason(graph, now=operation_now)
        if graph is not None
        else None
    )
    if graph is not None and unavailable_reason is not None:
        otp_outbox._fence_unavailable_delivery(
            session,
            graph,
            now=operation_now,
            reason=unavailable_reason,
        )
        _retire_pending_delivery_record(record, now=operation_now)
        session.commit()
        raise RegistrationError(
            409, "registration_replay_expired", "Idempotency-Key"
        )
    if (
        outbox_snapshot is None
        or outbox_snapshot.status != "sent"
        or challenge is None
        or challenge.delivery_state != "active"
        or challenge.registration_id != registration.id
        or challenge.purpose != "signup"
    ):
        raise RegistrationError(503, "otp_delivery_retryable")
    record.state = "succeeded"
    record.outcome_code = None
    record.outbox_id = None
    record.updated_at = operation_now
    session.commit()
    return PendingRegistrationFinalization(registration, newly_delivered)


def finalize_pending_registration(
    session: Session,
    key_hash: str,
    sender: IdempotentOtpSender,
    *,
    now: datetime | None = None,
) -> StudentRegistration:
    """Finalize one pending registration, preserving the original API."""

    return finalize_pending_registration_with_result(
        session,
        key_hash,
        sender,
        now=now,
    ).registration


def finalize_pending_resend_if_claimed(
    session: Session,
    registration_id: uuid.UUID,
    intent: otp_outbox.DeliveryIntent,
    sender: IdempotentOtpSender,
    *,
    now: datetime | None = None,
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
    finalize_pending_registration(session, key_hash, sender, now=now)
    return True


def register_student(
    session: Session,
    req: StudentRegisterRequest,
    idempotency_key: str | None = None,
    now: datetime | None = None,
) -> RegistrationReplayResolution:
    now = now or datetime.now(timezone.utc)
    idempotency_key = validate_idempotency_key(idempotency_key)

    # Resolve a replay before any validation-dependent write. A valid key is
    # bound to the entire original accepted request, so changing even consent
    # under that key is an idempotency conflict rather than a new operation.
    if idempotency_key:
        existing = resolve_idempotent_replay(
            session, idempotency_key, req, now=now
        )
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
