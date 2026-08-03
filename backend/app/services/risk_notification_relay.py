"""Privacy-safe relay for organisation-response invitations (SAATHI-279).

The database stores only an encrypted, transient delivery envelope.  A relay
decrypts it after atomically claiming the row, verifies that the representative
proof is still bound to the label's organisation, builds a fragment-only S-89
invitation URL in memory, and erases the secret after success or terminal
failure.  Neither raw invitation tokens nor delivery references are logged or
persisted in JSON/audit fields.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable
from urllib.parse import quote, urlsplit, urlunsplit

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import decrypt
from app.models.wave4 import (
    NotificationOutbox,
    OrganisationResponseRequest,
    PublishedRiskLabel,
)
from app.services.organisation_identity import representative_verification_hash

_KIND = "organisation_response_requested"
_CLAIM_LEASE = timedelta(minutes=5)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class NotificationRelayError(Exception):
    """Provider/contract failure carrying only a non-sensitive error code."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code[:80]
        self.retryable = retryable


@runtime_checkable
class ResponseInvitationProvider(Protocol):
    def send_invitation(
        self,
        *,
        organisation_id: uuid.UUID,
        delivery_ref: str,
        invitation_url: str,
        idempotency_key: str,
    ) -> None: ...


class DeterministicResponseInvitationProvider:
    """Explicit local/test adapter. Never selected in staging/production."""

    def __init__(self, *, fail_times: int = 0, retryable: bool = True) -> None:
        self.deliveries: list[dict[str, object]] = []
        self._idempotent_deliveries: dict[str, tuple[uuid.UUID, str, str]] = {}
        self.fail_times = fail_times
        self.retryable = retryable

    def send_invitation(
        self,
        *,
        organisation_id: uuid.UUID,
        delivery_ref: str,
        invitation_url: str,
        idempotency_key: str,
    ) -> None:
        signature = (organisation_id, delivery_ref, invitation_url)
        previous = self._idempotent_deliveries.get(idempotency_key)
        if previous is not None:
            if previous != signature:
                raise NotificationRelayError("provider_idempotency_conflict", retryable=False)
            return
        if self.fail_times:
            self.fail_times -= 1
            raise NotificationRelayError("provider_unavailable", retryable=self.retryable)
        self._idempotent_deliveries[idempotency_key] = signature
        self.deliveries.append({
            "organisation_id": organisation_id,
            "delivery_ref": delivery_ref,
            "invitation_url": invitation_url,
            "idempotency_key": idempotency_key,
        })


def build_response_invitation_provider() -> ResponseInvitationProvider | None:
    """Resolve the configured adapter; ``none`` leaves work pending."""
    if settings.internship_response_notification_provider == "none":
        return None
    if settings.internship_response_notification_provider == "deterministic":
        environment = (settings.app_env or "").strip().casefold()
        if environment not in {"test", "testing", "development", "dev", "local"}:
            raise NotificationRelayError("notification_provider_forbidden", retryable=False)
        return DeterministicResponseInvitationProvider()
    raise NotificationRelayError("notification_provider_unknown", retryable=False)


def _invitation_url(token: str) -> str:
    base = urlsplit(settings.internship_response_public_base_url)
    # The config validator already forbids base query/fragment. Re-check here so
    # a mutable test/runtime setting cannot accidentally move the bearer token
    # into server-visible request metadata.
    if base.query or base.fragment:
        raise NotificationRelayError("response_public_url_invalid", retryable=False)
    return urlunsplit((base.scheme, base.netloc, base.path, "", f"token={quote(token, safe='')}"))


