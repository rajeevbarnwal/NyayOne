"""NYAY-12 owner-scoped verified-email identity lifecycle.

Every mutation is authenticated against the exact presented session, actor
scoped, idempotent (sealed outcome per actor/operation/key), rate limited and
committed by this module. Delivery follows the NYAY-11 proof pattern: the
pending challenge is committed *before* the provider call, the row is re-locked
afterwards and activated only with a provider receipt; a failed delivery leaves
a resendable, non-reserving pending claim. Uniqueness of a verified address is
enforced by the database partial unique index and surfaced as an auditable
reconciliation row, never as a silent transfer.
"""
from __future__ import annotations

import hmac
import json
import math
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import active_key_version, decrypt, encrypt, keyed_hash
from app.core.email_identity import (
    EMAIL_IDENTITY_POLICY_VERSION,
    email_identity_hash,
    mask_login_email,
    normalize_login_email,
)
from app.models.email_identity import (
    EmailIdentityMutation,
    EmailIdentityReconciliation,
    UserEmailIdentity,
)
from app.models.registration import User
from app.services import login_service, otp_authority, profile_service
from app.services.otp_sender import IdempotentOtpSender, OtpSendError

IDEMPOTENCY_KEY_PATTERN = r"[A-Za-z0-9._~-]{16,200}"
STUDENT_ROLES = frozenset({"student"})
_CODE_PATTERN = r"[0-9]{6}"


