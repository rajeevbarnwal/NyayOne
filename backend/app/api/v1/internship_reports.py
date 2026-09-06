"""S-86/S-87 private internship reporting HTTP API.

The only projections in this router are reporter-owned.  There is deliberately
no public report or public risk-label endpoint; public activation remains gated
by SAATHI-452/279 and ``INTERNSHIP_RISK_LABELS_ENABLED=false``.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.openapi_headers import required_idempotency_header
from app.core.auth import ActorContext, Role, get_actor_context
from app.core.config import settings
from app.core.crypto import encrypt, key_version, keyed_hash
from app.db.session import get_session
from app.integrations.storage import StorageAdapter
from app.models.wave4 import (
    InternshipReport,
    InternshipReportCategory,
    InternshipReportConsent,
    InternshipReportEvidence,
    InternshipReportingOutbox,
    ModerationCase,
    ModerationHandoff,
    ReporterIdentityVault,
)
from app.schemas.reporting import (
    InternshipReportListOut,
    InternshipReportOut,
    InternshipReportStatusOut,
    ReportDraftCreate,
    ReportDraftPatch,
    ReportEvidenceOut,
    ReportSubmit,
)
from app.services.audit_service import record_audit_event
from app.services.report_storage import (
    ReportEvidenceInfected,
    ReportEvidenceScanner,
    ReportEvidenceScanUnavailable,
    get_report_evidence_scanner,
    get_report_storage,
    validate_report_evidence,
)

router = APIRouter(prefix="/internship-reports", tags=["internship-reports"])
_UNSAFE_IDEMPOTENCY = re.compile(r"[\x00-\x20<>]")
_SUPPORT_CATEGORIES = frozenset({"unsafe_environment", "harassment", "discrimination"})


def _error(status_code: int, code: str, message: str, *, field: str | None = None, **extra: object) -> HTTPException:
    detail: dict[str, object] = {"code": code, "message": message}
    if field:
        detail["field"] = field
    detail.update(extra)
    return HTTPException(status_code=status_code, detail=detail)


def _require_student(actor: ActorContext = Depends(get_actor_context)) -> ActorContext:
    if not actor.is_authenticated:
        raise _error(401, "authentication_required", "Authentication required")
    if not actor.has_role(Role.STUDENT):
        raise _error(403, "student_role_required", "Student role required")
    return actor


def _idempotency(value: str | None) -> str:
    cleaned = (value or "").strip()
    if not 8 <= len(cleaned) <= 200 or _UNSAFE_IDEMPOTENCY.search(cleaned):
        raise _error(
            422,
            "invalid_idempotency_key",
            "Idempotency-Key must contain 8 to 200 safe non-space characters",
            field="Idempotency-Key",
        )
    return cleaned


def _owner_hash(user_id: uuid.UUID) -> str:
    return keyed_hash(str(user_id), lower=True)


def _owned_report(
    session: Session,
    report_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> InternshipReport:
    stmt = (
        select(InternshipReport)
        .join(ReporterIdentityVault, ReporterIdentityVault.report_id == InternshipReport.id)
        .where(
            InternshipReport.id == report_id,
            InternshipReport.deleted_at.is_(None),
            ReporterIdentityVault.reporter_lookup_hash == _owner_hash(user_id),
            ReporterIdentityVault.deleted_at.is_(None),
        )
    )
    if for_update:
        stmt = stmt.with_for_update()
    row = session.scalar(stmt)
    if row is None:
        raise _error(404, "internship_report_not_found", "Internship report not found")
    return row


def _categories(session: Session, report_id: uuid.UUID) -> list[str]:
    return list(
        session.scalars(
            select(InternshipReportCategory.category)
            .where(
                InternshipReportCategory.report_id == report_id,
                InternshipReportCategory.deleted_at.is_(None),
            )
            .order_by(InternshipReportCategory.category)
        )
    )


def _consent(session: Session, report_id: uuid.UUID) -> InternshipReportConsent | None:
    return session.scalar(
        select(InternshipReportConsent).where(
            InternshipReportConsent.report_id == report_id,
            InternshipReportConsent.deleted_at.is_(None),
        )
    )


def _evidence(session: Session, report_id: uuid.UUID) -> list[InternshipReportEvidence]:
    return list(
        session.scalars(
            select(InternshipReportEvidence)
            .where(
                InternshipReportEvidence.report_id == report_id,
                InternshipReportEvidence.deleted_at.is_(None),
                InternshipReportEvidence.scan_state != "deleted",
            )
            .order_by(InternshipReportEvidence.created_at, InternshipReportEvidence.id)
        )
    )


def _evidence_out(row: InternshipReportEvidence, *, retryable: bool | None = None) -> ReportEvidenceOut:
    return ReportEvidenceOut(
        id=row.id,
        mime_type=row.mime_type,
        size_bytes=row.size_bytes,
        checksum_sha256=row.checksum_sha256,
        scan_state=row.scan_state,
        retryable=row.scan_state == "retryable_failure" if retryable is None else retryable,
    )


def _report_out(session: Session, row: InternshipReport) -> InternshipReportOut:
    consent = _consent(session, row.id)
    return InternshipReportOut(
        id=row.id,
        organisation_name=row.organisation_name,
        listing_application_ref=row.listing_application_ref,
        experience_start_date=row.experience_start_date,
        experience_end_date=row.experience_end_date,
        categories=_categories(session, row.id),
        narrative=row.narrative,
        privacy_mode=row.privacy_mode,
        consent_accepted=bool(consent and consent.accepted),
        consent_version=consent.consent_version if consent else None,
        status=row.status,
        support_guidance_required=row.support_guidance_required,
        evidence=[_evidence_out(item) for item in _evidence(session, row.id)],
        version=row.version,
        submitted_at=row.submitted_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _validate_combined_dates(start: date | None, end: date | None) -> None:
    today = date.today()
    if start and start > today:
        raise _error(422, "future_experience_start_date", "Experience start date cannot be in the future", field="experience_start_date")
    if end and end > today:
        raise _error(422, "future_experience_end_date", "Experience end date cannot be in the future", field="experience_end_date")
    if start and end and end < start:
        raise _error(422, "experience_end_before_start", "Experience end date cannot precede the start date", field="experience_end_date")


def _sync_categories(session: Session, report_id: uuid.UUID, categories: list[str]) -> None:
    session.execute(delete(InternshipReportCategory).where(InternshipReportCategory.report_id == report_id))
    for category in categories:
        session.add(InternshipReportCategory(report_id=report_id, category=category))


def _sync_consent(
    session: Session,
    report_id: uuid.UUID,
    *,
    accepted: bool,
    version: str | None,
    now: datetime,
) -> None:
    row = _consent(session, report_id)
    if row is None:
        row = InternshipReportConsent(
            report_id=report_id,
            consent_version=version or settings.internship_report_consent_version,
        )
        session.add(row)
    row.consent_version = version or settings.internship_report_consent_version
    row.accepted = accepted
    row.accepted_at = now if accepted else None


def _apply_draft_fields(
    session: Session,
    row: InternshipReport,
    payload: ReportDraftCreate | ReportDraftPatch,
    *,
    now: datetime,
) -> None:
    supplied = payload.model_fields_set
    if "organisation_name" in supplied:
        row.organisation_name = payload.organisation_name or ""
    if "listing_application_ref" in supplied:
        row.listing_application_ref = payload.listing_application_ref or ""
    if "experience_start_date" in supplied:
        row.experience_start_date = payload.experience_start_date
    if "experience_end_date" in supplied:
        row.experience_end_date = payload.experience_end_date
    if "narrative" in supplied:
        row.narrative = payload.narrative or ""
    if "privacy_mode" in supplied and payload.privacy_mode is not None:
        row.privacy_mode = payload.privacy_mode
    _validate_combined_dates(row.experience_start_date, row.experience_end_date)
    if "categories" in supplied:
        _sync_categories(session, row.id, payload.categories or [])
    if "consent_accepted" in supplied or "consent_version" in supplied:
        current = _consent(session, row.id)
        accepted = payload.consent_accepted if payload.consent_accepted is not None else bool(current and current.accepted)
        version = payload.consent_version or (current.consent_version if current else None)
        _sync_consent(session, row.id, accepted=accepted, version=version, now=now)


def _validate_submission(session: Session, row: InternshipReport) -> list[tuple[str, str]]:
    errors: list[tuple[str, str]] = []
    if not row.organisation_name.strip():
        errors.append(("organisation_required", "organisation_name"))
    if not row.listing_application_ref.strip():
        errors.append(("listing_application_reference_required", "listing_application_ref"))
    if row.experience_start_date is None:
        errors.append(("experience_start_date_required", "experience_start_date"))
    if row.experience_end_date is None:
        errors.append(("experience_end_date_required", "experience_end_date"))
    _validate_combined_dates(row.experience_start_date, row.experience_end_date)
    narrative_length = len(row.narrative.strip())
    if narrative_length < 50 or narrative_length > 5000:
        errors.append(("narrative_length_invalid", "narrative"))
    if not _categories(session, row.id):
        errors.append(("category_required", "categories"))
    consent = _consent(session, row.id)
    if not consent or not consent.accepted:
        errors.append(("consent_required", "consent_accepted"))
    elif consent.consent_version != settings.internship_report_consent_version:
        errors.append(("consent_version_stale", "consent_version"))
    if any(item.scan_state != "clean" for item in _evidence(session, row.id)):
        errors.append(("evidence_not_ready", "evidence"))
    return errors


@router.post("", response_model=InternshipReportOut, status_code=201, openapi_extra=required_idempotency_header())
def create_report(
    payload: ReportDraftCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", include_in_schema=False),
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(_require_student),
) -> InternshipReportOut:
    key = _idempotency(idempotency_key)
    owner_hash = _owner_hash(actor.user_id)
    existing = session.scalar(select(InternshipReport).where(InternshipReport.idempotency_key == key))
    if existing is not None:
        vault = session.scalar(select(ReporterIdentityVault).where(ReporterIdentityVault.report_id == existing.id))
        if vault and vault.reporter_lookup_hash == owner_hash:
            return _report_out(session, existing)
        raise _error(409, "idempotency_conflict", "Idempotency key already used")

    now = datetime.now(timezone.utc)
    row = InternshipReport(idempotency_key=key)
    session.add(row)
    try:
        # The UNIQUE idempotency conflict can happen at this flush on
        # PostgreSQL, before commit. Keep the entire create transaction inside
        # the recovery boundary so concurrent retries return the winner rather
        # than leaking an IntegrityError.
        session.flush()
        ciphertext = encrypt(str(actor.user_id))
        session.add(
            ReporterIdentityVault(
                report_id=row.id,
                reporter_lookup_hash=owner_hash,
                reporter_ciphertext=ciphertext,
                key_version=key_version(ciphertext),
            )
        )
        _apply_draft_fields(session, row, payload, now=now)
        record_audit_event(
            session,
            action="internship_report_draft_created",
            resource_type="internship_report",
            resource_id=row.id,
            actor_role="student",
            after_state={"status": "draft", "privacy_mode": row.privacy_mode, "version": row.version},
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(select(InternshipReport).where(InternshipReport.idempotency_key == key))
        if existing is not None:
            vault = session.scalar(select(ReporterIdentityVault).where(ReporterIdentityVault.report_id == existing.id))
            if vault and vault.reporter_lookup_hash == owner_hash:
                return _report_out(session, existing)
        raise _error(409, "idempotency_conflict", "Idempotency key already used")
    return _report_out(session, row)


@router.get("", response_model=InternshipReportListOut)
def list_my_reports(
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(_require_student),
) -> InternshipReportListOut:
    items = list(
        session.scalars(
            select(InternshipReport)
            .join(ReporterIdentityVault, ReporterIdentityVault.report_id == InternshipReport.id)
            .where(
                ReporterIdentityVault.reporter_lookup_hash == _owner_hash(actor.user_id),
                InternshipReport.deleted_at.is_(None),
                ReporterIdentityVault.deleted_at.is_(None),
            )
            .order_by(InternshipReport.updated_at.desc(), InternshipReport.id)
        )
    )
    return InternshipReportListOut(items=[_report_out(session, item) for item in items], total=len(items))


@router.get("/{report_id}", response_model=InternshipReportOut)
def get_report(
    report_id: uuid.UUID,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(_require_student),
) -> InternshipReportOut:
    return _report_out(session, _owned_report(session, report_id, actor.user_id))


@router.patch("/{report_id}", response_model=InternshipReportOut)
def update_report(
    report_id: uuid.UUID,
    payload: ReportDraftPatch,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(_require_student),
) -> InternshipReportOut:
    row = _owned_report(session, report_id, actor.user_id, for_update=True)
    if row.status != "draft":
        raise _error(409, "report_not_mutable", "Submitted report cannot be edited")
    if row.version != payload.expected_version:
        raise _error(409, "stale_report_version", "Report changed in another session", current_version=row.version)
    now = datetime.now(timezone.utc)
    _apply_draft_fields(session, row, payload, now=now)
    row.version += 1
    record_audit_event(
        session,
        action="internship_report_draft_saved",
        resource_type="internship_report",
        resource_id=row.id,
        actor_role="student",
        after_state={"status": row.status, "version": row.version},
    )
    session.commit()
    return _report_out(session, row)


@router.post("/{report_id}/evidence", response_model=ReportEvidenceOut)
async def upload_evidence(
    report_id: uuid.UUID,
    expected_version: int = Form(..., ge=1),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(_require_student),
    storage: StorageAdapter = Depends(get_report_storage),
    scanner: ReportEvidenceScanner = Depends(get_report_evidence_scanner),
) -> ReportEvidenceOut:
    row = _owned_report(session, report_id, actor.user_id, for_update=True)
    if row.status != "draft":
        raise _error(409, "report_not_mutable", "Submitted report cannot accept evidence")
    if row.version != expected_version:
        raise _error(409, "stale_report_version", "Report changed in another session", current_version=row.version)
    if session.scalar(
        select(func.count()).select_from(InternshipReportEvidence).where(
            InternshipReportEvidence.report_id == row.id,
            InternshipReportEvidence.deleted_at.is_(None),
            InternshipReportEvidence.scan_state != "deleted",
        )
    ) >= settings.internship_report_max_evidence_files:
        raise _error(422, "evidence_file_limit", "A report accepts at most five evidence files", field="evidence")

    data = await file.read(settings.internship_report_max_file_bytes + 1)
    try:
        mime = validate_report_evidence(filename=file.filename, declared_mime=file.content_type, data=data)
    except ValueError as exc:
        code = str(exc)
        raise _error(422, code, "Evidence file was rejected", field="evidence") from None
    digest = hashlib.sha256(data).hexdigest()
    duplicate = session.scalar(
        select(InternshipReportEvidence.id).where(
            InternshipReportEvidence.report_id == row.id,
            InternshipReportEvidence.checksum_sha256 == digest,
            InternshipReportEvidence.deleted_at.is_(None),
        )
    )
    if duplicate:
        raise _error(409, "duplicate_evidence", "Evidence file is already attached", field="evidence")

    object_ref = f"internship-reports/{row.id}/{uuid.uuid4().hex}"
    evidence = InternshipReportEvidence(
        report_id=row.id,
        object_ref=object_ref,
        mime_type=mime,
        size_bytes=len(data),
        checksum_sha256=digest,
        scan_state="quarantined",
        retention_policy="configured",
    )
    session.add(evidence)
    storage.put(object_ref, data, content_type=mime)
    try:
        scanner.scan(data)
    except ReportEvidenceInfected:
        storage.delete(object_ref)
        session.rollback()
        raise _error(422, "infected_evidence", "Evidence failed malware screening", field="evidence") from None
    except ReportEvidenceScanUnavailable:
        evidence.scan_state = "retryable_failure"
        evidence.scanner_result_code = "scanner_unavailable"
        row.version += 1
        session.add(
            InternshipReportingOutbox(
                event_kind="evidence_scan_requested",
                aggregate_type="internship_report",
                aggregate_id=row.id,
                idempotency_key=f"evidence-scan:{evidence.id}",
                payload_json={"evidence_id": str(evidence.id)},
            )
        )
        record_audit_event(
            session,
            action="internship_report_evidence_quarantined",
            resource_type="internship_report",
            resource_id=row.id,
            actor_role="student",
            after_state={"scan_state": "retryable_failure", "version": row.version},
        )
        session.commit()
        raise _error(503, "evidence_scanner_unavailable", "Evidence remains quarantined; retry later", field="evidence", retryable=True) from None
    evidence.scan_state = "clean"
    evidence.scanner_result_code = "clean"
    row.version += 1
    record_audit_event(
        session,
        action="internship_report_evidence_added",
        resource_type="internship_report",
        resource_id=row.id,
        actor_role="student",
        after_state={"scan_state": "clean", "version": row.version},
    )
    try:
        session.commit()
    except Exception:
        session.rollback()
        storage.delete(object_ref)
        raise
    return _evidence_out(evidence)


@router.post("/{report_id}/submit", response_model=InternshipReportOut)
def submit_report(
    report_id: uuid.UUID,
    payload: ReportSubmit,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(_require_student),
) -> InternshipReportOut:
    row = _owned_report(session, report_id, actor.user_id, for_update=True)
    if row.status == "moderation_pending":
        return _report_out(session, row)
    if row.status != "draft":
        raise _error(409, "report_not_submittable", "Report cannot be submitted in its current state")
    if row.version != payload.expected_version:
        raise _error(409, "stale_report_version", "Report changed in another session", current_version=row.version)
    errors = _validate_submission(session, row)
    if errors:
        code, field = errors[0]
        raise _error(422, code, "Report is incomplete", field=field)
    now = datetime.now(timezone.utc)
    categories = set(_categories(session, row.id))
    row.support_guidance_required = bool(categories & _SUPPORT_CATEGORIES)
    row.status = "moderation_pending"
    row.submitted_at = now
    row.version += 1
    session.add(ModerationHandoff(report_id=row.id, state="pending"))
    session.add(ModerationCase(report_id=row.id, state="pending"))
    session.add_all(
        [
            InternshipReportingOutbox(
                event_kind="report_submitted",
                aggregate_type="internship_report",
                aggregate_id=row.id,
                idempotency_key=f"report-submitted:{row.id}",
                payload_json={"status": "moderation_pending"},
            ),
            InternshipReportingOutbox(
                event_kind="moderation_handoff_created",
                aggregate_type="internship_report",
                aggregate_id=row.id,
                idempotency_key=f"moderation-handoff:{row.id}",
                payload_json={"state": "pending"},
            ),
        ]
    )
    record_audit_event(
        session,
        action="internship_report_submitted",
        resource_type="internship_report",
        resource_id=row.id,
        actor_role="student",
        after_state={
            "status": "moderation_pending",
            "support_guidance_required": row.support_guidance_required,
            "version": row.version,
        },
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        current = _owned_report(session, report_id, actor.user_id)
        if current.status == "moderation_pending":
            return _report_out(session, current)
        raise _error(409, "report_submission_conflict", "Report submission conflicted with another request")
    return _report_out(session, row)


@router.get("/{report_id}/status", response_model=InternshipReportStatusOut)
def get_report_status(
    report_id: uuid.UUID,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(_require_student),
) -> InternshipReportStatusOut:
    row = _owned_report(session, report_id, actor.user_id)
    evidence = _evidence(session, row.id)
    return InternshipReportStatusOut(
        id=row.id,
        status=row.status,
        privacy_mode=row.privacy_mode,
        support_guidance_required=row.support_guidance_required,
        evidence_total=len(evidence),
        evidence_clean=sum(item.scan_state == "clean" for item in evidence),
        version=row.version,
        submitted_at=row.submitted_at,
    )