def _invitation(
    session: Session, row: NotificationOutbox, *, now: datetime
) -> tuple[uuid.UUID, str, str]:
    # Follow the same label -> request -> outbox lock order as publication,
    # withdrawal and invitation renewal.  The outbox claim was committed
    # before this function, so it holds no lock while the governed rows lock.
    request_probe = session.scalar(select(OrganisationResponseRequest).where(
        OrganisationResponseRequest.id == row.aggregate_id,
        OrganisationResponseRequest.deleted_at.is_(None),
    ))
    if request_probe is None:
        raise NotificationRelayError("invitation_request_unavailable", retryable=False)
    label = session.scalar(select(PublishedRiskLabel).where(
        PublishedRiskLabel.id == request_probe.published_label_id,
        PublishedRiskLabel.deleted_at.is_(None),
    ).with_for_update())
    if label is None or label.status not in {"published", "corrected"}:
        raise NotificationRelayError("invitation_label_unavailable", retryable=False)
    request = session.scalar(select(OrganisationResponseRequest).where(
        OrganisationResponseRequest.id == request_probe.id,
        OrganisationResponseRequest.published_label_id == label.id,
        OrganisationResponseRequest.deleted_at.is_(None),
    ).with_for_update())
    if request is None or request.state != "pending":
        raise NotificationRelayError("invitation_request_unavailable", retryable=False)
    if _as_utc(request.expires_at) <= now:
        request.state = "expired"
        request.version += 1
        raise NotificationRelayError("invitation_expired", retryable=False)
    try:
        envelope = json.loads(decrypt(row.secret_ciphertext or ""))
    except Exception as exc:
        raise NotificationRelayError("invitation_envelope_invalid", retryable=False) from exc
    if not isinstance(envelope, dict) or set(envelope) != {
        "organisation_id", "delivery_ref", "invitation_token"
    }:
        raise NotificationRelayError("invitation_envelope_invalid", retryable=False)
    try:
        envelope_organisation_id = uuid.UUID(str(envelope["organisation_id"]))
    except (TypeError, ValueError, AttributeError) as exc:
        raise NotificationRelayError("invitation_envelope_invalid", retryable=False) from exc
    delivery_ref = envelope.get("delivery_ref")
    token = envelope.get("invitation_token")
    if (
        envelope_organisation_id != label.organisation_id
        or not isinstance(delivery_ref, str)
        or not isinstance(token, str)
        or len(token) < 32
        or request.representative_ref_hash != representative_verification_hash(
            label.organisation_id,
            request.representative_verification_method,
            delivery_ref,
        )
    ):
        raise NotificationRelayError("invitation_organisation_mismatch", retryable=False)
    return label.organisation_id, delivery_ref, _invitation_url(token)


@dataclass
class RelayResult:
    claimed: int = 0
    sent: int = 0
    failed: int = 0
    dead_lettered: int = 0
    skipped: int = 0


def _candidate_rows(
    session: Session, *, now: datetime, limit: int
) -> list[NotificationOutbox]:
    stale_before = now - _CLAIM_LEASE
    return list(session.scalars(
        select(NotificationOutbox).where(
            NotificationOutbox.event_kind == _KIND,
            NotificationOutbox.deleted_at.is_(None),
            or_(
                NotificationOutbox.state.in_(("pending", "failed")),
                (
                    (NotificationOutbox.state == "processing")
                    & (NotificationOutbox.claimed_at <= stale_before)
                ),
            ),
            or_(NotificationOutbox.available_at.is_(None), NotificationOutbox.available_at <= now),
        ).order_by(NotificationOutbox.created_at, NotificationOutbox.id).limit(limit)
    ))


def _claim(session: Session, row: NotificationOutbox, *, now: datetime) -> bool:
    stale_before = now - _CLAIM_LEASE
    claim_token = str(uuid.uuid4())
    result = session.execute(
        update(NotificationOutbox).where(
            NotificationOutbox.id == row.id,
            NotificationOutbox.attempts == row.attempts,
            or_(
                NotificationOutbox.state.in_(("pending", "failed")),
                (
                    (NotificationOutbox.state == "processing")
                    & (NotificationOutbox.claimed_at <= stale_before)
                ),
            ),
        ).values(
            state="processing",
            attempts=row.attempts + 1,
            claimed_at=now,
            claim_token=claim_token,
            last_error_code=None,
        ).execution_options(synchronize_session=False)
    )
    session.commit()
    return (result.rowcount or 0) == 1


def _dead_letter_exhausted(
    session: Session, row: NotificationOutbox, *, now: datetime
) -> bool:
    stale_before = now - _CLAIM_LEASE
    request = session.scalar(select(OrganisationResponseRequest).where(
        OrganisationResponseRequest.id == row.aggregate_id,
        OrganisationResponseRequest.deleted_at.is_(None),
    ).with_for_update())
    if request is not None and request.state == "pending":
        request.state = "revoked"
        request.version += 1
    result = session.execute(
        update(NotificationOutbox).where(
            NotificationOutbox.id == row.id,
            NotificationOutbox.attempts == row.attempts,
            or_(
                NotificationOutbox.state.in_(("pending", "failed")),
                (
                    (NotificationOutbox.state == "processing")
                    & (NotificationOutbox.claimed_at <= stale_before)
                ),
            ),
        ).values(
            state="void",
            claimed_at=None,
            claim_token=None,
            available_at=None,
            last_error_code="attempts_exhausted",
            sent_at=None,
            secret_ciphertext=None,
            secret_key_version=None,
        ).execution_options(synchronize_session=False)
    )
    if (result.rowcount or 0) == 1:
        session.commit()
        return True
    session.rollback()
    return False


