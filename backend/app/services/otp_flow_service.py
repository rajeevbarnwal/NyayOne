"""HttpOnly-cookie OTP flow capabilities and safe public state (NYAY-4)."""
from __future__ import annotations

import hmac
import math
import secrets
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from typing_extensions import TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import active_key_version, decrypt, encrypt, keyed_hash
from app.models.registration import (
    OtpChallenge,
    OtpFlow,
    OtpPurposeAuthority,
    RegistrationIdempotencyRecord,
    StudentRegistration,
)
from app.schemas.registration import StudentRegisterRequest
from app.services.otp_authority import as_utc, locked_for_seconds
from app.services import registration_service

_NONTERMINAL = ("pending", "code_sent", "verified", "locked")
_CANCELLABLE_ONBOARDING = frozenset({"pending", "code_sent", "locked"})


class OtpFlowState(TypedDict):
    status: str
    purpose: str | None
    destination_masked: str | None
    attempts_left: int | None
    expires_in_seconds: int | None
    resend_in_seconds: int | None
    locked_for_seconds: int | None
    resend_allowed: bool


@dataclass(frozen=True)
class OnboardingCancellation:
    state: OtpFlowState
    signup_restart_token: str | None
    signup_restart_max_age: int | None


def unavailable_state() -> OtpFlowState:
    return {
        "status": "unavailable",
        "purpose": None,
        "destination_masked": None,
        "attempts_left": None,
        "expires_in_seconds": None,
        "resend_in_seconds": None,
        "locked_for_seconds": None,
        "resend_allowed": False,
    }


def authenticated_state(purpose: str) -> OtpFlowState:
    return {
        "status": "authenticated",
        "purpose": purpose,
        "destination_masked": None,
        "attempts_left": None,
        "expires_in_seconds": None,
        "resend_in_seconds": None,
        "locked_for_seconds": None,
        "resend_allowed": False,
    }


def verified_state() -> OtpFlowState:
    return {
        "status": "verified",
        "purpose": "recovery",
        "destination_masked": None,
        "attempts_left": None,
        "expires_in_seconds": None,
        "resend_in_seconds": None,
        "locked_for_seconds": None,
        "resend_allowed": False,
    }


def flow_token_hash(raw_token: str) -> str:
    return keyed_hash(f"nyayone:otp-flow-storage:v1:{raw_token}")


def deterministic_signup_token(idempotency_key: str) -> str:
    """Recomputable bearer for zero-delta exact registration replay."""

    return keyed_hash(f"nyayone:otp-flow-bearer:v1:{idempotency_key}")


def _terminal_erasure_won(
    *,
    record: Any,
    record_id: Any,
    registration: Any,
    authority: Any,
    flow: Any,
) -> bool:
    """Recognise only a complete retention winner after stale flow discovery.

    Verification discovers capability links before acquiring the canonical
    ledger -> registration -> authority -> flow locks. Retention may atomically
    erase the graph while verification waits. That exact terminal tombstone is
    an unavailable capability, while every partial or malformed graph remains
    an internal integrity failure.
    """

    registration_erased = bool(
        registration is None
        or (
            registration.status == "deleted"
            and registration.deleted_at is not None
            and registration.dob_hash_state == "erased"
        )
    )
    return bool(
        record is not None
        and record.id == record_id
        and record.state in {"retired", "erased"}
        and record.registration_id is None
        and record.outbox_id is None
        and record.request_fingerprint is None
        and record.request_fingerprint_version is None
        and record.outcome_code == "registration_replay_expired"
        and registration_erased
        and authority is None
        and flow is None
    )


def random_flow_token() -> str:
    return secrets.token_urlsafe(32)


def mask_destination(destination: str) -> str:
    if "@" in destination:
        # NYAY-12 email channel: first local character, fixed fill, full domain.
        from app.core.email_identity import mask_login_email

        return mask_login_email(destination)
    digits = "".join(character for character in destination if character.isdigit())
    return f"••••••{digits[-4:]}"


