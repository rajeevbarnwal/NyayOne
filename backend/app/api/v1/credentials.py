"""Credential wallet, issuer verification and public share APIs.

SAATHI-253 / SAATHI-258: server-authoritative persistence, explicit issuer
grants, privacy-safe evidence metadata and hash-only bearer tokens.
"""
from __future__ import annotations

import base64
import hashlib
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.openapi_headers import required_idempotency_header
from app.core.auth import ActorContext, Role, get_actor_context
from app.core.config import settings
from app.core.crypto import (
    active_key_version,
    decrypt,
    encrypt,
    keyed_hash,
)
from app.core.guardian_authority import has_authoritative_guardian_proof
from app.db.session import get_session
from app.models.credentials import (
    CREDENTIAL_TYPES,
    Credential,
    CredentialEvidence,
    CredentialEvidenceScanEvent,
    CredentialOutbox,
    CredentialReminderJob,
    CredentialRevocation,
    CredentialShareProjection,
    CredentialStatusHistory,
    CredentialVerificationEvent,
    IssuerAuthorisation,
    VerificationAccessLog,
    VerificationToken,
)
from app.models.registration import GuardianConsent, StudentRegistration
from app.services.audit_service import record_audit_event
from app.services import login_service
from app.services.integrity_errors import constraint_name
from app.services.credential_storage import (
    EvidenceScanner,
    EvidenceScanUnavailable,
    get_credential_storage,
    get_evidence_scanner,
    validate_evidence,
)
from app.integrations.storage import StorageAdapter

router = APIRouter(tags=["credentials"])

PUBLIC_FIELDS = frozenset(
    {
        "title",
        "credential_type",
        "status",
        "issue_date",
        "expiry_date",
        "issuer_display_name",
        "verification_timestamp",
        "student_name",
    }
)
_UNSAFE_TEXT = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f<>]")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_CREDENTIAL_IDEMPOTENCY_CONSTRAINT = "uq_credentials_owner_idempotency"
_CREDENTIAL_IDENTIFIER_CONSTRAINT = "uq_credentials_owner_identifier_hash"
_SHARE_IDEMPOTENCY_CONSTRAINT = (
    "uq_credential_share_projections_owner_idempotency"
)
_TOKEN_IDEMPOTENCY_CONSTRAINT = "uq_verification_tokens_owner_idempotency"
_TOKEN_HASH_CONSTRAINT = "uq_verification_tokens_token_hash"


def _error(
    status_code: int,
    code: str,
    message: str,
    *,
    field: str | None = None,
    **extra: object,
) -> HTTPException:
    detail: dict[str, object] = {"code": code, "message": message}
    if field:
        detail["field"] = field
    detail.update(extra)
    return HTTPException(status_code=status_code, detail=detail)


def _clean_text(value: str, *, field: str, minimum: int, maximum: int) -> str:
    cleaned = " ".join((value or "").strip().split())
    if len(cleaned) < minimum or len(cleaned) > maximum or _UNSAFE_TEXT.search(cleaned):
        raise ValueError(f"{field}_invalid")
    return cleaned


def _require_student(actor: ActorContext = Depends(get_actor_context)) -> ActorContext:
    if not actor.is_authenticated:
        raise _error(401, "authentication_required", "Authentication required")
    if not actor.has_role(Role.STUDENT):
        raise _error(403, "student_role_required", "Student role required")
    return actor


def _require_authenticated(
    actor: ActorContext = Depends(get_actor_context),
) -> ActorContext:
    if not actor.is_authenticated:
        raise _error(401, "authentication_required", "Authentication required")
    return actor


def _idempotency(value: str | None) -> str:
    value = (value or "").strip()
    if not 8 <= len(value) <= 200 or _UNSAFE_TEXT.search(value):
        raise _error(
            422,
            "invalid_idempotency_key",
            "Idempotency-Key must contain 8 to 200 safe characters",
            field="Idempotency-Key",
        )
    return value


class CredentialCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    credential_type: str
    issue_date: date
    expiry_date: date | None = None
    issuer_id: uuid.UUID | None = None
    identifier: str | None = Field(default=None, max_length=120)

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        return _clean_text(value, field="title", minimum=2, maximum=160)

    @field_validator("credential_type")
    @classmethod
    def _type(cls, value: str) -> str:
        if value not in CREDENTIAL_TYPES:
            raise ValueError("unsupported_credential_type")
        return value

    @field_validator("identifier")
    @classmethod
    def _identifier(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return _clean_text(value, field="identifier", minimum=2, maximum=120)

    @model_validator(mode="after")
    def _dates(self):
        if self.issue_date > date.today():
            raise ValueError("future_issue_date")
        if self.expiry_date and self.expiry_date < self.issue_date:
            raise ValueError("expiry_before_issue")
        return self


class CredentialPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    expiry_date: date | None = None
    identifier: str | None = Field(default=None, max_length=120)
    expected_version: int = Field(ge=1)

    @field_validator("title")
    @classmethod
    def _title(cls, value: str | None) -> str | None:
        return (
            _clean_text(value, field="title", minimum=2, maximum=160)
            if value is not None
            else None
        )

    @field_validator("identifier")
    @classmethod
    def _identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            return ""
        return _clean_text(value, field="identifier", minimum=2, maximum=120)


class ShareProjectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fields: list[str] = Field(min_length=1, max_length=len(PUBLIC_FIELDS))

    @field_validator("fields")
    @classmethod
    def _fields(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("duplicate_projection_field")
        unsupported = sorted(set(values) - PUBLIC_FIELDS)
        if unsupported:
            raise ValueError(f"unsupported_projection_fields:{','.join(unsupported)}")
        return values


class VerificationTokenCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    projection_id: uuid.UUID
    lifetime_days: int = Field(default=90, ge=1, le=90)


class VerifyCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)


class RevokeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str
    expected_version: int = Field(ge=1)

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        return _clean_text(value, field="reason", minimum=10, maximum=500)


def _get_owned(
    session: Session,
    credential_id: uuid.UUID,
    owner_user_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> Credential:
    statement = select(Credential).where(
        Credential.id == credential_id,
        Credential.owner_user_id == owner_user_id,
        Credential.deleted_at.is_(None),
    )
    if for_update:
        statement = statement.with_for_update()
    row = session.scalar(statement)
    if row is None:
        raise _error(404, "credential_not_found", "Credential not found")
    return row


def _require_presented_effect_session(
    session: Session,
    request: Request,
    actor: ActorContext,
    *,
    now: datetime,
) -> None:
    """Revalidate cookie authority after domain locks and before any effect.

    Development/test header actors deliberately have no cookie to revalidate.
    A production actor, however, can only originate from the opaque session
    cookie and every side effect must lock that exact row before replay, audit,
    mutation, external I/O, or commit.
    """

    raw_session_token = request.cookies.get(settings.auth_session_cookie_name)
    if raw_session_token is None:
        return
    locked_session = login_service.lock_presented_session_for_effect(
        session,
        raw_session_token,
        expected_user_id=actor.user_id,
        now=now,
        allowed_roles=frozenset(role.value for role in actor.roles),
    )
    if locked_session is None:
        raise _error(401, "authentication_required", "Authentication required")


def _require_current_sharing_access(
    session: Session,
    actor: ActorContext,
) -> None:
    """Enforce GUARD-05 from current database authority, never client claims."""

    registrations = list(
        session.scalars(
            select(StudentRegistration)
            .where(
                StudentRegistration.user_id == actor.user_id,
                StudentRegistration.deleted_at.is_(None),
                StudentRegistration.status.in_(("otp_verified", "active")),
                StudentRegistration.dob_hash_state == "verified",
            )
            .limit(2)
            .with_for_update()
        )
    )
    access_error: HTTPException | None = None
    registration = registrations[0] if len(registrations) == 1 else None
    if registration is None:
        access_error = _error(
            403,
            "guardian_verification_required",
            "Guardian verification is required for sharing",
        )
    elif registration.is_minor:
        guardians = list(
            session.scalars(
                select(GuardianConsent)
                .where(GuardianConsent.registration_id == registration.id)
                .limit(2)
                .with_for_update()
            )
        )
        if len(guardians) != 1 or not has_authoritative_guardian_proof(
            guardians[0]
        ):
            access_error = _error(
                403,
                "guardian_verification_required",
                "Guardian verification is required for sharing",
            )

    if access_error is not None:
        raise access_error


def _get_owned_after_sharing_access_lock(
    session: Session,
    credential_id: uuid.UUID,
    actor: ActorContext,
    *,
    request: Request,
    now: datetime,
) -> Credential:
    """Lock profile authority first without weakening the owned-404 oracle."""

    access_error: HTTPException | None = None
    try:
        _require_current_sharing_access(
            session,
            actor,
        )
    except HTTPException as exc:
        access_error = exc
    row = _get_owned(
        session, credential_id, actor.user_id, for_update=True
    )
    _require_presented_effect_session(
        session, request, actor, now=now
    )
    if access_error is not None:
        raise access_error
    return row


def _history(
    session: Session,
    credential: Credential,
    actor_user_id: uuid.UUID | None,
    from_status: str | None,
    to_status: str,
    reason_code: str,
) -> None:
    session.add(
        CredentialStatusHistory(
            credential_id=credential.id,
            actor_user_id=actor_user_id,
            from_status=from_status,
            to_status=to_status,
            reason_code=reason_code,
        )
    )


def _issuer_name(session: Session, credential: Credential) -> str | None:
    if not credential.issuer_id:
        return None
    from app.models.credentials import CredentialIssuer

    issuer = session.get(CredentialIssuer, credential.issuer_id)
    return issuer.display_name if issuer and issuer.active else None


def _effective_status(credential: Credential) -> str:
    if (
        credential.status == "verified"
        and credential.expiry_date is not None
        and credential.expiry_date < date.today()
    ):
        return "expired"
    return credential.status


def _as_utc(value: datetime) -> datetime:
    """SQLite drops timezone metadata; PostgreSQL retains it."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _credential_payload(session: Session, credential: Credential) -> dict[str, object]:
    evidence = session.scalars(
        select(CredentialEvidence)
        .where(
            CredentialEvidence.credential_id == credential.id,
            CredentialEvidence.deleted_at.is_(None),
        )
        .order_by(CredentialEvidence.created_at)
    ).all()
    return {
        "id": str(credential.id),
        "title": credential.title,
        "credential_type": credential.credential_type,
        "status": _effective_status(credential),
        "issue_date": credential.issue_date.isoformat(),
        "expiry_date": (
            credential.expiry_date.isoformat() if credential.expiry_date else None
        ),
        "issuer_id": str(credential.issuer_id) if credential.issuer_id else None,
        "issuer_display_name": _issuer_name(session, credential),
        "identifier": (
            decrypt(credential.identifier_ct) if credential.identifier_ct else None
        ),
        "version": credential.version,
        "evidence": [
            {
                "id": str(item.id),
                "mime": item.detected_mime,
                "size_bytes": item.size_bytes,
                "sha256": item.sha256_digest,
                "scan_state": item.scan_state,
            }
            for item in evidence
        ],
        "created_at": credential.created_at.isoformat(),
        "updated_at": credential.updated_at.isoformat(),
    }


def _schedule_reminders(session: Session, credential: Credential) -> None:
    session.execute(
        delete(CredentialReminderJob).where(
            CredentialReminderJob.credential_id == credential.id
        )
    )
    if not credential.expiry_date:
        return
    for days_before in (30, 7, 1):
        remind_date = credential.expiry_date - timedelta(days=days_before)
        remind_at = datetime.combine(remind_date, time(9, 0), tzinfo=timezone.utc)
        if remind_at > datetime.now(timezone.utc):
            session.add(
                CredentialReminderJob(
                    credential_id=credential.id,
                    days_before=days_before,
                    remind_at=remind_at,
                    status="pending",
                )
            )
            session.add(
                CredentialOutbox(
                    credential_id=credential.id,
                    kind="expiry_reminder",
                    status="pending",
                    attempts=0,
                    available_at=remind_at,
                    payload_json={"days_before": days_before},
                    idempotency_key=f"{credential.id}:{days_before}",
                )
            )


@router.get("/credentials")
def list_credentials(
    page: int = 1,
    page_size: int = 20,
    status_filter: str | None = None,
    actor: ActorContext = Depends(_require_student),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    if page < 1 or not 1 <= page_size <= 50:
        raise _error(422, "invalid_pagination", "Invalid pagination")
    query = select(Credential).where(
        Credential.owner_user_id == actor.user_id,
        Credential.deleted_at.is_(None),
    )
    if status_filter:
        if status_filter not in {
            "self_declared",
            "pending_verification",
            "verified",
            "expired",
            "revoked",
        }:
            raise _error(
                422,
                "unsupported_status",
                "Unsupported credential status",
                field="status_filter",
            )
        query = query.where(Credential.status == status_filter)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(
        query.order_by(Credential.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [_credential_payload(session, row) for row in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get("/credential-issuers")
def list_credential_issuers(
    actor: ActorContext = Depends(_require_student),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    from app.models.credentials import CredentialIssuer

    rows = session.scalars(
        select(CredentialIssuer)
        .where(
            CredentialIssuer.active.is_(True),
            CredentialIssuer.deleted_at.is_(None),
        )
        .order_by(CredentialIssuer.display_name)
    ).all()
    return {
        "items": [
            {
                "id": str(item.id),
                "display_name": item.display_name,
                "issuer_type": item.issuer_type,
            }
            for item in rows
        ]
    }


@router.post("/credentials", status_code=status.HTTP_201_CREATED, openapi_extra=required_idempotency_header())
def create_credential(
    payload: CredentialCreate,
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", include_in_schema=False)] = None,
    actor: ActorContext = Depends(_require_student),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    request_now = datetime.now(timezone.utc)
    idem = _idempotency(idempotency_key)
    existing = session.scalar(
        select(Credential).where(
            Credential.owner_user_id == actor.user_id,
            Credential.idempotency_key == idem,
        ).with_for_update()
    )
    _require_presented_effect_session(
        session, request, actor, now=request_now
    )
    if existing:
        return _credential_payload(session, existing)
    if payload.issuer_id:
        from app.models.credentials import CredentialIssuer

        issuer = session.get(CredentialIssuer, payload.issuer_id)
        if not issuer or not issuer.active or issuer.deleted_at is not None:
            raise _error(422, "issuer_not_found", "Issuer not found", field="issuer_id")
    identifier_ct = encrypt(payload.identifier) if payload.identifier else None
    row = Credential(
        owner_user_id=actor.user_id,
        issuer_id=payload.issuer_id,
        title=payload.title,
        credential_type=payload.credential_type,
        status="self_declared",
        issue_date=payload.issue_date,
        expiry_date=payload.expiry_date,
        identifier_hash=(
            keyed_hash(payload.identifier, lower=True) if payload.identifier else None
        ),
        identifier_ct=identifier_ct,
        key_version=active_key_version() if identifier_ct else None,
        version=1,
        idempotency_key=idem,
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError as exc:
        failed_constraint = constraint_name(exc)
        session.rollback()
        if failed_constraint == _CREDENTIAL_IDENTIFIER_CONSTRAINT:
            raise _error(
                409,
                "credential_conflict",
                "A credential with this identifier already exists",
            ) from exc
        if failed_constraint != _CREDENTIAL_IDEMPOTENCY_CONSTRAINT:
            raise
        replay_id = session.scalar(
            select(Credential.id).where(
                Credential.owner_user_id == actor.user_id,
                Credential.idempotency_key == idem,
            )
        )
        if replay_id is None:
            raise exc
        replay = session.scalar(
            select(Credential)
            .where(
                Credential.id == replay_id,
                Credential.owner_user_id == actor.user_id,
                Credential.idempotency_key == idem,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if replay is None:
            raise exc
        _require_presented_effect_session(
            session, request, actor, now=request_now
        )
        return _credential_payload(session, replay)
    _history(session, row, actor.user_id, None, "self_declared", "created")
    _schedule_reminders(session, row)
    record_audit_event(
        session,
        action="credential.created",
        resource_type="credential",
        resource_id=row.id,
        actor_user_id=actor.user_id,
        actor_role="student",
        after_state={"status": row.status, "credential_type": row.credential_type},
    )
    session.commit()
    return _credential_payload(session, row)


@router.get("/credentials/{credential_id}")
def get_credential(
    credential_id: uuid.UUID,
    actor: ActorContext = Depends(_require_student),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return _credential_payload(
        session, _get_owned(session, credential_id, actor.user_id)
    )


@router.patch("/credentials/{credential_id}")
def update_credential(
    credential_id: uuid.UUID,
    payload: CredentialPatch,
    request: Request,
    actor: ActorContext = Depends(_require_student),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    request_now = datetime.now(timezone.utc)
    row = _get_owned(
        session, credential_id, actor.user_id, for_update=True
    )
    _require_presented_effect_session(
        session, request, actor, now=request_now
    )
    if row.status in {"verified", "revoked"}:
        raise _error(
            409,
            "credential_immutable",
            "Verified or revoked credentials cannot be edited",
        )
    if payload.expected_version != row.version:
        raise _error(
            409,
            "stale_credential_version",
            "Credential was modified by another request",
            current_version=row.version,
        )
    if payload.expiry_date and payload.expiry_date < row.issue_date:
        raise _error(
            422,
            "expiry_before_issue",
            "Expiry date cannot precede issue date",
            field="expiry_date",
        )
    before = {"status": row.status, "version": row.version}
    if payload.title is not None:
        row.title = payload.title
    row.expiry_date = payload.expiry_date
    if payload.identifier is not None:
        if payload.identifier:
            row.identifier_hash = keyed_hash(payload.identifier, lower=True)
            row.identifier_ct = encrypt(payload.identifier)
            row.key_version = active_key_version()
        else:
            row.identifier_hash = None
            row.identifier_ct = None
            row.key_version = None
    row.version += 1
    _schedule_reminders(session, row)
    record_audit_event(
        session,
        action="credential.updated",
        resource_type="credential",
        resource_id=row.id,
        actor_user_id=actor.user_id,
        actor_role="student",
        before_state=before,
        after_state={"status": row.status, "version": row.version},
    )
    session.commit()
    return _credential_payload(session, row)


@router.delete("/credentials/{credential_id}")
def delete_credential(
    credential_id: uuid.UUID,
    request: Request,
    actor: ActorContext = Depends(_require_student),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    row = _get_owned(
        session, credential_id, actor.user_id, for_update=True
    )
    _require_presented_effect_session(session, request, actor, now=now)
    previous = row.status
    row.status = "revoked"
    row.deleted_at = now
    # Erasure removes the reversible identifier and its lookup fingerprint so
    # a user may later add the same real-world credential again. Privacy-safe
    # status/history/audit rows remain for configured retention.
    row.identifier_hash = None
    row.identifier_ct = None
    row.key_version = None
    row.version += 1
    session.execute(
        select(VerificationToken)
        .where(
            VerificationToken.credential_id == row.id,
            VerificationToken.revoked_at.is_(None),
        )
        .with_for_update()
    )
    for token in session.scalars(
        select(VerificationToken).where(
            VerificationToken.credential_id == row.id,
            VerificationToken.revoked_at.is_(None),
        )
    ):
        token.revoked_at = now
    for evidence in session.scalars(
        select(CredentialEvidence).where(
            CredentialEvidence.credential_id == row.id,
            CredentialEvidence.deleted_at.is_(None),
        )
    ):
        evidence.deleted_at = now
        evidence.scan_state = "deleted"
        session.add(
            CredentialOutbox(
                credential_id=row.id,
                evidence_id=evidence.id,
                kind="delete_evidence",
                status="pending",
                attempts=0,
                available_at=now,
                payload_json=None,
                idempotency_key=str(evidence.id),
            )
        )
    _history(session, row, actor.user_id, previous, "revoked", "owner_deleted")
    record_audit_event(
        session,
        action="credential.deleted",
        resource_type="credential",
        resource_id=row.id,
        actor_user_id=actor.user_id,
        actor_role="student",
        before_state={"status": previous},
        after_state={"status": "revoked", "deleted": True},
    )
    session.commit()
    return {"id": str(row.id), "status": "deleted"}


@router.post("/credentials/{credential_id}/evidence")
async def add_evidence(
    credential_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    actor: ActorContext = Depends(_require_student),
    session: Session = Depends(get_session),
    storage: StorageAdapter = Depends(get_credential_storage),
    scanner: EvidenceScanner = Depends(get_evidence_scanner),
) -> dict[str, object]:
    request_now = datetime.now(timezone.utc)
    row = _get_owned(
        session, credential_id, actor.user_id, for_update=True
    )
    _require_presented_effect_session(
        session, request, actor, now=request_now
    )
    if row.status in {"verified", "revoked"}:
        raise _error(
            409, "credential_immutable", "Evidence cannot be changed in this state"
        )
    count = session.scalar(
        select(func.count(CredentialEvidence.id)).where(
            CredentialEvidence.credential_id == row.id,
            CredentialEvidence.deleted_at.is_(None),
        )
    )
    if (count or 0) >= settings.credential_max_evidence_files:
        raise _error(
            422,
            "evidence_file_limit",
            f"A credential accepts at most {settings.credential_max_evidence_files} files",
            max_allowed=settings.credential_max_evidence_files,
        )
    data = await file.read(settings.credential_max_file_bytes + 1)
    try:
        detected_mime = validate_evidence(
            filename=file.filename, declared_mime=file.content_type, data=data
        )
    except ValueError as exc:
        code = str(exc)
        raise _error(422, code, "Evidence file failed validation", field="file") from exc
    digest = hashlib.sha256(data).hexdigest()
    if session.scalar(
        select(CredentialEvidence.id).where(
            CredentialEvidence.credential_id == row.id,
            CredentialEvidence.sha256_digest == digest,
            CredentialEvidence.deleted_at.is_(None),
        )
    ):
        raise _error(
            409, "duplicate_evidence", "This evidence file is already attached"
        )
    try:
        scan_result = scanner.scan(data, detected_mime=detected_mime)
    except EvidenceScanUnavailable:
        scan_result = None
    if scan_result and scan_result.state == "infected":
        raise _error(
            422, "infected_evidence", "Malware was detected; the file was rejected"
        )
    evidence_id = uuid.uuid4()
    # The stored object name is generated and opaque. Derive its suffix from
    # inspected bytes, not the untrusted upload name.
    suffix = {
        "application/pdf": ".pdf",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
    }[detected_mime]
    object_ref = f"credential-evidence/{actor.user_id}/{row.id}/{evidence_id}{suffix}"
    storage.put(object_ref, data, content_type=detected_mime)
    evidence = CredentialEvidence(
        id=evidence_id,
        credential_id=row.id,
        object_ref=object_ref,
        sha256_digest=digest,
        declared_mime=(file.content_type or "").lower(),
        detected_mime=detected_mime,
        size_bytes=len(data),
        scan_state=(scan_result.state if scan_result else "retryable_failure"),
    )
    session.add(evidence)
    session.add(
        CredentialEvidenceScanEvent(
            evidence_id=evidence.id,
            scan_state=evidence.scan_state,
            provider=(
                scan_result.provider
                if scan_result
                else settings.credential_scanner_provider
            ),
            result_code=(
                scan_result.result_code if scan_result else "scanner_unavailable"
            ),
        )
    )
    if scan_result is None:
        session.add(
            CredentialOutbox(
                credential_id=row.id,
                evidence_id=evidence.id,
                kind="scan_evidence",
                status="pending",
                attempts=0,
                available_at=request_now,
                payload_json=None,
                idempotency_key=str(evidence.id),
            )
        )
    else:
        previous = row.status
        row.status = "pending_verification"
        row.version += 1
        _history(
            session,
            row,
            actor.user_id,
            previous,
            row.status,
            "clean_evidence_added",
        )
    try:
        # record_audit_event flushes the whole unit of work. Keep it inside the
        # same exception boundary as commit so a concurrent duplicate digest
        # is always translated to the typed 409 contract and its newly-written
        # object is erased.
        record_audit_event(
            session,
            action="credential.evidence_added",
            resource_type="credential",
            resource_id=row.id,
            actor_user_id=actor.user_id,
            actor_role="student",
            after_state={"scan_state": evidence.scan_state},
        )
        session.commit()
    except IntegrityError as exc:
        storage.delete(object_ref)
        session.rollback()
        raise _error(
            409, "duplicate_evidence", "This evidence file is already attached"
        ) from exc
    except Exception:
        storage.delete(object_ref)
        raise
    return {
        "id": str(evidence.id),
        "scan_state": evidence.scan_state,
        "status": row.status,
        "retryable": evidence.scan_state == "retryable_failure",
    }


@router.post("/credentials/{credential_id}/share-projections", openapi_extra=required_idempotency_header())
def create_share_projection(
    credential_id: uuid.UUID,
    payload: ShareProjectionCreate,
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", include_in_schema=False)] = None,
    actor: ActorContext = Depends(_require_student),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    row = _get_owned_after_sharing_access_lock(
        session,
        credential_id,
        actor,
        request=request,
        now=now,
    )
    idem = _idempotency(idempotency_key)
    existing = session.scalar(
        select(CredentialShareProjection).where(
            CredentialShareProjection.owner_user_id == actor.user_id,
            CredentialShareProjection.idempotency_key == idem,
        )
    )
    if existing:
        return {
            "id": str(existing.id),
            "credential_id": str(existing.credential_id),
            "fields": existing.fields_json,
            "active": existing.active,
        }
    projection = CredentialShareProjection(
        credential_id=row.id,
        owner_user_id=actor.user_id,
        fields_json=payload.fields,
        version=1,
        active=True,
        idempotency_key=idem,
    )
    session.add(projection)
    try:
        session.flush()
    except IntegrityError as exc:
        failed_constraint = constraint_name(exc)
        session.rollback()
        if failed_constraint != _SHARE_IDEMPOTENCY_CONSTRAINT:
            raise
        replay_discovery = session.scalar(
            select(CredentialShareProjection).where(
                CredentialShareProjection.owner_user_id == actor.user_id,
                CredentialShareProjection.idempotency_key == idem,
            )
        )
        if replay_discovery is None:
            raise exc
        _get_owned_after_sharing_access_lock(
            session,
            replay_discovery.credential_id,
            actor,
            request=request,
            now=now,
        )
        replay = session.scalar(
            select(CredentialShareProjection)
            .where(
                CredentialShareProjection.id == replay_discovery.id,
                CredentialShareProjection.owner_user_id == actor.user_id,
                CredentialShareProjection.idempotency_key == idem,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if replay:
            return {
                "id": str(replay.id),
                "credential_id": str(replay.credential_id),
                "fields": replay.fields_json,
                "active": replay.active,
            }
        raise _error(
            409, "share_projection_conflict", "Share projection conflict"
        ) from exc
    record_audit_event(
        session,
        action="credential.share_projection_created",
        resource_type="credential",
        resource_id=row.id,
        actor_user_id=actor.user_id,
        actor_role="student",
        after_state={"fields": payload.fields},
    )
    session.commit()
    return {
        "id": str(projection.id),
        "credential_id": str(row.id),
        "fields": projection.fields_json,
        "active": projection.active,
    }


def _issuer_grant(
    session: Session,
    credential: Credential,
    actor: ActorContext,
    capability: str,
) -> IssuerAuthorisation:
    if credential.issuer_id is None:
        raise _error(
            409,
            "credential_has_no_issuer",
            "A self-declared credential has no verifying issuer",
        )
    grant = session.scalar(
        select(IssuerAuthorisation).where(
            IssuerAuthorisation.issuer_id == credential.issuer_id,
            IssuerAuthorisation.user_id == actor.user_id,
            IssuerAuthorisation.active.is_(True),
            IssuerAuthorisation.deleted_at.is_(None),
        )
    )
    allowed = bool(
        grant
        and (
            (capability == "verify" and grant.can_verify)
            or (capability == "revoke" and grant.can_revoke)
        )
    )
    if not allowed:
        raise _error(
            403,
            "issuer_authorisation_required",
            "An active issuer authorisation is required",
        )
    return grant


@router.post("/issuer/credentials/{credential_id}/verify", openapi_extra=required_idempotency_header())
def verify_credential(
    credential_id: uuid.UUID,
    payload: VerifyCommand,
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", include_in_schema=False)] = None,
    actor: ActorContext = Depends(_require_authenticated),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    request_now = datetime.now(timezone.utc)
    idem = _idempotency(idempotency_key)
    replay = session.scalar(
        select(CredentialVerificationEvent).where(
            CredentialVerificationEvent.actor_user_id == actor.user_id,
            CredentialVerificationEvent.idempotency_key == idem,
        )
    )
    locked_credential_id = replay.credential_id if replay else credential_id
    row = session.scalar(
        select(Credential)
        .where(Credential.id == locked_credential_id)
        .with_for_update()
    )
    if row is None or (not replay and row.deleted_at is not None):
        raise _error(404, "credential_not_found", "Credential not found")
    _require_presented_effect_session(
        session, request, actor, now=request_now
    )
    if replay:
        return {
            "credential_id": str(replay.credential_id),
            "status": replay.resulting_status,
            "idempotent_replay": True,
        }
    # A concurrent request with the same idempotency key may have committed
    # while this request waited for the credential row lock.
    replay = session.scalar(
        select(CredentialVerificationEvent).where(
            CredentialVerificationEvent.actor_user_id == actor.user_id,
            CredentialVerificationEvent.idempotency_key == idem,
        )
    )
    if replay:
        return {
            "credential_id": str(replay.credential_id),
            "status": replay.resulting_status,
            "idempotent_replay": True,
        }
    _issuer_grant(session, row, actor, "verify")
    if payload.expected_version != row.version:
        raise _error(
            409,
            "stale_credential_version",
            "Credential was modified by another request",
            current_version=row.version,
        )
    if row.status != "pending_verification":
        raise _error(
            409,
            "credential_not_pending",
            "Only a pending credential can be verified",
        )
    clean_count = session.scalar(
        select(func.count(CredentialEvidence.id)).where(
            CredentialEvidence.credential_id == row.id,
            CredentialEvidence.scan_state == "clean",
            CredentialEvidence.deleted_at.is_(None),
        )
    )
    if not clean_count:
        raise _error(
            409, "clean_evidence_required", "Clean evidence is required"
        )
    previous = row.status
    row.status = (
        "expired"
        if row.expiry_date is not None and row.expiry_date < date.today()
        else "verified"
    )
    row.version += 1
    event = CredentialVerificationEvent(
        credential_id=row.id,
        issuer_id=row.issuer_id,
        actor_user_id=actor.user_id,
        action="verified",
        idempotency_key=idem,
        resulting_status=row.status,
    )
    session.add(event)
    _history(session, row, actor.user_id, previous, row.status, "issuer_verified")
    record_audit_event(
        session,
        action="credential.verified",
        resource_type="credential",
        resource_id=row.id,
        actor_user_id=actor.user_id,
        actor_role="issuer",
        before_state={"status": previous},
        after_state={"status": row.status},
    )
    session.commit()
    return {
        "credential_id": str(row.id),
        "status": row.status,
        "version": row.version,
        "verification_event_id": str(event.id),
        "idempotent_replay": False,
    }


def _raw_token(projection_id: uuid.UUID, owner_id: uuid.UUID, idem: str) -> str:
    digest = bytes.fromhex(
        keyed_hash(f"credential-share:{projection_id}:{owner_id}:{idem}")
    )
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@router.post("/credentials/{credential_id}/verification-tokens", openapi_extra=required_idempotency_header())
def create_verification_token(
    credential_id: uuid.UUID,
    payload: VerificationTokenCreate,
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", include_in_schema=False)] = None,
    actor: ActorContext = Depends(_require_student),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    request_now = datetime.now(timezone.utc)
    row = _get_owned_after_sharing_access_lock(
        session,
        credential_id,
        actor,
        request=request,
        now=request_now,
    )
    idem = _idempotency(idempotency_key)
    if _effective_status(row) != "verified":
        raise _error(
            409,
            "verified_credential_required",
            "Only a valid verified credential can be shared",
        )
    projection = session.scalar(
        select(CredentialShareProjection).where(
            CredentialShareProjection.id == payload.projection_id,
            CredentialShareProjection.credential_id == row.id,
            CredentialShareProjection.owner_user_id == actor.user_id,
            CredentialShareProjection.active.is_(True),
        )
    )
    if projection is None:
        raise _error(404, "share_projection_not_found", "Share projection not found")
    raw = _raw_token(projection.id, actor.user_id, idem)
    existing = session.scalar(
        select(VerificationToken).where(
            VerificationToken.owner_user_id == actor.user_id,
            VerificationToken.idempotency_key == idem,
        )
    )
    if existing:
        return {
            "id": str(existing.id),
            "token": raw,
            "verification_url": f"{settings.credential_public_base_url.rstrip('/')}/{raw}",
            "expires_at": existing.expires_at.isoformat(),
            "idempotent_replay": True,
        }
    now = request_now
    for prior in session.scalars(
        select(VerificationToken)
        .where(
            VerificationToken.projection_id == projection.id,
            VerificationToken.revoked_at.is_(None),
        )
        .with_for_update()
    ):
        prior.revoked_at = now
    token = VerificationToken(
        projection_id=projection.id,
        credential_id=row.id,
        owner_user_id=actor.user_id,
        token_hash=keyed_hash(raw),
        key_version=active_key_version(),
        expires_at=now + timedelta(days=payload.lifetime_days),
        idempotency_key=idem,
    )
    session.add(token)
    try:
        session.flush()
    except IntegrityError as exc:
        failed_constraint = constraint_name(exc)
        session.rollback()
        if failed_constraint not in {
            _TOKEN_IDEMPOTENCY_CONSTRAINT,
            _TOKEN_HASH_CONSTRAINT,
        }:
            raise
        replay_discovery = session.scalar(
            select(VerificationToken).where(
                VerificationToken.owner_user_id == actor.user_id,
                VerificationToken.idempotency_key == idem,
            )
        )
        if replay_discovery is None:
            raise exc
        _get_owned_after_sharing_access_lock(
            session,
            replay_discovery.credential_id,
            actor,
            request=request,
            now=request_now,
        )
        replay = session.scalar(
            select(VerificationToken)
            .where(
                VerificationToken.id == replay_discovery.id,
                VerificationToken.owner_user_id == actor.user_id,
                VerificationToken.idempotency_key == idem,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if replay:
            replay_raw = _raw_token(
                replay.projection_id, actor.user_id, idem
            )
            if keyed_hash(replay_raw) != replay.token_hash:
                raise exc
            return {
                "id": str(replay.id),
                "token": replay_raw,
                "verification_url": (
                    f"{settings.credential_public_base_url.rstrip('/')}/{replay_raw}"
                ),
                "expires_at": replay.expires_at.isoformat(),
                "idempotent_replay": True,
            }
        raise _error(
            409, "verification_token_conflict", "Verification token conflict"
        ) from exc
    record_audit_event(
        session,
        action="credential.verification_token_created",
        resource_type="credential",
        resource_id=row.id,
        actor_user_id=actor.user_id,
        actor_role="student",
        after_state={
            "projection_id": str(projection.id),
            "expires_at": token.expires_at.isoformat(),
        },
    )
    session.commit()
    return {
        "id": str(token.id),
        "token": raw,
        "verification_url": f"{settings.credential_public_base_url.rstrip('/')}/{raw}",
        "expires_at": token.expires_at.isoformat(),
        "idempotent_replay": False,
    }


@router.delete("/credentials/{credential_id}/verification-tokens/{token_id}")
def revoke_verification_token(
    credential_id: uuid.UUID,
    token_id: uuid.UUID,
    request: Request,
    actor: ActorContext = Depends(_require_student),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    request_now = datetime.now(timezone.utc)
    _get_owned(
        session, credential_id, actor.user_id, for_update=True
    )
    token = session.scalar(
        select(VerificationToken).where(
            VerificationToken.id == token_id,
            VerificationToken.credential_id == credential_id,
            VerificationToken.owner_user_id == actor.user_id,
        ).with_for_update()
    )
    _require_presented_effect_session(
        session, request, actor, now=request_now
    )
    if token is None:
        raise _error(404, "verification_token_not_found", "Token not found")
    if token.revoked_at is None:
        token.revoked_at = request_now
        record_audit_event(
            session,
            action="credential.verification_token_revoked",
            resource_type="credential",
            resource_id=credential_id,
            actor_user_id=actor.user_id,
            actor_role="student",
            after_state={"token_id": str(token.id), "revoked": True},
        )
    session.commit()
    return {"id": str(token.id), "status": "revoked"}


def _public_bucket(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    source = forwarded or (request.client.host if request.client else "unknown")
    return keyed_hash(f"public-verification-bucket:{source}")


def _log_access(
    session: Session,
    *,
    token_id: uuid.UUID | None,
    bucket_hash: str,
    outcome: str,
) -> None:
    session.add(
        VerificationAccessLog(
            token_id=token_id, bucket_hash=bucket_hash, outcome=outcome
        )
    )


@router.get("/public/credential-verifications/{token}")
def public_verification(
    token: str,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    bucket = _public_bucket(request)
    minute_ago = datetime.now(timezone.utc) - timedelta(minutes=1)
    recent = session.scalar(
        select(func.count(VerificationAccessLog.id)).where(
            VerificationAccessLog.bucket_hash == bucket,
            VerificationAccessLog.created_at >= minute_ago,
        )
    )
    if (recent or 0) >= settings.credential_public_rate_per_minute:
        _log_access(
            session, token_id=None, bucket_hash=bucket, outcome="rate_limited"
        )
        session.commit()
        raise _error(429, "rate_limit_exceeded", "Too many verification requests")
    if not _TOKEN_RE.fullmatch(token):
        _log_access(session, token_id=None, bucket_hash=bucket, outcome="invalid")
        session.commit()
        raise _error(
            404, "verification_not_found", "Verification record not found"
        )
    token_row = session.scalar(
        select(VerificationToken).where(
            VerificationToken.token_hash == keyed_hash(token)
        )
    )
    if token_row is None:
        _log_access(session, token_id=None, bucket_hash=bucket, outcome="invalid")
        session.commit()
        raise _error(
            404, "verification_not_found", "Verification record not found"
        )
    now = datetime.now(timezone.utc)
    if token_row.revoked_at is not None:
        _log_access(
            session, token_id=token_row.id, bucket_hash=bucket, outcome="revoked"
        )
        session.commit()
        raise _error(410, "verification_revoked", "Verification link was revoked")
    if _as_utc(token_row.expires_at) <= now:
        _log_access(
            session, token_id=token_row.id, bucket_hash=bucket, outcome="expired"
        )
        session.commit()
        raise _error(410, "verification_expired", "Verification link expired")
    projection = session.get(CredentialShareProjection, token_row.projection_id)
    credential = session.get(Credential, token_row.credential_id)
    if (
        projection is None
        or credential is None
        or not projection.active
        or credential.deleted_at is not None
    ):
        _log_access(
            session, token_id=token_row.id, bucket_hash=bucket, outcome="invalid"
        )
        session.commit()
        raise _error(
            404, "verification_not_found", "Verification record not found"
        )
    result: dict[str, object] = {}
    effective = _effective_status(credential)
    latest_verified = session.scalar(
        select(CredentialVerificationEvent)
        .where(
            CredentialVerificationEvent.credential_id == credential.id,
            CredentialVerificationEvent.action == "verified",
        )
        .order_by(CredentialVerificationEvent.created_at.desc())
    )
    registration = None
    if "student_name" in projection.fields_json:
        registration = session.scalar(
            select(StudentRegistration).where(
                StudentRegistration.user_id == credential.owner_user_id,
                StudentRegistration.deleted_at.is_(None),
            )
        )
    values: dict[str, object] = {
        "title": credential.title,
        "credential_type": credential.credential_type,
        "status": effective,
        "issue_date": credential.issue_date.isoformat(),
        "expiry_date": (
            credential.expiry_date.isoformat() if credential.expiry_date else None
        ),
        "issuer_display_name": _issuer_name(session, credential),
        "verification_timestamp": (
            latest_verified.created_at.isoformat() if latest_verified else None
        ),
        "student_name": (
            " ".join(
                part
                for part in (
                    registration.first_name if registration else None,
                    registration.middle_name if registration else None,
                    registration.last_name if registration else None,
                )
                if part
            )
            or None
        ),
    }
    for field in projection.fields_json:
        result[field] = values[field]
    # Status is always returned so a previously issued URL truthfully reflects
    # later expiry or issuer revocation.
    result["status"] = effective
    _log_access(
        session,
        token_id=token_row.id,
        bucket_hash=bucket,
        outcome=("revoked" if effective == "revoked" else "valid"),
    )
    session.commit()
    return {
        "verification": result,
        "token_expires_at": token_row.expires_at.isoformat(),
    }


@router.post("/issuer/credentials/{credential_id}/revoke", openapi_extra=required_idempotency_header())
def revoke_credential(
    credential_id: uuid.UUID,
    payload: RevokeCommand,
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", include_in_schema=False)] = None,
    actor: ActorContext = Depends(_require_authenticated),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    request_now = datetime.now(timezone.utc)
    idem = _idempotency(idempotency_key)
    replay = session.scalar(
        select(CredentialVerificationEvent).where(
            CredentialVerificationEvent.actor_user_id == actor.user_id,
            CredentialVerificationEvent.idempotency_key == idem,
        )
    )
    locked_credential_id = replay.credential_id if replay else credential_id
    row = session.scalar(
        select(Credential)
        .where(Credential.id == locked_credential_id)
        .with_for_update()
    )
    if row is None or (not replay and row.deleted_at is not None):
        raise _error(404, "credential_not_found", "Credential not found")
    _require_presented_effect_session(
        session, request, actor, now=request_now
    )
    if replay:
        return {
            "credential_id": str(replay.credential_id),
            "status": replay.resulting_status,
            "idempotent_replay": True,
        }
    replay = session.scalar(
        select(CredentialVerificationEvent).where(
            CredentialVerificationEvent.actor_user_id == actor.user_id,
            CredentialVerificationEvent.idempotency_key == idem,
        )
    )
    if replay:
        return {
            "credential_id": str(replay.credential_id),
            "status": replay.resulting_status,
            "idempotent_replay": True,
        }
    if not actor.has_role(Role.ADMIN):
        _issuer_grant(session, row, actor, "revoke")
    if payload.expected_version != row.version:
        raise _error(
            409,
            "stale_credential_version",
            "Credential was modified by another request",
            current_version=row.version,
        )
    if row.status not in {"verified", "expired"}:
        raise _error(
            409,
            "credential_not_revocable",
            "Only a verified or expired credential can be revoked",
        )
    previous = row.status
    row.status = "revoked"
    row.version += 1
    now = request_now
    for token_row in session.scalars(
        select(VerificationToken)
        .where(
            VerificationToken.credential_id == row.id,
            VerificationToken.revoked_at.is_(None),
        )
        .with_for_update()
    ):
        token_row.revoked_at = now
    reason_ct = encrypt(payload.reason)
    session.add(
        CredentialRevocation(
            credential_id=row.id,
            issuer_id=row.issuer_id,
            actor_user_id=actor.user_id,
            reason_ct=reason_ct,
            reason_hash=keyed_hash(payload.reason, lower=True),
            key_version=active_key_version(),
        )
    )
    event = CredentialVerificationEvent(
        credential_id=row.id,
        issuer_id=row.issuer_id,
        actor_user_id=actor.user_id,
        action="revoked",
        idempotency_key=idem,
        resulting_status="revoked",
    )
    session.add(event)
    _history(session, row, actor.user_id, previous, "revoked", "issuer_revoked")
    record_audit_event(
        session,
        action="credential.revoked",
        resource_type="credential",
        resource_id=row.id,
        actor_user_id=actor.user_id,
        actor_role="admin" if actor.has_role(Role.ADMIN) else "issuer",
        before_state={"status": previous},
        after_state={"status": "revoked"},
    )
    session.commit()
    return {
        "credential_id": str(row.id),
        "status": row.status,
        "version": row.version,
        "idempotent_replay": False,
    }


@router.get("/issuer/credentials/{credential_id}/history")
def credential_history(
    credential_id: uuid.UUID,
    actor: ActorContext = Depends(_require_authenticated),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    row = session.scalar(
        select(Credential).where(
            Credential.id == credential_id, Credential.deleted_at.is_(None)
        )
    )
    if row is None:
        raise _error(404, "credential_not_found", "Credential not found")
    if actor.user_id != row.owner_user_id and not actor.has_role(Role.ADMIN):
        _issuer_grant(session, row, actor, "verify")
    rows = session.scalars(
        select(CredentialStatusHistory)
        .where(CredentialStatusHistory.credential_id == row.id)
        .order_by(CredentialStatusHistory.created_at)
    ).all()
    return {
        "credential_id": str(row.id),
        "items": [
            {
                "id": str(item.id),
                "from_status": item.from_status,
                "to_status": item.to_status,
                "reason_code": item.reason_code,
                "created_at": item.created_at.isoformat(),
            }
            for item in rows
        ],
    }