class EmailIdentityError(Exception):
    def __init__(
        self,
        code: str,
        status_code: int,
        *,
        retry_after_seconds: int | None = None,
        field: str | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds
        self.field = field


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _seconds_until(value: datetime | None, now: datetime) -> int | None:
    if value is None:
        return None
    return max(0, math.ceil((_utc(value) - _utc(now)).total_seconds()))


def _rate_subject(user_id: uuid.UUID, scope: str) -> str:
    return otp_authority.authority_subject_from_mobile_hash(
        keyed_hash(f"nyay12:email-identity-rate:v1:{scope}:{user_id}")
    )


def consume_budget(session: Session, user_id: uuid.UUID, *, action: str, client_ip: str | None, now: datetime) -> None:
    try:
        otp_authority.consume_rate_budgets(
            session,
            subject_hash=_rate_subject(user_id, action),
            client_ip=client_ip,
            action=action,
            purpose="login",
            now=now,
            commit=True,
        )
    except otp_authority.RateLimitExceeded as exc:
        raise EmailIdentityError(
            "email_identity_rate_limited", 429, retry_after_seconds=exc.retry_after_seconds
        ) from exc


# --------------------------------------------------------------------------- #
# Projection                                                                  #
# --------------------------------------------------------------------------- #
def project_identity(row: UserEmailIdentity, *, now: datetime) -> dict[str, Any]:
    status = row.verification_state
    expires = None
    resend = None
    attempts_left = None
    if row.state == "pending" and status != "none":
        expires = _seconds_until(row.challenge_expires_at, now)
        if status == "active" and expires == 0:
            status = "expired"
        cooldown_until = (
            _utc(row.challenge_issued_at) + timedelta(seconds=settings.otp_resend_cooldown_seconds)
            if row.challenge_issued_at is not None
            else None
        )
        resend = _seconds_until(cooldown_until, now)
        attempts_left = max(0, settings.otp_max_attempts - row.attempts)
    elif row.state != "pending":
        status = "none"
    return {
        "id": str(row.id),
        "email_masked": mask_login_email(decrypt(row.email_ct)),
        "state": row.state,
        "is_primary": bool(row.is_primary),
        "verification": {
            "status": status,
            "expires_in_seconds": expires,
            "resend_in_seconds": resend,
            "attempts_left": attempts_left,
        },
    }


def list_identities(session: Session, actor_user_id: uuid.UUID, *, now: datetime) -> dict[str, Any]:
    rows = session.scalars(
        select(UserEmailIdentity)
        .where(UserEmailIdentity.user_id == actor_user_id, UserEmailIdentity.state != "removed")
        .order_by(UserEmailIdentity.created_at, UserEmailIdentity.id)
    ).all()
    return {
        "login_channel_enabled": bool(settings.email_login_enabled),
        "max_identities": int(settings.email_identity_max_per_user),
        "identities": [project_identity(row, now=now) for row in rows],
    }


# --------------------------------------------------------------------------- #
# Authority, idempotency and locking helpers                                   #
# --------------------------------------------------------------------------- #
def _presented(session: Session, actor_user_id: uuid.UUID | None, raw_token: str | None, now: datetime):
    if actor_user_id is None or not raw_token:
        raise EmailIdentityError("authentication_required", 401)
    proof = login_service.lock_presented_session_for_effect(
        session, raw_token, expected_user_id=actor_user_id, now=now, allowed_roles=STUDENT_ROLES
    )
    if proof is None:
        raise EmailIdentityError("authentication_required", 401)
    return proof


def _require_full_access(session: Session, actor_user_id: uuid.UUID, raw_token: str | None, now: datetime) -> None:
    projection = profile_service.projection_for_actor(
        session, actor_user_id, now=now, raw_session_token=raw_token
    )
    if projection.get("access_mode") != "full":
        raise EmailIdentityError("email_identity_capability_disabled", 403)


def validate_idempotency_key(key: object) -> str:
    import re

    if not isinstance(key, str) or re.fullmatch(IDEMPOTENCY_KEY_PATTERN, key) is None:
        raise EmailIdentityError("invalid_idempotency_key", 422, field="Idempotency-Key")
    return key


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _replay(
    session: Session, actor_user_id: uuid.UUID, operation: str, key: str, payload: dict[str, Any]
) -> tuple[EmailIdentityMutation | None, tuple[int, dict[str, Any]] | None]:
    key_hash = keyed_hash("nyay12:key:v1:" + key)
    fingerprint = keyed_hash("nyay12:payload:v1:" + _canonical({"operation": operation, "payload": payload}))
    record = session.scalar(
        select(EmailIdentityMutation)
        .where(
            EmailIdentityMutation.user_id == actor_user_id,
            EmailIdentityMutation.operation == operation,
            EmailIdentityMutation.key_hash == key_hash,
        )
        .with_for_update()
    )
    if record is not None:
        if not hmac.compare_digest(record.fingerprint, fingerprint):
            raise EmailIdentityError("email_identity_idempotency_conflict", 409)
        return record, (record.status_code, json.loads(decrypt(record.outcome_ct)))
    return (
        EmailIdentityMutation(
            user_id=actor_user_id, operation=operation, key_hash=key_hash, fingerprint=fingerprint,
            status_code=0 or 200, outcome_ct="",
        ),
        None,
    )


def _seal(session: Session, record: EmailIdentityMutation, status_code: int, body: dict[str, Any]) -> None:
    record.status_code = status_code
    record.outcome_ct = encrypt(_canonical(body))
    session.add(record)
    session.flush()


def _owned_identity(
    session: Session, actor_user_id: uuid.UUID, identity_id: object, *, live_only: bool = True
) -> UserEmailIdentity:
    try:
        parsed = uuid.UUID(str(identity_id))
    except (TypeError, ValueError) as exc:
        raise EmailIdentityError("email_identity_not_found", 404) from exc
    row = session.scalar(
        select(UserEmailIdentity)
        .where(UserEmailIdentity.id == parsed, UserEmailIdentity.user_id == actor_user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None or (live_only and row.state == "removed"):
        raise EmailIdentityError("email_identity_not_found", 404)
    return row


def _lock_user(session: Session, actor_user_id: uuid.UUID) -> User:
    user = login_service.lock_user_for_session_rotation(session, actor_user_id)
    if user is None or user.status != "active" or user.role != "student":
        raise EmailIdentityError("authentication_required", 401)
    return user


def _reconcile(
    session: Session, *, email_hash: str, holder_user_id: uuid.UUID | None, claimant_user_id: uuid.UUID | None, now: datetime
) -> None:
    session.add(
        EmailIdentityReconciliation(
            email_hash=email_hash,
            holder_user_id=holder_user_id,
            claimant_user_id=claimant_user_id,
            reason="verified_collision",
            state="open",
            metadata_json={"policy_version": EMAIL_IDENTITY_POLICY_VERSION},
            created_at=now,
            updated_at=now,
        )
    )


# --------------------------------------------------------------------------- #
# Delivery                                                                    #
# --------------------------------------------------------------------------- #
def _stage_challenge(row: UserEmailIdentity, *, now: datetime) -> tuple[str, str]:
    code = f"{secrets.randbelow(1_000_000):06d}"
    code_hash = keyed_hash(f"nyay12:email-code:v1:{row.id}:{code}")
    row.code_hash = code_hash
    row.provider_receipt_hash = None
    row.verification_state = "pending_delivery"
    row.attempts = 0
    row.challenge_issued_at = now
    row.challenge_expires_at = now + timedelta(seconds=settings.otp_challenge_ttl_seconds)
    return code, code_hash


def _deliver(
    session: Session,
    *,
    actor_user_id: uuid.UUID,
    raw_token: str | None,
    identity_id: uuid.UUID,
    code: str,
    code_hash: str,
    sender: IdempotentOtpSender,
    now: datetime,
) -> UserEmailIdentity:
    """Provider call outside every lock; activation only with a receipt."""

    destination = decrypt(session.get(UserEmailIdentity, identity_id).email_ct)  # type: ignore[union-attr]
    session.commit()
    try:
        receipt = sender.send_idempotent(
            destination, code, idempotency_token=keyed_hash(f"nyay12:email-delivery:v1:{identity_id}:{code_hash}")
        )
    except OtpSendError:
        receipt = None
    _presented(session, actor_user_id, raw_token, now)
    row = session.scalar(
        select(UserEmailIdentity)
        .where(UserEmailIdentity.id == identity_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None or row.code_hash != code_hash or row.state != "pending":
        session.commit()
        raise EmailIdentityError("email_identity_state_conflict", 409)
    row.verification_state = "active" if receipt else "failed"
    row.provider_receipt_hash = keyed_hash("nyay12:email-receipt:v1:" + receipt) if receipt else None
    session.flush()
    return row


# --------------------------------------------------------------------------- #
# Mutations                                                                    #
# --------------------------------------------------------------------------- #
def add_identity(
    session: Session,
    actor_user_id: uuid.UUID,
    raw_token: str | None,
    *,
    email: str,
    sender: IdempotentOtpSender | None,
    key: str,
    client_ip: str | None,
    now: datetime,
) -> tuple[int, dict[str, Any], bool]:
    validate_idempotency_key(key)
    try:
        normalized = normalize_login_email(email)
    except ValueError as exc:
        raise EmailIdentityError("validation_error", 422, field="email") from exc
    if sender is None:
        raise EmailIdentityError("email_delivery_unavailable", 503)
    consume_budget(session, actor_user_id, action="issue", client_ip=client_ip, now=now)
    lookup = email_identity_hash(normalized)
    _presented(session, actor_user_id, raw_token, now)
    record, replay = _replay(session, actor_user_id, "add", key, {"email_hash": lookup})
    if replay is not None:
        return replay[0], replay[1], True
    _require_full_access(session, actor_user_id, raw_token, now)
    _lock_user(session, actor_user_id)
    existing = session.scalar(
        select(UserEmailIdentity)
        .where(
            UserEmailIdentity.user_id == actor_user_id,
            UserEmailIdentity.email_hash == lookup,
            UserEmailIdentity.state != "removed",
        )
        .with_for_update()
    )
    if existing is not None:
        body = {"status": "accepted", "identity": project_identity(existing, now=now)}
        _seal(session, record, 202, body)
        session.commit()
        return 202, body, False
    live = session.scalar(
        select(func.count(UserEmailIdentity.id)).where(
            UserEmailIdentity.user_id == actor_user_id, UserEmailIdentity.state != "removed"
        )
    )
    if int(live or 0) >= int(settings.email_identity_max_per_user):
        session.rollback()
        raise EmailIdentityError("email_identity_limit_reached", 409)
    row = UserEmailIdentity(
        id=uuid.uuid4(),  # bind the code hash to the final identity id before flush
        user_id=actor_user_id,
        email_hash=lookup,
        email_ct=encrypt(normalized),
        key_version=active_key_version(),
        state="pending",
        is_primary=False,
        verification_state="none",
        attempts=0,
        created_at=now,
        updated_at=now,
    )
    code, code_hash = _stage_challenge(row, now=now)
    session.add(row)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise EmailIdentityError("email_identity_state_conflict", 409) from exc
    identity_id = row.id
    # The pending claim is durable before delivery (never a phantom "sent").
    session.add(record)
    record.status_code, record.outcome_ct = 202, encrypt(_canonical({"status": "delivery_pending"}))
    row = _deliver(
        session,
        actor_user_id=actor_user_id,
        raw_token=raw_token,
        identity_id=identity_id,
        code=code,
        code_hash=code_hash,
        sender=sender,
        now=now,
    )
    body = {"status": "accepted", "identity": project_identity(row, now=now)}
    if row.verification_state == "failed":
        session.delete(_reload_record(session, record))
        session.commit()
        raise EmailIdentityError("email_delivery_unavailable", 503)
    _seal(session, _reload_record(session, record), 202, body)
    session.commit()
    return 202, body, False


def _reload_record(session: Session, record: EmailIdentityMutation) -> EmailIdentityMutation:
    reloaded = session.get(EmailIdentityMutation, record.id)
    return reloaded if reloaded is not None else record


def resend_identity(
    session: Session,
    actor_user_id: uuid.UUID,
    raw_token: str | None,
    *,
    identity_id: object,
    sender: IdempotentOtpSender | None,
    key: str,
    client_ip: str | None,
    now: datetime,
) -> tuple[int, dict[str, Any], bool]:
    validate_idempotency_key(key)
    if sender is None:
        raise EmailIdentityError("email_delivery_unavailable", 503)
    _presented(session, actor_user_id, raw_token, now)
    row = _owned_identity(session, actor_user_id, identity_id)
    record, replay = _replay(session, actor_user_id, "resend", key, {"identity_id": str(row.id)})
    if replay is not None:
        return replay[0], replay[1], True
    if row.state != "pending":
        session.rollback()
        raise EmailIdentityError("email_identity_state_conflict", 409)
    if row.challenge_issued_at is not None:
        cooldown_until = _utc(row.challenge_issued_at) + timedelta(seconds=settings.otp_resend_cooldown_seconds)
        if cooldown_until > _utc(now):
            session.rollback()
            raise EmailIdentityError(
                "email_identity_rate_limited", 429, retry_after_seconds=_seconds_until(cooldown_until, now)
            )
    session.rollback()
    consume_budget(session, actor_user_id, action="resend", client_ip=client_ip, now=now)
    _presented(session, actor_user_id, raw_token, now)
    row = _owned_identity(session, actor_user_id, identity_id)
    record, replay = _replay(session, actor_user_id, "resend", key, {"identity_id": str(row.id)})
    if replay is not None:
        return replay[0], replay[1], True
    if row.state != "pending":
        session.rollback()
        raise EmailIdentityError("email_identity_state_conflict", 409)
    code, code_hash = _stage_challenge(row, now=now)
    session.add(record)
    record.status_code, record.outcome_ct = 202, encrypt(_canonical({"status": "delivery_pending"}))
    session.flush()
    row = _deliver(
        session,
        actor_user_id=actor_user_id,
        raw_token=raw_token,
        identity_id=row.id,
        code=code,
        code_hash=code_hash,
        sender=sender,
        now=now,
    )
    body = {"status": "accepted", "identity": project_identity(row, now=now)}
    if row.verification_state == "failed":
        session.delete(_reload_record(session, record))
        session.commit()
        raise EmailIdentityError("email_delivery_unavailable", 503)
    _seal(session, _reload_record(session, record), 202, body)
    session.commit()
    return 202, body, False


def verify_identity(
    session: Session,
    actor_user_id: uuid.UUID,
    raw_token: str | None,
    *,
    identity_id: object,
    code: object,
    key: str,
    now: datetime,
) -> tuple[int, dict[str, Any], bool]:
    import re

    validate_idempotency_key(key)
    if not isinstance(code, str) or re.fullmatch(_CODE_PATTERN, code) is None:
        raise EmailIdentityError("validation_error", 422, field="code")
    _presented(session, actor_user_id, raw_token, now)
    row = _owned_identity(session, actor_user_id, identity_id)
    presented_hash = keyed_hash(f"nyay12:email-code:v1:{row.id}:{code}")
    record, replay = _replay(
        session, actor_user_id, "verify", key,
        {"identity_id": str(row.id), "code_hash": keyed_hash("nyay12:verify-fingerprint:v1:" + presented_hash)},
    )
    if replay is not None:
        return replay[0], replay[1], True
    _require_full_access(session, actor_user_id, raw_token, now)
    _lock_user(session, actor_user_id)
    row = _owned_identity(session, actor_user_id, identity_id)
    if (
        row.state != "pending"
        or row.verification_state != "active"
        or row.code_hash is None
        or row.challenge_expires_at is None
        or _utc(row.challenge_expires_at) <= _utc(now)
        or row.attempts >= settings.otp_max_attempts
    ):
        session.rollback()
        raise EmailIdentityError("email_identity_verification_failed", 401)
    row.attempts += 1
    if not hmac.compare_digest(row.code_hash, presented_hash):
        if row.attempts >= settings.otp_max_attempts:
            row.verification_state, row.code_hash = "failed", None
        session.commit()  # failed attempts stay durable
        raise EmailIdentityError("email_identity_verification_failed", 401)
    holder = session.scalar(
        select(UserEmailIdentity).where(
            UserEmailIdentity.email_hash == row.email_hash,
            UserEmailIdentity.state == "verified",
            UserEmailIdentity.id != row.id,
        )
    )
    if holder is not None:
        row.code_hash, row.verification_state = None, "none"
        row.challenge_issued_at = row.challenge_expires_at = None
        _reconcile(session, email_hash=row.email_hash, holder_user_id=holder.user_id, claimant_user_id=actor_user_id, now=now)
        session.commit()
        raise EmailIdentityError("email_identity_conflict", 409)
    has_primary = session.scalar(
        select(UserEmailIdentity.id).where(
            UserEmailIdentity.user_id == actor_user_id, UserEmailIdentity.is_primary.is_(True)
        )
    )
    row.state = "verified"
    row.verified_at = now
    row.code_hash, row.provider_receipt_hash = None, None
    row.verification_state = "none"
    row.challenge_issued_at = row.challenge_expires_at = None
    row.attempts = 0
    row.is_primary = has_primary is None
    try:
        session.flush()
    except IntegrityError:
        # A concurrent owner won the verified index: fail closed, audit, no transfer.
        session.rollback()
        _presented(session, actor_user_id, raw_token, now)
        fresh = _owned_identity(session, actor_user_id, identity_id)
        fresh.code_hash, fresh.verification_state = None, "none"
        fresh.challenge_issued_at = fresh.challenge_expires_at = None
        winner = session.scalar(
            select(UserEmailIdentity).where(
                UserEmailIdentity.email_hash == fresh.email_hash, UserEmailIdentity.state == "verified"
            )
        )
        _reconcile(
            session, email_hash=fresh.email_hash,
            holder_user_id=winner.user_id if winner is not None else None,
            claimant_user_id=actor_user_id, now=now,
        )
        session.commit()
        raise EmailIdentityError("email_identity_conflict", 409)
    body = {"status": "verified", "identity": project_identity(row, now=now)}
    _seal(session, record, 200, body)
    session.commit()
    return 200, body, False


def remove_identity(
    session: Session,
    actor_user_id: uuid.UUID,
    raw_token: str | None,
    *,
    identity_id: object,
    key: str,
    now: datetime,
) -> tuple[int, dict[str, Any], bool]:
    validate_idempotency_key(key)
    _presented(session, actor_user_id, raw_token, now)
    _lock_user(session, actor_user_id)
    row = _owned_identity(session, actor_user_id, identity_id)
    record, replay = _replay(session, actor_user_id, "remove", key, {"identity_id": str(row.id)})
    if replay is not None:
        return replay[0], replay[1], True
    row.state = "removed"
    row.removed_at = now
    row.is_primary = False
    row.code_hash, row.provider_receipt_hash = None, None
    row.verification_state = "none"
    row.challenge_issued_at = row.challenge_expires_at = None
    session.flush()
    body = {"status": "removed", "identity": project_identity(row, now=now)}
    _seal(session, record, 200, body)
    session.commit()
    return 200, body, False


def set_primary(
    session: Session,
    actor_user_id: uuid.UUID,
    raw_token: str | None,
    *,
    identity_id: object,
    key: str,
    now: datetime,
) -> tuple[int, dict[str, Any], bool]:
    validate_idempotency_key(key)
    _presented(session, actor_user_id, raw_token, now)
    _lock_user(session, actor_user_id)
    row = _owned_identity(session, actor_user_id, identity_id)
    record, replay = _replay(session, actor_user_id, "primary", key, {"identity_id": str(row.id)})
    if replay is not None:
        return replay[0], replay[1], True
    if row.state != "verified":
        session.rollback()
        raise EmailIdentityError("email_identity_state_conflict", 409)
    _require_full_access(session, actor_user_id, raw_token, now)
    others = session.scalars(
        select(UserEmailIdentity)
        .where(
            UserEmailIdentity.user_id == actor_user_id,
            UserEmailIdentity.is_primary.is_(True),
            UserEmailIdentity.id != row.id,
        )
        .with_for_update()
    ).all()
    for other in others:
        other.is_primary = False
    session.flush()
    row.is_primary = True
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise EmailIdentityError("email_identity_state_conflict", 409) from exc
    body = {"status": "primary", "identity": project_identity(row, now=now)}
    _seal(session, record, 200, body)
    session.commit()
    return 200, body, False