EMAIL_CHANNEL_METADATA_KEY = "channel"


def flow_channel(flow: OtpFlow | None) -> str:
    """Return the server-recorded delivery channel of a flow (mobile default)."""

    metadata = (flow.metadata_json or {}) if flow is not None else {}
    return "email" if metadata.get(EMAIL_CHANNEL_METADATA_KEY) == "email" else "mobile"


def channel_for_token(session: Session, raw_token: str | None) -> str:
    """Read the delivery channel of an opaque flow token without domain locks."""

    if raw_token:
        metadata = session.scalar(
            select(OtpFlow.metadata_json).where(
                OtpFlow.token_hash == flow_token_hash(raw_token)
            )
        )
        if isinstance(metadata, dict) and metadata.get(EMAIL_CHANNEL_METADATA_KEY) == "email":
            return "email"
    return "mobile"


def create_flow(
    session: Session,
    authority: OtpPurposeAuthority,
    *,
    now: datetime,
    destination: str,
    challenge: OtpChallenge | None,
    registration_id: uuid.UUID | None,
    registration_idempotency_record_id: uuid.UUID | None = None,
    raw_token: str | None = None,
) -> tuple[str, OtpFlow]:
    """Replace the browser flow while preserving challenge/provider authority."""

    now = as_utc(now)
    token = raw_token or random_flow_token()
    token_hash = flow_token_hash(token)
    same = session.scalar(
        select(OtpFlow)
        .where(OtpFlow.token_hash == token_hash)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if same is not None:
        if same.authority_id != authority.id:
            raise RuntimeError("OTP flow token authority is ambiguous")
        return token, same
    existing = list(
        session.scalars(
            select(OtpFlow)
            .where(
                OtpFlow.authority_id == authority.id,
                OtpFlow.state.in_(_NONTERMINAL),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    for prior in existing:
        prior.state = "consumed"
        prior.consumed_at = now
        prior.destination_masked_ct = None
        prior.key_version = None
    session.flush()
    row = OtpFlow(
        token_hash=token_hash,
        authority_id=authority.id,
        subject_hash=authority.subject_hash,
        purpose=authority.purpose,
        registration_id=registration_id,
        registration_idempotency_record_id=registration_idempotency_record_id,
        challenge_id=challenge.id if challenge is not None else None,
        destination_masked_ct=encrypt(mask_destination(destination)),
        key_version=active_key_version(),
        state="pending",
        expires_at=now + timedelta(seconds=settings.otp_flow_ttl_seconds),
        consumed_at=None,
    )
    session.add(row)
    session.flush()
    return token, row


def _locked_flow_graph(
    session: Session, raw_token: str | None
) -> tuple[OtpPurposeAuthority, OtpFlow] | None:
    if not raw_token:
        return None
    token_hash = flow_token_hash(raw_token)
    discovery = session.execute(
        select(
            OtpFlow.authority_id,
            OtpFlow.registration_id,
            OtpFlow.registration_idempotency_record_id,
        ).where(OtpFlow.token_hash == token_hash)
    ).one_or_none()
    if discovery is None:
        return None
    authority_id, registration_id, record_id = discovery
    record = None
    if record_id is not None:
        record = session.scalar(
            select(RegistrationIdempotencyRecord)
            .where(RegistrationIdempotencyRecord.id == record_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    registration = None
    if registration_id is not None:
        registration, _ = registration_service.lock_registration_with_idempotency(
            session, registration_id
        )
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
    if _terminal_erasure_won(
        record=record,
        record_id=record_id,
        registration=registration,
        authority=authority,
        flow=flow,
    ):
        return None
    if (
        (record_id is not None and record is None)
        or (registration_id is not None and registration is None)
        or authority is None
        or flow is None
        or flow.authority_id != authority.id
        or flow.subject_hash != authority.subject_hash
        or flow.purpose != authority.purpose
        or (
            flow.registration_id is not None
            and flow.registration_id != authority.registration_id
        )
        or flow.registration_idempotency_record_id != record_id
        or (
            record is not None
            and (
                (
                    flow.registration_id is None
                    and (
                        record.state != "neutralized"
                        or record.registration_id is not None
                    )
                )
                or (
                    flow.registration_id is not None
                    and record.registration_id not in {
                        flow.registration_id,
                        None,
                    }
                    and record.state not in {"retired", "erased"}
                )
            )
        )
    ):
        raise RuntimeError("OTP flow authority graph is invalid")
    if registration is not None and (
        registration.deleted_at is not None
        or registration.status == "deleted"
        or registration.dob_hash_state != "verified"
        or (
            flow.purpose in {"login", "recovery"}
            and registration.status not in {"otp_verified", "active"}
        )
        or (
            flow.purpose == "signup"
            and registration.status != "otp_pending"
        )
    ):
        # A stale capability for an account that is no longer eligible is
        # externally identical to a missing capability.  Do not rebind it to a
        # decoy or expose its persisted counters/status through projection.
        return None
    if flow.challenge_id is not None:
        challenge = session.get(OtpChallenge, flow.challenge_id)
        if (
            challenge is None
            or challenge.authority_id != authority.id
            or challenge.registration_id != authority.registration_id
            or flow.registration_id != challenge.registration_id
            or challenge.purpose != authority.purpose
        ):
            raise RuntimeError("OTP flow challenge graph is invalid")
    return authority, flow


def resolve_flow(
    session: Session,
    raw_token: str | None,
) -> tuple[OtpPurposeAuthority, OtpFlow] | None:
    return _locked_flow_graph(session, raw_token)


def _seconds_until(value: datetime | None, now: datetime) -> int:
    if value is None:
        return 0
    return max(0, math.ceil((as_utc(value) - as_utc(now)).total_seconds()))


def project(
    authority: OtpPurposeAuthority | None,
    flow: OtpFlow | None,
    *,
    now: datetime,
) -> OtpFlowState:
    now = as_utc(now)
    if authority is None or flow is None:
        return unavailable_state()
    if as_utc(flow.expires_at) <= now or flow.state in {
        "expired",
        "consumed",
        "failed",
    }:
        return unavailable_state()
    if flow.state == "verified":
        return verified_state()

    locked_seconds = locked_for_seconds(authority, now)
    # Public expiry is anchored to the serialized issuance authority, never to
    # provider timing or the presence of an older delivered verifier.  A real
    # resend/start may preserve that older verifier until its staged replacement
    # is accepted, while a decoy has no verifier at all.  Exposing
    # ``active_expires_at`` would therefore reveal account existence on a
    # repeated start.  The active expiry remains authoritative internally for
    # verification; the public window is the same pre-provider bound in both
    # worlds and is still capped by the cookie-flow lifetime.
    public_expires = None
    if authority.last_issued_at is not None:
        public_expires = as_utc(authority.last_issued_at) + timedelta(
            seconds=settings.otp_challenge_ttl_seconds
        )
    expires_seconds = min(
        _seconds_until(flow.expires_at, now),
        _seconds_until(public_expires, now),
    )
    resend_seconds = _seconds_until(authority.cooldown_until, now)
    effective_failures = authority.failed_attempts
    if (
        locked_seconds == 0
        and authority.attempt_window_started_at is not None
        and as_utc(authority.attempt_window_started_at)
        + timedelta(seconds=settings.otp_attempt_window_seconds)
        <= now
    ):
        # GET projection is mutation-free, but it must show the same effective
        # budget that the next verify will reset under lock.
        effective_failures = 0
    attempts_left = max(0, authority.max_attempts - effective_failures)
    resend_window_open = True
    if authority.resend_window_started_at is not None:
        window_end = as_utc(authority.resend_window_started_at) + timedelta(
            seconds=settings.otp_resend_window_seconds
        )
        if window_end > now:
            resend_window_open = authority.resend_count < authority.max_resends
    return {
        "status": "pending",
        "purpose": flow.purpose,
        "destination_masked": (
            decrypt(flow.destination_masked_ct)
            if flow.destination_masked_ct is not None
            else None
        ),
        "attempts_left": attempts_left,
        "expires_in_seconds": expires_seconds,
        "resend_in_seconds": resend_seconds,
        "locked_for_seconds": locked_seconds,
        "resend_allowed": bool(
            locked_seconds == 0
            and resend_seconds == 0
            and resend_window_open
            and attempts_left > 0
        ),
    }


def state_for_token(
    session: Session, raw_token: str | None, *, now: datetime
) -> OtpFlowState:
    graph = resolve_flow(session, raw_token)
    if graph is None:
        return unavailable_state()
    return project(*graph, now=now)


def cancel_onboarding_flow(
    session: Session,
    raw_token: str | None,
    *,
    now: datetime,
) -> OnboardingCancellation:
    """Atomically retire one cookie-owned signup/login authority graph.

    Missing, expired, random, and non-onboarding capabilities share the same
    unavailable projection. A live onboarding flow is consumed only after its
    active or pending challenge and every relayable outbox row are locked and
    fenced, so a captured cookie/code pair or stale delivery worker cannot win
    after the cancellation commit.
    """

    graph = resolve_flow(session, raw_token)
    if graph is None:
        return OnboardingCancellation(unavailable_state(), None, None)
    authority, flow = graph
    now = as_utc(now)
    if (
        flow.purpose not in {"signup", "login"}
        or flow.state not in _CANCELLABLE_ONBOARDING
        or flow.consumed_at is not None
        or as_utc(flow.expires_at) <= now
    ):
        return OnboardingCancellation(unavailable_state(), None, None)

    # Local import avoids a module cycle: otp_outbox imports the OtpFlow model
    # and coordinates the same authority-first locking discipline.
    from app.services import otp_outbox

    otp_outbox.fence_expired_flow_deliveries(
        session,
        authority,
        now=now,
        reason="otp_flow_cancelled",
    )
    signup_restart_token = None
    signup_restart_max_age = None
    if (
        flow.purpose == "signup"
        and raw_token is not None
        and flow.registration_id is not None
        and flow.registration_idempotency_record_id is not None
    ):
        record = session.get(
            RegistrationIdempotencyRecord,
            flow.registration_idempotency_record_id,
        )
        if (
            record is None
            or record.registration_id != flow.registration_id
            or record.state not in {"pending", "succeeded"}
            or record.request_fingerprint is None
            or record.request_fingerprint_version
            not in registration_service.REGISTRATION_REQUEST_FINGERPRINT_VERSIONS
        ):
            raise RuntimeError("signup cancellation authority is invalid")
        # Preserve only the keyed, versioned request fingerprint on the
        # consumed capability. This permits one exact restart without retaining
        # the browser's old idempotency authority or exposing any PII.
        flow.metadata_json = {
            "terminal_reason": "user_cancelled",
            "request_fingerprint": record.request_fingerprint,
            "request_fingerprint_version": record.request_fingerprint_version,
        }
        registration = session.get(StudentRegistration, flow.registration_id)
        if (
            registration is None
            or registration.status != "otp_pending"
            or registration.deleted_at is not None
        ):
            raise RuntimeError("signup cancellation registration is invalid")
        registration_service.terminalize_registration_idempotency(
            session,
            registration,
            state="retired",
            locked_record=record,
        )
        signup_restart_token = raw_token
        signup_restart_max_age = _seconds_until(flow.expires_at, now)
    flow.state = "consumed"
    flow.consumed_at = now
    flow.destination_masked_ct = None
    flow.key_version = None
    session.flush()
    return OnboardingCancellation(
        unavailable_state(),
        signup_restart_token,
        signup_restart_max_age,
    )


def restart_cancelled_signup(
    session: Session,
    raw_token: str | None,
    request: StudentRegisterRequest,
    idempotency_key: str | None,
    *,
    now: datetime,
) -> registration_service.RegistrationResult | None:
    """Restart one exact canceled signup through its path-scoped capability.

    The old ledger is already a terminal tombstone. The consumed flow carries
    only a keyed request fingerprint, so a different payload or replayed
    capability receives no authority and falls through to the neutral duplicate
    path. A successful restart consumes this marker before staging a new
    challenge and binds a fresh idempotency ledger.
    """

    if not raw_token or idempotency_key is None:
        return None
    candidate = session.execute(
        select(
            OtpFlow.purpose,
            OtpFlow.state,
            OtpFlow.registration_id,
            OtpFlow.registration_idempotency_record_id,
            OtpFlow.expires_at,
            OtpFlow.metadata_json,
        ).where(OtpFlow.token_hash == flow_token_hash(raw_token))
    ).one_or_none()
    if candidate is None:
        return None
    (
        purpose,
        state,
        registration_id,
        record_id,
        candidate_expires_at,
        candidate_metadata,
    ) = candidate
    candidate_metadata = candidate_metadata or {}
    if not isinstance(candidate_metadata, Mapping):
        return None
    candidate_version = candidate_metadata.get("request_fingerprint_version")
    candidate_fingerprint = candidate_metadata.get("request_fingerprint")
    if (
        purpose != "signup"
        or state != "consumed"
        or registration_id is None
        or record_id is None
        or as_utc(candidate_expires_at) <= as_utc(now)
        or candidate_metadata.get("terminal_reason") != "user_cancelled"
        or candidate_version
        not in registration_service.REGISTRATION_REQUEST_FINGERPRINT_VERSIONS
        or not isinstance(candidate_fingerprint, str)
        or len(candidate_fingerprint) != 64
    ):
        # The OTP cookie name is intentionally shared across purposes and its
        # Path attribute is not visible to the server. Broad legacy, active,
        # neutralized, and retention-tombstoned cookies are therefore ordinary
        # registration context—not restart capabilities. Only the exact marker
        # shape proceeds into the strict, canonically locked graph resolver.
        return None
    graph = resolve_flow(session, raw_token)
    if graph is None:
        return None
    authority, flow = graph
    metadata = flow.metadata_json or {}
    version = metadata.get("request_fingerprint_version")
    stored_fingerprint = metadata.get("request_fingerprint")
    if (
        flow.purpose != "signup"
        or flow.state != "consumed"
        or flow.registration_id is None
        or flow.registration_idempotency_record_id is None
        or as_utc(flow.expires_at) <= as_utc(now)
        or metadata.get("terminal_reason") != "user_cancelled"
        or version
        not in registration_service.REGISTRATION_REQUEST_FINGERPRINT_VERSIONS
        or not isinstance(stored_fingerprint, str)
        or len(stored_fingerprint) != 64
    ):
        return None
    try:
        expected_fingerprint = registration_service.registration_request_fingerprint(
            request,
            version=version,
        )
    except ValueError:
        return None
    if not hmac.compare_digest(stored_fingerprint, expected_fingerprint):
        return None

    from app.services import otp_service

    registration = session.get(StudentRegistration, flow.registration_id)
    record = session.get(
        RegistrationIdempotencyRecord,
        flow.registration_idempotency_record_id,
    )
    if (
        registration is None
        or registration.status != "otp_pending"
        or registration.deleted_at is not None
        or record is None
        or record.state != "retired"
        or record.registration_id is not None
        or record.outbox_id is not None
    ):
        raise RuntimeError("signup restart authority is invalid")

    if (
        authority.cooldown_until is not None
        and as_utc(authority.cooldown_until) > as_utc(now)
    ):
        retry_after = max(
            1,
            math.ceil(
                (
                    as_utc(authority.cooldown_until) - as_utc(now)
                ).total_seconds()
            ),
        )
        raise otp_service.OtpError(
            429,
            "resend_cooldown",
            retry_after_seconds=retry_after,
        )
    otp_service.consume_resend_window(authority, now)
    session.flush()

    # Consume the one-use restart marker before creating successor authority.
    flow.metadata_json = {"terminal_reason": "signup_restart_consumed"}
    _, intent = otp_service.issue_challenge(
        session,
        registration.id,
        now,
        purpose="signup",
        destination=request.mobile,
    )
    fingerprint_version = registration_service.registration_request_fingerprint_version(
        request
    )
    replacement_record = RegistrationIdempotencyRecord(
        idempotency_key_hash=registration_service.registration_idempotency_key_hash(
            idempotency_key
        ),
        request_fingerprint=registration_service.registration_request_fingerprint(
            request,
            version=fingerprint_version,
        ),
        request_fingerprint_version=fingerprint_version,
        state="pending",
        outcome_code=None,
        registration_id=registration.id,
        outbox_id=intent.outbox_id,
    )
    session.add(replacement_record)
    session.flush()
    return registration_service.RegistrationResult(
        registration=registration,
        delivery=intent,
        idempotency_record=replacement_record,
        replayed=False,
    )


def subject_for_token(session: Session, raw_token: str | None) -> str:
    """Return an opaque rate-limit subject without taking domain row locks.

    Unknown capabilities are deliberately placed in a stable keyed bucket for
    the supplied opaque token. The raw cookie value is never persisted.
    """

    if raw_token:
        stored = flow_token_hash(raw_token)
        subject = session.scalar(
            select(OtpFlow.subject_hash).where(OtpFlow.token_hash == stored)
        )
        if subject is not None:
            return subject
    unknown_hash = keyed_hash(
        f"nyayone:otp-flow-unknown-subject:v1:{raw_token or 'missing'}"
    )
    from app.services.otp_authority import authority_subject_from_mobile_hash

    return authority_subject_from_mobile_hash(unknown_hash)


def purpose_for_token(session: Session, raw_token: str | None) -> str:
    """Return the non-sensitive rate-budget domain for an opaque flow token."""

    if raw_token:
        purpose = session.scalar(
            select(OtpFlow.purpose).where(
                OtpFlow.token_hash == flow_token_hash(raw_token)
            )
        )
        if purpose in {"signup", "login", "recovery"}:
            return purpose
    # Missing/random capabilities still consume common IP/global and one fixed
    # identity domain without disclosing whether a stored flow exists.
    return "signup"


def mark_authenticated(
    flow: OtpFlow, *, now: datetime
) -> OtpFlowState:
    purpose = flow.purpose
    flow.state = "consumed"
    flow.consumed_at = as_utc(now)
    flow.destination_masked_ct = None
    flow.key_version = None
    return authenticated_state(purpose)


def mark_recovery_verified(flow: OtpFlow, *, now: datetime) -> OtpFlowState:
    flow.state = "verified"
    flow.destination_masked_ct = None
    flow.key_version = None
    flow.expires_at = as_utc(now) + timedelta(
        seconds=settings.otp_recovery_proof_ttl_seconds
    )
    return verified_state()


def consume_recovery_proof(
    session: Session,
    raw_token: str | None,
    *,
    registration_id: uuid.UUID,
    now: datetime,
) -> OtpFlow:
    graph = resolve_flow(session, raw_token)
    if graph is None:
        raise ValueError("recovery proof unavailable")
    authority, flow = graph
    now = as_utc(now)
    if (
        flow.state != "verified"
        or flow.purpose != "recovery"
        or flow.registration_id != registration_id
        or authority.registration_id != registration_id
        or as_utc(flow.expires_at) <= now
    ):
        raise ValueError("recovery proof unavailable")
    flow.state = "consumed"
    flow.consumed_at = now
    flow.destination_masked_ct = None
    flow.key_version = None
    session.flush()
    return flow
