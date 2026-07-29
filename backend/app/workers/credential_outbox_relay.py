"""Retry relay for credential evidence scans, erasure and expiry reminders."""
from __future__ import annotations

import abc
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_sessionmaker
from app.integrations.storage import StorageAdapter
from app.models.credentials import (
    Credential,
    CredentialEvidence,
    CredentialEvidenceScanEvent,
    CredentialOutbox,
    CredentialReminderJob,
    CredentialStatusHistory,
)
from app.services.credential_storage import (
    EvidenceScanner,
    EvidenceScanUnavailable,
    get_credential_storage,
    get_evidence_scanner,
)


class CredentialReminderSender(abc.ABC):
    @abc.abstractmethod
    def send(self, credential_id: uuid.UUID, days_before: int) -> None: ...


class DeterministicReminderSender(CredentialReminderSender):
    def send(self, credential_id: uuid.UUID, days_before: int) -> None:
        # Local/CI adapter deliberately has no user PII and no network side effect.
        return None


def _retry(row: CredentialOutbox, code: str) -> None:
    row.attempts += 1
    row.status = "failed" if row.attempts >= 3 else "pending"
    row.last_error_code = code[:80]
    row.available_at = datetime.now(timezone.utc) + timedelta(
        seconds=min(300, 2 ** row.attempts)
    )


def _scan(
    session: Session,
    row: CredentialOutbox,
    storage: StorageAdapter,
    scanner: EvidenceScanner,
) -> None:
    evidence = (
        session.get(CredentialEvidence, row.evidence_id)
        if row.evidence_id
        else None
    )
    if evidence is None or evidence.deleted_at is not None:
        row.status = "complete"
        row.delivered_at = datetime.now(timezone.utc)
        return
    try:
        result = scanner.scan(
            storage.get(evidence.object_ref), detected_mime=evidence.detected_mime
        )
    except (EvidenceScanUnavailable, OSError):
        _retry(row, "scanner_unavailable")
        return
    evidence.scan_state = result.state
    session.add(
        CredentialEvidenceScanEvent(
            evidence_id=evidence.id,
            scan_state=result.state,
            provider=result.provider,
            result_code=result.result_code,
        )
    )
    if result.state == "infected":
        storage.delete(evidence.object_ref)
        evidence.object_ref = f"deleted:{evidence.id}"
        evidence.deleted_at = datetime.now(timezone.utc)
    elif result.state == "clean":
        credential = session.get(Credential, evidence.credential_id)
        if credential and credential.status == "self_declared":
            previous = credential.status
            credential.status = "pending_verification"
            credential.version += 1
            session.add(
                CredentialStatusHistory(
                    credential_id=credential.id,
                    actor_user_id=None,
                    from_status=previous,
                    to_status=credential.status,
                    reason_code="retry_scan_clean",
                )
            )
    row.status = "complete"
    row.delivered_at = datetime.now(timezone.utc)
    row.last_error_code = None


def _delete(
    session: Session, row: CredentialOutbox, storage: StorageAdapter
) -> None:
    evidence = (
        session.get(CredentialEvidence, row.evidence_id)
        if row.evidence_id
        else None
    )
    if evidence and not evidence.object_ref.startswith("deleted:"):
        storage.delete(evidence.object_ref)
        evidence.object_ref = f"deleted:{evidence.id}"
    row.status = "complete"
    row.delivered_at = datetime.now(timezone.utc)
    row.last_error_code = None


def _remind(
    session: Session,
    row: CredentialOutbox,
    reminder_sender: CredentialReminderSender,
) -> None:
    days = int((row.payload_json or {}).get("days_before", 0))
    try:
        reminder_sender.send(row.credential_id, days)
    except Exception:
        _retry(row, "reminder_provider_failure")
        return
    job = session.scalar(
        select(CredentialReminderJob).where(
            CredentialReminderJob.credential_id == row.credential_id,
            CredentialReminderJob.days_before == days,
        )
    )
    if job:
        job.status = "sent"
    row.status = "complete"
    row.delivered_at = datetime.now(timezone.utc)
    row.last_error_code = None


def relay_credential_outbox(
    *,
    limit: int = 50,
    storage: StorageAdapter | None = None,
    scanner: EvidenceScanner | None = None,
    reminder_sender: CredentialReminderSender | None = None,
    session_factory=None,
) -> int:
    factory = session_factory or get_sessionmaker()
    storage = storage or get_credential_storage()
    scanner = scanner or get_evidence_scanner()
    reminder_sender = reminder_sender or DeterministicReminderSender()
    now = datetime.now(timezone.utc)
    processed = 0
    with factory() as session:
        rows = session.scalars(
            select(CredentialOutbox)
            .where(
                CredentialOutbox.status == "pending",
                CredentialOutbox.available_at <= now,
            )
            .order_by(CredentialOutbox.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
        for row in rows:
            row.status = "processing"
            if row.kind == "scan_evidence":
                _scan(session, row, storage, scanner)
            elif row.kind == "delete_evidence":
                _delete(session, row, storage)
            elif row.kind == "expiry_reminder":
                _remind(session, row, reminder_sender)
            processed += 1
        session.commit()
    return processed