def _finish(
    session: Session,
    row_id: uuid.UUID,
    *,
    state: str,
    now: datetime,
    error_code: str | None,
    expected_attempts: int,
    expected_claim_token: str,
) -> bool:
    terminal = state in {"sent", "void"}
    values: dict[str, object] = {
        "state": state,
        "claimed_at": None,
        "claim_token": None,
        "last_error_code": error_code,
        "sent_at": now if state == "sent" else None,
        "available_at": now + timedelta(seconds=30) if state == "failed" else None,
    }
    if terminal:
        values.update(secret_ciphertext=None, secret_key_version=None)
    result = session.execute(
        update(NotificationOutbox).where(
            NotificationOutbox.id == row_id,
            NotificationOutbox.state == "processing",
            NotificationOutbox.attempts == expected_attempts,
            NotificationOutbox.claim_token == expected_claim_token,
            NotificationOutbox.claimed_at.is_not(None),
        ).values(**values).execution_options(synchronize_session=False)
    )
    if (result.rowcount or 0) == 1:
        session.commit()
        return True
    session.rollback()
    return False


def _terminal_request_state(
    session: Session, row: NotificationOutbox, *, expired: bool
) -> None:
    request = session.scalar(select(OrganisationResponseRequest).where(
        OrganisationResponseRequest.id == row.aggregate_id,
        OrganisationResponseRequest.deleted_at.is_(None),
    ).with_for_update())
    if request is not None and request.state == "pending":
        request.state = "expired" if expired else "revoked"
        request.version += 1


def relay_response_invitations(
    session: Session,
    provider: ResponseInvitationProvider | None = None,
    *,
    now: datetime | None = None,
    limit: int = 50,
    max_attempts: int | None = None,
) -> RelayResult:
    """Claim and deliver due invitation rows once; disabled means no mutation."""
    provider = provider if provider is not None else build_response_invitation_provider()
    result = RelayResult()
    if provider is None:
        return result
    now = now or datetime.now(timezone.utc)
    attempt_limit = max_attempts or settings.worker_max_attempts
    for candidate in _candidate_rows(session, now=now, limit=limit):
        if candidate.attempts >= attempt_limit:
            if _dead_letter_exhausted(session, candidate, now=now):
                result.dead_lettered += 1
            else:
                result.skipped += 1
            continue
        if not _claim(session, candidate, now=now):
            result.skipped += 1
            continue
        result.claimed += 1
        session.refresh(candidate)
        row = candidate
        if row is None or row.claimed_at is None:
            result.skipped += 1
            continue
        try:
            organisation_id, delivery_ref, invitation_url = _invitation(session, row, now=now)
            provider.send_invitation(
                organisation_id=organisation_id,
                delivery_ref=delivery_ref,
                invitation_url=invitation_url,
                idempotency_key=row.idempotency_key,
            )
        except Exception as exc:
            retryable = bool(getattr(exc, "retryable", False))
            error_code = exc.code if isinstance(exc, NotificationRelayError) else "provider_failure"
            exhausted = row.attempts >= attempt_limit
            if retryable and not exhausted:
                finished = _finish(
                    session, row.id, state="failed", now=now, error_code=error_code,
                    expected_attempts=row.attempts,
                    expected_claim_token=row.claim_token,
                )
                result.failed += int(finished)
                result.skipped += int(not finished)
            else:
                _terminal_request_state(
                    session, row, expired=error_code == "invitation_expired"
                )
                finished = _finish(
                    session, row.id, state="void", now=now, error_code=error_code,
                    expected_attempts=row.attempts,
                    expected_claim_token=row.claim_token,
                )
                result.dead_lettered += int(finished)
                result.skipped += int(not finished)
            continue
        finished = _finish(
            session, row.id, state="sent", now=now, error_code=None,
            expected_attempts=row.attempts,
            expected_claim_token=row.claim_token,
        )
        result.sent += int(finished)
        result.skipped += int(not finished)
    return result
