"""Server-authoritative mentor ceremony and isolated session lifecycle.

No function accepts an actor, profile, invitation, engagement, scope, provider,
or session selector from the wire.  Opaque cookies select keyed server-side
rows and every mutation is bound to a canonical NYAY-9-style idempotency
fingerprint before any authority transition is committed.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import secrets
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, NoReturn

from cryptography.exceptions import InvalidSignature
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import Request, Response
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth_cookies import cookie_secure
from app.core.config import settings
from app.core.crypto import active_key_version, decrypt, encrypt, keyed_hash
from app.core.guardian_authority import has_authoritative_guardian_proof
from app.db.models.audit import AuditEvent
from app.models.mentor_auth import (
    MENTOR_SESSION_TERMINAL_STATES,
    MentorAuthorityStepUp,
    MentorAuditLink,
    MentorBootstrapAttempt,
    MentorCeremony,
    MentorConsent,
    MentorEngagement,
    MentorIdempotencyRecord,
    MentorInvitation,
    MentorProviderResult,
    MentorRateBucket,
    MentorRetentionBlockedGraph,
    MentorSession,
    MentorSubjectConsent,
    TutorProfileOwnershipProof,
)
from app.models.registration import (
    AuthSession,
    GuardianConsent,
    StudentProfile,
    StudentRegistration,
    User,
)
from app.models.wave2 import TutorProfile


BOOTSTRAP_COOKIE = "nyayone_mentor_bootstrap"
CEREMONY_COOKIE = "nyayone_mentor_ceremony"
SESSION_COOKIE = "nyayone_mentor_session"
STEP_UP_COOKIE = "nyayone_mentor_authority_step_up"
MENTOR_COOKIE_PATH = "/api/v1/auth/mentor"
STEP_UP_COOKIE_PATH = "/api/v1/auth/mentor/authority"
SCHEMA_VERSION = "mentor-ceremony.v1"
_IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9._~-]{16,200}")
_DISCLOSURE_TO_SLICE = {
    "display_identity": "display_name",
    "preferred_language": "preferred_language",
    "city": "city",
    "education_context": "college",
    "interests": "interests",
    "goals": "goals",
}
_PURPOSE_SCOPES = {
    "student_guidance": ("engagement:read", "engagement:respond", "profile-slice:read", "consent:read", "session:rotate", "session:end"),
    "legal_education": ("engagement:read", "engagement:respond", "profile-slice:read", "consent:read", "session:rotate", "session:end"),
    "document_review": ("engagement:read", "engagement:respond", "consent:read", "session:rotate", "session:end"),
    "case_discussion": ("engagement:read", "engagement:respond", "consent:read", "session:rotate", "session:end"),
}
_PURPOSE_POLICY_VERSION = "mentor-purpose-policy.v1"
_PURPOSE_POLICIES = {
    "student_guidance": {
        "roles": frozenset({"tutor", "lawyer_tutor"}),
        "disclosures": frozenset(
            {
                "display_identity",
                "preferred_language",
                "city",
                "education_context",
                "interests",
                "goals",
            }
        ),
        "consent_version": "mentor-consent.v1",
        "acceptance_version": "mentor-acceptance.v1",
    },
    "legal_education": {
        "roles": frozenset({"lawyer_tutor"}),
        "disclosures": frozenset(
            {
                "display_identity",
                "preferred_language",
                "city",
                "education_context",
            }
        ),
        "consent_version": "mentor-consent.v1",
        "acceptance_version": "mentor-acceptance.v1",
    },
    "document_review": {
        "roles": frozenset({"lawyer_tutor"}),
        "disclosures": frozenset(),
        "consent_version": "mentor-consent.v1",
        "acceptance_version": "mentor-acceptance.v1",
    },
    "case_discussion": {
        "roles": frozenset({"lawyer_tutor"}),
        "disclosures": frozenset({"display_identity", "preferred_language"}),
        "consent_version": "mentor-consent.v1",
        "acceptance_version": "mentor-acceptance.v1",
    },
}
_PROOF_POLICIES = {
    "tutor": frozenset(
        {
            ("nyayone_reviewed_identity", "high", "mentor-proof.v1"),
            ("approved_federated_attestation", "high", "mentor-proof.v1"),
        }
    ),
    "lawyer_tutor": frozenset(
        {
            ("nyayone_reviewed_identity", "high", "mentor-proof.v1"),
            ("approved_federated_attestation", "high", "mentor-proof.v1"),
        }
    ),
}
_PROVIDER_RESULT_FIELDS = frozenset(
    {
        "providerClass",
        "assuranceClass",
        "policyVersion",
        "issuer",
        "audience",
        "algorithm",
        "nonce",
        "correlation",
        "providerSubject",
        "accountBindingClass",
        "userPresenceApproved",
        "evidenceDigest",
        "issuedAt",
        "expiresAt",
    }
)
_RETENTION_GUARD = threading.Lock()
_SUBJECT_ERASURE_BOUNDARY_GUARD = object()
_SUBJECT_ERASURE_APPROVAL_GUARD = object()
_SUBJECT_ERASURE_STATE_KEY = "nyay22_subject_erasure_boundaries"
SUBJECT_GRAPH_HARD_CAP = 256


@dataclass(frozen=True)
class SubjectMentorErasureBoundary:
    """Opaque, transaction-bound proof of a closed prelock inventory."""

    registration_id: uuid.UUID
    subject_user_id: uuid.UUID
    registration_updated_at: datetime
    authority_domains: tuple[str, ...]
    actor_ids: tuple[uuid.UUID, ...]
    policy_digest: str
    inventory_digest: str
    current: datetime
    _nonce: str
    _guard: object


@dataclass(frozen=True)
class SubjectMentorErasureApproval:
    """One-shot approval issued only after a cutoff-bound zero-link proof."""

    registration_id: uuid.UUID
    policy_digest: str
    inventory_digest: str
    zero_link_digest: str
    _nonce: str
    _guard: object


def _subject_erasure_state(db: Session) -> dict[str, dict[str, Any]]:
    return db.info.setdefault(_SUBJECT_ERASURE_STATE_KEY, {})


def _retention_policy_digest() -> str:
    payload = {
        "terminalRetentionSeconds": settings.mentor_terminal_retention_seconds,
        "auditLinkRetentionSeconds": settings.mentor_audit_link_retention_seconds,
        "hardGraphCap": SUBJECT_GRAPH_HARD_CAP,
        "mode": settings.mentor_retention_mode,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _boundary_inventory_digest(
    *,
    registration_id: uuid.UUID,
    subject_user_id: uuid.UUID,
    registration_updated_at: datetime,
    authority_domains: tuple[str, ...],
    actor_ids: tuple[uuid.UUID, ...],
    policy_digest: str,
    current: datetime,
) -> str:
    payload = {
        "registration": str(registration_id),
        "subject": str(subject_user_id),
        "registrationUpdatedAt": _utc(registration_updated_at).isoformat(),
        "authorityDomains": list(authority_domains),
        "actors": [str(value) for value in actor_ids],
        "policyDigest": policy_digest,
        "current": _utc(current).isoformat(),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def validate_subject_mentor_erasure_boundary(
    db: Session,
    boundary: SubjectMentorErasureBoundary,
    registration_id: uuid.UUID,
) -> None:
    """Reject missing, stale, cross-session or already-consumed prelocks."""

    state = db.info.setdefault(_SUBJECT_ERASURE_STATE_KEY, {}).get(
        getattr(boundary, "_nonce", "")
    )
    if (
        not isinstance(boundary, SubjectMentorErasureBoundary)
        or boundary._guard is not _SUBJECT_ERASURE_BOUNDARY_GUARD
        or boundary.registration_id != registration_id
        or state is None
        or state.get("boundary") is not boundary
        or state.get("transaction") is not db.get_transaction()
        or state.get("consumed") is not False
        or state.get("phase") != "prelocked"
        or boundary.policy_digest != _retention_policy_digest()
    ):
        raise RuntimeError("mentor erasure boundary was not prelocked")


def consume_subject_mentor_erasure_approval(
    db: Session,
    approval: SubjectMentorErasureApproval,
    registration_id: uuid.UUID,
) -> None:
    """Consume an approval exactly once in its issuing Session transaction."""

    state = db.info.setdefault(_SUBJECT_ERASURE_STATE_KEY, {}).get(
        getattr(approval, "_nonce", "")
    )
    if (
        not isinstance(approval, SubjectMentorErasureApproval)
        or approval._guard is not _SUBJECT_ERASURE_APPROVAL_GUARD
        or approval.registration_id != registration_id
        or state is None
        or state.get("approval") is not approval
        or state.get("transaction") is not db.get_transaction()
        or state.get("consumed") is not False
        or state.get("phase") != "approved"
        or approval.policy_digest != _retention_policy_digest()
        or not approval.zero_link_digest
    ):
        raise RuntimeError("mentor erasure approval is invalid")
    state["consumed"] = True
    state["phase"] = "consumed"
_PG_AUTHORITY_LOCK_TIMEOUT_MS = 5_000
_PG_AUTHORITY_STATEMENT_TIMEOUT_MS = 15_000


class MentorCeremonyError(RuntimeError):
    """Stable public failure carrying no request or authority value."""

    def __init__(
        self,
        status_code: int,
        code: str,
        *,
        retryable: bool = False,
        field: str | None = None,
        retry_after_seconds: int | None = None,
        clear_cookie: tuple[str, str, str] | None = None,
    ) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.retryable = retryable
        self.field = field
        self.retry_after_seconds = retry_after_seconds
        self.clear_cookie = clear_cookie

    def payload(self) -> dict[str, Any]:
        detail: dict[str, Any] = {
            "code": self.code,
            "message": "Request failed",
            "retryable": self.retryable,
        }
        if self.field is not None:
            detail["field"] = self.field
        if self.retry_after_seconds is not None:
            detail["retryAfterSeconds"] = self.retry_after_seconds
        return {"detail": detail}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _body(body: Any) -> dict[str, Any]:
    return (
        body.model_dump(mode="json", by_alias=True)
        if hasattr(body, "model_dump")
        else dict(body)
    )


def _headers(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Cookie"


def _set_cookie(response: Response, *, key: str, token: str, max_age: int, path: str, same_site: str) -> None:
    response.set_cookie(
        key=key,
        value=token,
        max_age=max_age,
        path=path,
        secure=cookie_secure(),
        httponly=True,
        samesite=same_site,
    )


def _clear_cookie(response: Response, *, key: str, path: str, same_site: str) -> None:
    response.delete_cookie(
        key=key,
        path=path,
        secure=cookie_secure(),
        httponly=True,
        samesite=same_site,
    )


def _random_token() -> str:
    return secrets.token_urlsafe(32)


def _advisory_key(label: str) -> int:
    raw = int.from_bytes(
        hashlib.sha256(f"nyay22-authority-lock:v1:{label}".encode("ascii")).digest()[:8],
        "big",
        signed=False,
    )
    return raw if raw < 2**63 else raw - 2**64


def _candidate_actor_for_ceremony(
    db: Session, ceremony: MentorCeremony
) -> uuid.UUID | None:
    """Discover a lock key without treating the discovery as authority."""

    if ceremony.actor_user_id is not None:
        return ceremony.actor_user_id
    source = (ceremony.metadata_json or {}).get("mentorSessionId")
    try:
        source_id = uuid.UUID(str(source))
    except (TypeError, ValueError, AttributeError):
        source_id = None
    if source_id is not None:
        actor = db.scalar(
            select(MentorSession.actor_user_id).where(MentorSession.id == source_id)
        )
        if actor is not None:
            return actor
    provider = db.scalar(
        select(MentorProviderResult).where(
            MentorProviderResult.ceremony_id == ceremony.id
        )
    )
    if provider is None or provider.provider_subject_hash is None:
        return None
    candidates = list(
        db.scalars(
            select(TutorProfileOwnershipProof.user_id)
            .where(
                TutorProfileOwnershipProof.provider_class == provider.provider_class,
                TutorProfileOwnershipProof.provider_subject_hash
                == provider.provider_subject_hash,
                TutorProfileOwnershipProof.state == "current",
                TutorProfileOwnershipProof.deleted_at.is_(None),
            )
            .limit(2)
        )
    )
    return candidates[0] if len(candidates) == 1 else None


def _candidate_authority_lock_label(
    db: Session,
    request: Request | None = None,
    *,
    ceremony_id: uuid.UUID | None = None,
    actor_hint: uuid.UUID | None = None,
    fallback: str,
) -> str:
    """Two-phase, DB-derived lock selection; all authority is rechecked later."""

    if actor_hint is not None:
        return f"actor:{actor_hint}"
    if request is not None:
        raw_session = request.cookies.get(SESSION_COOKIE)
        if raw_session:
            actor = db.scalar(
                select(MentorSession.actor_user_id).where(
                    MentorSession.token_hash == _token_hash(raw_session)
                )
            )
            if actor is not None:
                return f"actor:{actor}"
        raw_step_up = request.cookies.get(STEP_UP_COOKIE)
        if raw_step_up:
            actor = db.scalar(
                select(MentorAuthorityStepUp.actor_user_id).where(
                    MentorAuthorityStepUp.token_hash == _token_hash(raw_step_up)
                )
            )
            if actor is not None:
                return f"actor:{actor}"
        raw_ceremony = request.cookies.get(CEREMONY_COOKIE)
        if raw_ceremony:
            presented = _token_hash(raw_ceremony)
            rows = list(
                db.scalars(
                    select(MentorCeremony)
                    .where(
                        or_(
                            MentorCeremony.token_hash == presented,
                            MentorCeremony.predecessor_token_hash == presented,
                        )
                    )
                    .limit(2)
                )
            )
            if len(rows) == 1:
                actor = _candidate_actor_for_ceremony(db, rows[0])
                if actor is not None:
                    return f"actor:{actor}"
                return f"ceremony:{rows[0].id}"
        raw_bootstrap = request.cookies.get(BOOTSTRAP_COOKIE)
        if raw_bootstrap:
            return f"bootstrap:{_token_hash(raw_bootstrap)}"
    if ceremony_id is not None:
        ceremony = db.get(MentorCeremony, ceremony_id)
        if ceremony is not None:
            actor = _candidate_actor_for_ceremony(db, ceremony)
            if actor is not None:
                return f"actor:{actor}"
        return f"ceremony:{ceremony_id}"
    return fallback


def _lock_authority_scope(
    db: Session,
    request: Request | None = None,
    *,
    ceremony_id: uuid.UUID | None = None,
    actor_hint: uuid.UUID | None = None,
    fallback: str,
) -> str:
    """Acquire one keyed transaction lock before any authorizing row lock.

    The candidate is derived only from server rows, then every binding is read
    again under normal row locks.  PostgreSQL bounds acquisition; SQLite's
    single-writer transaction model is used only by local deterministic tests.
    """

    label = _candidate_authority_lock_label(
        db,
        request,
        ceremony_id=ceremony_id,
        actor_hint=actor_hint,
        fallback=fallback,
    )
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        try:
            db.execute(
                text(
                    "SET LOCAL lock_timeout = "
                    f"'{_PG_AUTHORITY_LOCK_TIMEOUT_MS}ms'"
                )
            )
            db.execute(
                text(
                    "SET LOCAL statement_timeout = "
                    f"'{_PG_AUTHORITY_STATEMENT_TIMEOUT_MS}ms'"
                )
            )
            db.execute(select(func.pg_advisory_xact_lock(_advisory_key(label))))
        except Exception:
            db.rollback()
            raise MentorCeremonyError(
                409, "CONCURRENT_STATE_CHANGED", retryable=True
            ) from None
    return label


def _seeded_token(
    kind: str,
    binding: uuid.UUID,
    generation: int,
    seed: str,
) -> str:
    """Bind one CSPRNG seed to an authority row and cookie generation."""

    return keyed_hash(
        f"mentor-issued-token:v2:{kind}:{binding}:g{generation}:{seed}"
    )


def _new_seeded_token(
    kind: str,
    binding: uuid.UUID,
    generation: int = 1,
) -> tuple[str, str, str]:
    """Issue one CSPRNG-rooted bearer and its encrypted replay binding."""

    seed = _random_token()
    ciphertext = encrypt(seed)
    key_version = active_key_version()
    if not ciphertext.startswith(f"{key_version}:"):
        raise MentorCeremonyError(503, "PROVIDER_UNAVAILABLE", retryable=True)
    return (
        _seeded_token(kind, binding, generation, seed),
        ciphertext,
        key_version,
    )


def _reconstruct_seeded_token(
    db: Session,
    *,
    kind: str,
    binding: uuid.UUID,
    generation: int,
) -> str:
    """Reconstruct only the bearer committed for an exact replay.

    The raw seed is never persisted outside its version-stamped ciphertext.
    Missing, erased, malformed, or digest-mismatched bindings fail closed.
    """

    model = {
        "ceremony": MentorCeremony,
        "session": MentorSession,
        "step-up": MentorAuthorityStepUp,
    }.get(kind)
    if model is None:
        raise MentorCeremonyError(410, "AUTHORITY_TERMINAL")
    row = db.get(model, binding)

    seed = _decrypt_token_seed(row)
    token = _seeded_token(kind, binding, generation, seed)
    token_hash = getattr(row, "token_hash", "")
    if not isinstance(token_hash, str) or not secrets.compare_digest(
        _token_hash(token), token_hash
    ):
        raise MentorCeremonyError(410, "AUTHORITY_TERMINAL")
    return token


def _remaining_seeded_authority_lifetime(
    db: Session,
    *,
    kind: str,
    binding: uuid.UUID,
) -> int:
    """Return bounded whole seconds remaining for a replayed cookie."""

    model = {
        "ceremony": MentorCeremony,
        "session": MentorSession,
        "step-up": MentorAuthorityStepUp,
    }.get(kind)
    row = db.get(model, binding) if model is not None else None
    expires_at = getattr(row, "expires_at", None) if row is not None else None
    live_states = {
        "ceremony": {"challenge_issued", "proof_verified"},
        "session": {"active"},
        "step-up": {"active"},
    }
    if (
        not isinstance(expires_at, datetime)
        or getattr(row, "deleted_at", None) is not None
        or getattr(row, "state", None) not in live_states.get(kind, set())
    ):
        raise MentorCeremonyError(410, "AUTHORITY_TERMINAL")
    remaining = int((_utc(expires_at) - _now()).total_seconds())
    if kind == "session":
        last_seen_at = getattr(row, "last_seen_at", None)
        if not isinstance(last_seen_at, datetime):
            raise MentorCeremonyError(410, "AUTHORITY_TERMINAL")
        idle_remaining = int(
            (
                _utc(last_seen_at)
                + timedelta(seconds=settings.mentor_session_idle_ttl_seconds)
                - _now()
            ).total_seconds()
        )
        remaining = min(remaining, idle_remaining)
    if remaining < 1:
        raise MentorCeremonyError(410, "AUTHORITY_TERMINAL")
    return remaining


def _session_expiry_boundary(session: MentorSession) -> datetime:
    """Return the immutable earliest absolute/idle authority deadline."""

    return min(
        _utc(session.expires_at),
        _utc(session.last_seen_at)
        + timedelta(seconds=settings.mentor_session_idle_ttl_seconds),
    )


def _decrypt_token_seed(row: Any) -> str:
    """Open one version-bound authority seed or fail without diagnostics."""

    ciphertext = getattr(row, "token_seed_ct", None) if row is not None else None
    key_version = (
        getattr(row, "token_seed_key_version", None) if row is not None else None
    )
    if (
        not isinstance(ciphertext, str)
        or not isinstance(key_version, str)
        or not ciphertext.startswith(f"{key_version}:")
    ):
        raise MentorCeremonyError(410, "AUTHORITY_TERMINAL")
    try:
        return decrypt(ciphertext)
    except Exception:
        raise MentorCeremonyError(410, "AUTHORITY_TERMINAL") from None


def _provider_policy(role: str) -> tuple[str, str, str]:
    configured = (
        settings.mentor_identity_provider_class,
        settings.mentor_identity_provider_assurance,
        settings.mentor_identity_provider_policy_version,
    )
    if configured not in _PROOF_POLICIES.get(role, frozenset()):
        raise MentorCeremonyError(503, "PROVIDER_UNAVAILABLE", retryable=True)
    return configured


def _provider_result_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _parse_provider_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise MentorCeremonyError(403, "AUTHORIZATION_DENIED")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise MentorCeremonyError(403, "AUTHORIZATION_DENIED") from None
    if parsed.tzinfo is None:
        raise MentorCeremonyError(403, "AUTHORIZATION_DENIED")
    return parsed.astimezone(timezone.utc)


def _token_hash(token: str) -> str:
    return keyed_hash(f"mentor-cookie:v1:{token}")


def _fingerprint(operation: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return keyed_hash(f"mentor-request:v1:{operation}:{canonical}")


def _require_idempotency_key(value: str | None) -> str:
    if not isinstance(value, str) or _IDEMPOTENCY_KEY.fullmatch(value) is None:
        raise MentorCeremonyError(400, "INVALID_IDEMPOTENCY_KEY", field="Idempotency-Key")
    return value


def _scope_hash(operation: str, binding: str, payload: dict[str, Any]) -> str:
    # The uniqueness namespace is exclusively server-derived.  Client fields
    # belong in ``request_fingerprint``; including them here would let a caller
    # reuse one key with a changed purpose/intent and create a second ledger row
    # instead of receiving the required IDEMPOTENCY_CONFLICT.
    del payload
    return keyed_hash(f"mentor-scope:v1:{operation}:{binding}")


def _begin_idempotency(
    db: Session,
    *,
    operation: str,
    binding: str,
    idempotency_key: str | None,
    payload: dict[str, Any],
) -> tuple[MentorIdempotencyRecord, tuple[int, dict[str, Any]] | None]:
    raw_key = _require_idempotency_key(idempotency_key)
    scope_hash = _scope_hash(operation, binding, payload)
    key_hash = keyed_hash(f"mentor-idempotency-key:v1:{raw_key}")
    request_fingerprint = _fingerprint(operation, payload)
    record = db.scalar(
        select(MentorIdempotencyRecord)
        .where(
            MentorIdempotencyRecord.scope_hash == scope_hash,
            MentorIdempotencyRecord.operation == operation,
            MentorIdempotencyRecord.idempotency_key_hash == key_hash,
        )
        .with_for_update()
    )
    if record is not None:
        if record.request_fingerprint != request_fingerprint:
            raise MentorCeremonyError(409, "IDEMPOTENCY_CONFLICT")
        if record.state in {"succeeded", "failed"} and record.outcome_ct is not None and record.outcome_status is not None:
            return record, (int(record.outcome_status), json.loads(decrypt(record.outcome_ct)))
        if record.state == "pending":
            raise MentorCeremonyError(409, "CONCURRENT_STATE_CHANGED", retryable=True)
        raise MentorCeremonyError(410, "AUTHORITY_TERMINAL")
    record = MentorIdempotencyRecord(
        scope_hash=scope_hash,
        operation=operation,
        idempotency_key_hash=key_hash,
        request_fingerprint=request_fingerprint,
        state="pending",
    )
    db.add(record)
    try:
        db.flush()
    except IntegrityError:
        # PostgreSQL waits on the competing unique-key transaction before
        # raising.  Once it does, discard this failed transaction and reread
        # the committed winner; an exact concurrent retry must replay rather
        # than degrade into a generic conflict.
        db.rollback()
        winner = db.scalar(
            select(MentorIdempotencyRecord)
            .where(
                MentorIdempotencyRecord.scope_hash == scope_hash,
                MentorIdempotencyRecord.operation == operation,
                MentorIdempotencyRecord.idempotency_key_hash == key_hash,
            )
            .with_for_update()
        )
        if winner is None:
            raise MentorCeremonyError(
                409, "CONCURRENT_STATE_CHANGED", retryable=True
            ) from None
        if winner.request_fingerprint != request_fingerprint:
            raise MentorCeremonyError(409, "IDEMPOTENCY_CONFLICT") from None
        if (
            winner.state in {"succeeded", "failed"}
            and winner.outcome_ct is not None
            and winner.outcome_status is not None
        ):
            return winner, (
                int(winner.outcome_status),
                json.loads(decrypt(winner.outcome_ct)),
            )
        raise MentorCeremonyError(
            409, "CONCURRENT_STATE_CHANGED", retryable=True
        ) from None
    return record, None


def _existing_idempotency(
    db: Session,
    *,
    operation: str,
    bindings: list[str],
    idempotency_key: str | None,
    payload: dict[str, Any],
) -> tuple[MentorIdempotencyRecord, tuple[int, dict[str, Any]]] | None:
    """Resolve an exact retry through a server-related predecessor binding.

    Cookie rotation advances the presented session row.  A lost response may
    therefore retry while presenting the successor, but the durable operation
    remains scoped to its predecessor generation.  Only server-derived graph
    relations enter ``bindings``; request fields never choose a namespace.
    """

    raw_key = _require_idempotency_key(idempotency_key)
    key_hash = keyed_hash(f"mentor-idempotency-key:v1:{raw_key}")
    request_fingerprint = _fingerprint(operation, payload)
    scope_hashes = [_scope_hash(operation, binding, payload) for binding in bindings]
    rows = list(
        db.scalars(
            select(MentorIdempotencyRecord)
            .where(
                MentorIdempotencyRecord.scope_hash.in_(scope_hashes),
                MentorIdempotencyRecord.operation == operation,
                MentorIdempotencyRecord.idempotency_key_hash == key_hash,
            )
            .order_by(MentorIdempotencyRecord.id)
            .with_for_update()
        )
    )
    if not rows:
        return None
    if len(rows) != 1 or rows[0].request_fingerprint != request_fingerprint:
        raise MentorCeremonyError(409, "IDEMPOTENCY_CONFLICT")
    record = rows[0]
    if (
        record.state not in {"succeeded", "failed"}
        or record.outcome_ct is None
        or record.outcome_status is None
    ):
        raise MentorCeremonyError(409, "CONCURRENT_STATE_CHANGED", retryable=True)
    return record, (
        int(record.outcome_status),
        json.loads(decrypt(record.outcome_ct)),
    )


def _seal_idempotency(
    record: MentorIdempotencyRecord,
    status: int,
    payload: dict[str, Any],
    *,
    cookie_effects: list[dict[str, Any]] | None = None,
) -> None:
    record.state = "succeeded" if status < 400 else "failed"
    record.outcome_status = status
    record.key_version = active_key_version()
    sealed_payload = dict(payload)
    if cookie_effects:
        sealed_payload["__nyayoneCookieEffects"] = cookie_effects
    record.outcome_ct = encrypt(
        json.dumps(sealed_payload, sort_keys=True, separators=(",", ":"))
    )


def _replay(
    db: Session,
    response: Response,
    replay: tuple[int, dict[str, Any]],
    *,
    apply_cookie_effects: bool = True,
) -> dict[str, Any]:
    response.status_code = replay[0]
    payload = dict(replay[1])
    effects = payload.pop("__nyayoneCookieEffects", [])
    for effect in effects if apply_cookie_effects and isinstance(effects, list) else []:
        if not isinstance(effect, dict):
            continue
        if effect.get("action") == "clear":
            _clear_cookie(
                response,
                key=str(effect["key"]),
                path=str(effect["path"]),
                same_site=str(effect["sameSite"]),
            )
        elif effect.get("action") == "set":
            binding = uuid.UUID(str(effect["binding"]))
            kind = str(effect["kind"])
            _validate_replayed_authority(db, kind=kind, binding=binding)
            token = _reconstruct_seeded_token(
                db,
                kind=kind,
                binding=binding,
                generation=int(effect.get("generation", 1)),
            )
            remaining = _remaining_seeded_authority_lifetime(
                db,
                kind=kind,
                binding=binding,
            )
            _set_cookie(
                response,
                key=str(effect["key"]),
                token=token,
                max_age=min(int(effect["maxAge"]), remaining),
                path=str(effect["path"]),
                same_site=str(effect["sameSite"]),
            )
    _headers(response)
    return payload


def _validate_replayed_authority(
    db: Session,
    *,
    kind: str,
    binding: uuid.UUID,
) -> None:
    """Recheck the complete server graph before reissuing any authority.

    An encrypted idempotency outcome proves a prior commit, not present
    authorization.  Consent/proof/profile restrictions that won after that
    commit must therefore suppress every later cookie replay.
    """

    now = _now()
    if kind == "ceremony":
        ceremony = _locked_row(db, MentorCeremony, binding)
        if ceremony is None:
            raise MentorCeremonyError(410, "AUTHORITY_TERMINAL")
        if ceremony.state == "challenge_issued":
            # This is a non-authorizing bootstrap/recovery continuation.
            return
        if ceremony.state != "proof_verified":
            raise MentorCeremonyError(410, "AUTHORITY_TERMINAL")
        _user, _profile, _proof = _current_proof(db, ceremony, now)
        if ceremony.intent == "mentor_session":
            invitation = _locked_row(db, MentorInvitation, ceremony.invitation_id)
            if invitation is None:
                raise MentorCeremonyError(403, "AUTHORIZATION_DENIED")
            _validate_invitation_consent(db, invitation, now)
            if not _subject_registration_sharing_allowed(
                db, invitation.subject_registration_id
            ):
                raise MentorCeremonyError(403, "AUTHORIZATION_DENIED")
        return
    if kind == "session":
        session = _locked_row(db, MentorSession, binding)
        if session is None or session.state != "active":
            raise MentorCeremonyError(410, "AUTHORITY_TERMINAL")
        if (
            _utc(session.expires_at) <= now
            or _utc(session.last_seen_at)
            + timedelta(seconds=settings.mentor_session_idle_ttl_seconds)
            <= now
        ):
            session.state = "expired"
            session.terminal_at = _session_expiry_boundary(session)
            _audit(
                db,
                action="mentor.session.expired",
                state="expired",
                generation=session.generation,
                actor_user_id=session.actor_user_id,
                authority_domain_hash=session.authority_domain_hash,
                purpose_code=session.purpose_code,
            )
            db.commit()
            raise MentorCeremonyError(410, "SESSION_EXPIRED")
        engagement, _consent, _proof, _profile = _validate_live_session_graph(
            db, session, now
        )
        if not _subject_sharing_allowed(db, engagement):
            raise MentorCeremonyError(403, "AUTHORIZATION_DENIED")
        return
    if kind == "step-up":
        step_up = _locked_row(db, MentorAuthorityStepUp, binding)
        if (
            step_up is None
            or step_up.state != "active"
            or _utc(step_up.expires_at) <= now
        ):
            raise MentorCeremonyError(410, "STEP_UP_EXPIRED")
        session = _locked_row(db, MentorSession, step_up.mentor_session_id)
        if session is None or session.state != "active":
            raise MentorCeremonyError(410, "AUTHORITY_TERMINAL")
        engagement, _consent, _proof, _profile = _validate_live_session_graph(
            db, session, now
        )
        expected = _fingerprint(
            "delete-authority",
            {
                "actor": str(session.actor_user_id),
                "sessionGeneration": session.generation,
                "retentionNoticeVersion": settings.mentor_retention_notice_version,
            },
        )
        if (
            step_up.actor_user_id != session.actor_user_id
            or step_up.fingerprint != expected
            or not _subject_sharing_allowed(db, engagement)
        ):
            raise MentorCeremonyError(403, "AUTHORIZATION_DENIED")
        return
    raise MentorCeremonyError(410, "AUTHORITY_TERMINAL")


def _audit(
    db: Session,
    *,
    action: str,
    state: str,
    generation: int | None = None,
    actor_user_id: uuid.UUID | None = None,
    authority_domain_hash: str | None = None,
    purpose_code: str | None = None,
    policy_version: str | None = None,
    subject_consent_version: str | None = None,
    mentor_consent_version: str | None = None,
) -> AuditEvent:
    """Append one PII-free event and, when needed, a separately erasable link."""

    after: dict[str, Any] = {"outcome": state}
    if generation is not None:
        after["generation"] = generation
    if purpose_code is not None:
        after["purpose_code"] = purpose_code
    if policy_version is not None:
        after["policy_version"] = policy_version
    if subject_consent_version is not None:
        after["subject_consent_version"] = subject_consent_version
    if mentor_consent_version is not None:
        after["mentor_consent_version"] = mentor_consent_version
    if authority_domain_hash is not None:
        after["correlation_digest"] = keyed_hash(
            f"mentor-audit-correlation:v1:{authority_domain_hash}:{action}:{generation or 0}"
        )
    event = AuditEvent(
        actor_user_id=None,
        actor_role="mentor",
        action=action,
        resource_type="mentor_authority",
        resource_id=None,
        after_state=after,
    )
    db.add(event)
    db.flush()
    if actor_user_id is not None and authority_domain_hash is not None:
        per_subject_key = Fernet.generate_key()
        db.add(
            MentorAuditLink(
                audit_event_id=event.id,
                correlation_hash=keyed_hash(
                    f"mentor-audit-link:v1:{authority_domain_hash}"
                ),
                link_key_ct=encrypt(per_subject_key.decode("ascii")),
                actor_link_ct=Fernet(per_subject_key)
                .encrypt(str(actor_user_id).encode("ascii"))
                .decode("ascii"),
                key_version=active_key_version(),
                expires_at=_now()
                + timedelta(seconds=settings.mentor_audit_link_retention_seconds),
            )
        )
    return event


def _consume_rate_budget(
    db: Session,
    *,
    request: Request,
    operation: str,
    binding: str,
    now: datetime | None = None,
) -> None:
    """Consume one bounded digest-only operation budget atomically."""

    current = _utc(now or _now())
    width = settings.mentor_rate_window_seconds
    started_epoch = int(current.timestamp()) // width * width
    started = datetime.fromtimestamp(started_epoch, tz=timezone.utc)
    # The raw network address and capability binding are never persisted or
    # returned; only a keyed digest enters the rate table.
    host = request.client.host if request.client is not None else "unavailable"
    scope_hash = keyed_hash(
        f"mentor-rate:v1:{operation}:{binding}:{host}"
    )
    row = db.scalar(
        select(MentorRateBucket)
        .where(
            MentorRateBucket.scope_hash == scope_hash,
            MentorRateBucket.operation == operation,
            MentorRateBucket.window_started_at == started,
        )
        .with_for_update()
    )
    if row is None:
        row = MentorRateBucket(
            scope_hash=scope_hash,
            operation=operation,
            window_started_at=started,
            count=1,
            expires_at=started + timedelta(seconds=width * 2),
        )
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise MentorCeremonyError(
                409, "CONCURRENT_STATE_CHANGED", retryable=True
            ) from None
        return
    if row.count >= settings.mentor_rate_max_requests:
        raise MentorCeremonyError(
            429,
            "RATE_LIMITED",
            retryable=True,
            retry_after_seconds=max(
                1, int((_utc(row.expires_at) - current).total_seconds())
            ),
        )
    row.count += 1


def persist_denied_attempt(
    db: Session,
    *,
    request: Request,
    operation: str,
    failure: MentorCeremonyError,
) -> MentorCeremonyError:
    """Persist a bounded denial without committing partial authority writes.

    Every service denial first discards the request transaction.  A fresh
    transaction then records only a digest-scoped abuse counter.  This keeps
    malformed proof/consent attempts durable while making it impossible for a
    route error to accidentally commit a half-issued ceremony or session.
    """

    db.rollback()
    try:
        _consume_rate_budget(
            db,
            request=request,
            operation=operation,
            binding="public-denial",
        )
        db.commit()
    except MentorCeremonyError as limiter:
        db.rollback()
        if limiter.code == "RATE_LIMITED":
            return limiter
    except Exception:
        # Availability of the denial ledger cannot turn a denial into an
        # approval.  Preserve the original generic error and leave no write.
        db.rollback()
    return failure


def _active_student_session(
    db: Session, request: Request
) -> tuple[AuthSession | None, bool]:
    """Lock and return only live owner/student authority present in this browser."""

    raw = request.cookies.get(settings.auth_session_cookie_name)
    if not raw:
        return None, False
    discovered = db.execute(
        select(AuthSession.id, AuthSession.user_id).where(
            AuthSession.token_hash == keyed_hash(raw)
        )
    ).one_or_none()
    if discovered is None or discovered.user_id is None:
        # An unresolvable or already-erased owner cookie is ambiguous, never
        # proof that the conflicting browser authority class is absent.
        raise MentorCeremonyError(409, "SESSION_CONFLICT")

    owner_session_id = discovered.id
    owner_actor_id = discovered.user_id
    actor_ids = {owner_actor_id}
    presented_label = _candidate_authority_lock_label(
        db,
        request,
        fallback="owner-session-conflict",
    )
    if presented_label.startswith("actor:"):
        try:
            actor_ids.add(uuid.UUID(presented_label.removeprefix("actor:")))
        except ValueError:
            raise MentorCeremonyError(409, "SESSION_CONFLICT") from None

    ordered_actor_ids = sorted(actor_ids, key=str)
    for actor_id in ordered_actor_ids:
        _lock_authority_scope(
            db,
            actor_hint=actor_id,
            fallback=f"actor:{actor_id}",
        )
    locked_users = {
        user.id: user
        for user in db.scalars(
            select(User)
            .where(User.id.in_(ordered_actor_ids))
            .order_by(User.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    }
    if owner_actor_id not in locked_users:
        raise MentorCeremonyError(409, "SESSION_CONFLICT")
    locked_sessions = list(
        db.scalars(
            select(AuthSession)
            .where(AuthSession.user_id.in_(ordered_actor_ids))
            .order_by(AuthSession.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    row = next(
        (candidate for candidate in locked_sessions if candidate.id == owner_session_id),
        None,
    )
    now = _now()
    if row is None:
        # A discovery/lock mismatch is a concurrent authority transition.
        raise MentorCeremonyError(409, "SESSION_CONFLICT")
    if row.status != "active":
        return None, False
    if row.user_id != owner_actor_id or row.deleted_at is not None:
        raise MentorCeremonyError(409, "SESSION_CONFLICT")
    if _utc(row.expires_at) <= now:
        row.status = "expired"
        row.revoked_at = row.expires_at
        return None, True
    return row, False


def _reject_conflicting_session_class(db: Session, request: Request) -> bool:
    # Presence of an unresolved, stale or live owner cookie is ambiguous at
    # this boundary.  A resolved terminal/elapsed row carries no authority and
    # is materialized terminal; an unknown digest remains fail closed.
    if request.cookies.get(settings.auth_session_cookie_name) is not None:
        active, materialized_expiry = _active_student_session(db, request)
        if active is not None:
            raise MentorCeremonyError(409, "SESSION_CONFLICT")
        return materialized_expiry
    return False


def _lock_actor_session_classes(
    db: Session,
    actor_user_id: uuid.UUID,
) -> tuple[User, list[AuthSession], list[MentorSession]]:
    """Take the shared issuance order: User -> owner sessions -> mentor sessions."""

    user = db.scalar(
        select(User)
        .where(User.id == actor_user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None:
        raise MentorCeremonyError(403, "AUTHORIZATION_DENIED")
    owner_sessions = list(
        db.scalars(
            select(AuthSession)
            .where(AuthSession.user_id == actor_user_id)
            .order_by(AuthSession.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    mentor_sessions = list(
        db.scalars(
            select(MentorSession)
            .where(MentorSession.actor_user_id == actor_user_id)
            .order_by(MentorSession.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    return user, owner_sessions, mentor_sessions


def _role_is_server_authorized(
    *, user: User, profile: TutorProfile, role: str
) -> bool:
    if (
        user.role != "lawyer"
        or user.status != "active"
        or user.deleted_at is not None
        or profile.status != "active"
        or profile.deleted_at is not None
        or not profile.verified_identity
    ):
        return False
    if role == "lawyer_tutor":
        return bool(profile.verified_credentials)
    return role == "tutor"


def _purpose_policy(
    *,
    role: str,
    purpose: str,
    consent_version: str,
    acceptance_version: str,
    disclosures: list[str],
) -> dict[str, Any]:
    """Resolve one closed, versioned purpose policy without client expansion."""

    policy = _PURPOSE_POLICIES.get(purpose)
    if (
        policy is None
        or role not in policy["roles"]
        or consent_version != policy["consent_version"]
        or acceptance_version != policy["acceptance_version"]
        or not isinstance(disclosures, list)
        or len(disclosures) != len(set(disclosures))
        or set(disclosures) - policy["disclosures"]
    ):
        raise MentorCeremonyError(403, "AUTHORIZATION_DENIED")
    return policy


def _provider_result(
    db: Session, ceremony: MentorCeremony, now: datetime
) -> MentorProviderResult:
    row = db.scalar(
        select(MentorProviderResult)
        .where(MentorProviderResult.ceremony_id == ceremony.id)
        .with_for_update()
    )
    policy = _PROOF_POLICIES.get(ceremony.requested_role or "")
    provenance = (
        row.provider_class,
        row.assurance_class,
        row.policy_version,
    ) if row is not None else None
    if (
        row is None
        or policy is None
        or provenance not in policy
        or row.state != "verified"
        or row.provider_subject_hash is None
        or row.evidence_digest is None
        or row.key_version is None
        or row.issued_at is None
        or row.consumed_at is not None
        or row.deleted_at is not None
        or _utc(row.issued_at) > now
        or _utc(row.expires_at) <= now
    ):
        raise MentorCeremonyError(403, "AUTHORIZATION_DENIED")
    return row


def _derive_current_authority(
    db: Session,
    ceremony: MentorCeremony,
    now: datetime,
) -> tuple[
    User,
    TutorProfile,
    TutorProfileOwnershipProof,
    MentorInvitation | None,
    MentorProviderResult,
]:
    """Reduce a trusted backchannel result to one role/purpose invitation."""

    provider = _provider_result(db, ceremony, now)
    proof_candidates = list(
        db.scalars(
            select(TutorProfileOwnershipProof.id)
            .where(
                TutorProfileOwnershipProof.provider_subject_hash
                == provider.provider_subject_hash,
                TutorProfileOwnershipProof.evidence_digest
                == provider.evidence_digest,
                TutorProfileOwnershipProof.provider_class
                == provider.provider_class,
                TutorProfileOwnershipProof.assurance_class
                == provider.assurance_class,
                TutorProfileOwnershipProof.policy_version
                == provider.policy_version,
                TutorProfileOwnershipProof.key_version == provider.key_version,
                TutorProfileOwnershipProof.state == "current",
            )
        )
    )
    if len(proof_candidates) != 1:
        raise MentorCeremonyError(403, "AUTHORIZATION_DENIED")
    preliminary = db.get(TutorProfileOwnershipProof, proof_candidates[0])
    if preliminary is None:
        raise MentorCeremonyError(403, "AUTHORIZATION_DENIED")
    # Global authority lock order is ceremony/provider -> stable User ->
    # profile -> proof -> invitation/consent -> session classes.  The first
    # query discovers only an opaque candidate id; every authorizing field is
    # re-read under this order.
    user = _locked_row(db, User, preliminary.user_id)
    profile = _locked_row(db, TutorProfile, preliminary.tutor_profile_id)
    proof = _locked_row(db, TutorProfileOwnershipProof, preliminary.id)
    role = ceremony.requested_role or ""
    if (
        user is None
        or profile is None
        or profile.user_id != user.id
        or proof.user_id != user.id
        or proof.tutor_profile_id != profile.id
        or proof.state != "current"
        or proof.deleted_at is not None
        or proof.revoked_at is not None
        or proof.provider_subject_hash != provider.provider_subject_hash
        or proof.evidence_digest != provider.evidence_digest
        or proof.provider_class != provider.provider_class
        or proof.assurance_class != provider.assurance_class
        or proof.policy_version != provider.policy_version
        or proof.key_version != provider.key_version
        or _utc(proof.issued_at) > now
        or _utc(proof.expires_at) <= now
        or not _role_is_server_authorized(user=user, profile=profile, role=role)
    ):
        raise MentorCeremonyError(403, "AUTHORIZATION_DENIED")

    invitation: MentorInvitation | None = None
    if ceremony.intent == "mentor_session":
        invitation_candidates = list(
            db.scalars(
                select(MentorInvitation.id)
                .where(
                    MentorInvitation.mentor_match_hash
                    == provider.provider_subject_hash,
                    MentorInvitation.mentor_role == role,
                    MentorInvitation.purpose_code == ceremony.purpose_code,
                    MentorInvitation.state == "pending",
                    MentorInvitation.deleted_at.is_(None),
                )
            )
        )
        if len(invitation_candidates) != 1:
            raise MentorCeremonyError(403, "AUTHORIZATION_DENIED")
        invitation = _locked_row(db, MentorInvitation, invitation_candidates[0])
        if (
            invitation is None
            or invitation.state != "pending"
            or invitation.deleted_at is not None
            or _utc(invitation.expires_at) <= now
        ):
            raise MentorCeremonyError(403, "AUTHORIZATION_DENIED")
        _purpose_policy(
            role=role,
            purpose=invitation.purpose_code,
            consent_version=invitation.consent_version,
            acceptance_version=invitation.acceptance_text_version,
            disclosures=list(invitation.disclosure_classes),
        )
    return user, profile, proof, invitation, provider


def issue_bootstrap(
    db: Session,
    request: Request,
    response: Response,
) -> dict[str, Any]:
    """Create a non-authorizing browser binding for the public mentor entry."""

    _lock_authority_scope(db, request, fallback="public-bootstrap")
    _reject_conflicting_session_class(db, request)
    if request.cookies.get(SESSION_COOKIE):
        raise MentorCeremonyError(409, "SESSION_CONFLICT")
    now = _now()
    _consume_rate_budget(
        db,
        request=request,
        operation="entry",
        binding="public-entry",
        now=now,
    )
    # Bootstrap has no replay contract and must be freshly random.  Durable
    # replay tokens are used only after a server-owned UUID binding exists.
    raw_token = _random_token()
    db.add(
        MentorBootstrapAttempt(
            token_hash=_token_hash(raw_token),
            requested_role="tutor",
            purpose_code=None,
            state="active",
            expires_at=now + timedelta(seconds=settings.mentor_bootstrap_ttl_seconds),
        )
    )
    _audit(db, action="mentor.bootstrap.issued", state="active")
    db.commit()
    _set_cookie(
        response,
        key=BOOTSTRAP_COOKIE,
        token=raw_token,
        max_age=settings.mentor_bootstrap_ttl_seconds,
        path=MENTOR_COOKIE_PATH,
        same_site="strict",
    )
    _headers(response)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "accepted",
        "next": "ceremony_initiate",
        "expiresInSeconds": settings.mentor_bootstrap_ttl_seconds,
    }


def _add_provider_transaction(
    db: Session,
    *,
    ceremony: MentorCeremony,
    requested_role: str,
    raw_nonce: str,
    raw_correlation: str,
) -> None:
    provider_class, assurance_class, policy_version = _provider_policy(
        requested_role
    )
    now = _now()
    db.add(
        MentorProviderResult(
            ceremony_id=ceremony.id,
            provider_class=provider_class,
            assurance_class=assurance_class,
            policy_version=policy_version,
            issuer_hash=keyed_hash(settings.mentor_identity_provider_issuer),
            audience_hash=keyed_hash(settings.mentor_identity_provider_audience),
            algorithm=settings.mentor_identity_provider_algorithm,
            nonce_hash=keyed_hash(raw_nonce),
            correlation_hash=keyed_hash(raw_correlation),
            nonce_ct=encrypt(raw_nonce),
            correlation_ct=encrypt(raw_correlation),
            transaction_key_version=active_key_version(),
            failure_count=0,
            state="pending",
            expires_at=min(
                _utc(ceremony.expires_at),
                now + timedelta(seconds=settings.mentor_provider_deadline_seconds),
            ),
        )
    )


def _deny_provider_result(
    db: Session,
    row: MentorProviderResult,
    *,
    now: datetime,
) -> NoReturn:
    """Persist only a bounded denial counter, then fail with one public code."""

    row.failure_count = min(
        row.failure_count + 1,
        settings.mentor_provider_circuit_breaker_failures,
    )
    if row.failure_count >= settings.mentor_provider_circuit_breaker_failures:
        row.state = "rejected"
        row.consumed_at = now
    _audit(db, action="mentor.provider.result_denied", state="rejected")
    db.commit()
    raise MentorCeremonyError(403, "AUTHORIZATION_DENIED")


def claim_provider_start(
    db: Session,
    *,
    ceremony_id: uuid.UUID,
) -> dict[str, str]:
    """Lease the server-created provider transaction to an internal adapter.

    Raw nonce and correlation values are decrypted only for this backchannel
    dispatch seam.  They never cross a browser response or enter audit/log
    material.  A callback received before this claim fails closed.
    """

    _lock_authority_scope(
        db, ceremony_id=ceremony_id, fallback=f"ceremony:{ceremony_id}"
    )
    row = db.scalar(
        select(MentorProviderResult)
        .where(MentorProviderResult.ceremony_id == ceremony_id)
        .with_for_update()
    )
    now = _now()
    if (
        row is None
        or row.state != "pending"
        or row.deleted_at is not None
        or _utc(row.expires_at) <= now
        or row.start_dispatched_at is not None
    ):
        raise MentorCeremonyError(409, "CONCURRENT_STATE_CHANGED")
    try:
        nonce = decrypt(row.nonce_ct)
        correlation = decrypt(row.correlation_ct)
    except Exception:
        raise MentorCeremonyError(503, "PROVIDER_UNAVAILABLE", retryable=True) from None
    if (
        keyed_hash(nonce) != row.nonce_hash
        or keyed_hash(correlation) != row.correlation_hash
        or row.transaction_key_version != active_key_version()
    ):
        raise MentorCeremonyError(503, "PROVIDER_UNAVAILABLE", retryable=True)
    row.start_dispatched_at = now
    db.commit()
    return {
        "providerClass": row.provider_class,
        "assuranceClass": row.assurance_class,
        "policyVersion": row.policy_version,
        "issuer": settings.mentor_identity_provider_issuer,
        "audience": settings.mentor_identity_provider_audience,
        "algorithm": settings.mentor_identity_provider_algorithm,
        "nonce": nonce,
        "correlation": correlation,
    }


def settle_provider_result(
    db: Session,
    *,
    ceremony_id: uuid.UUID,
    payload: dict[str, Any],
    signature_b64: str,
) -> None:
    """Verify and consume one signed server-to-server provider callback."""

    _lock_authority_scope(
        db, ceremony_id=ceremony_id, fallback=f"ceremony:{ceremony_id}"
    )
    row = db.scalar(
        select(MentorProviderResult)
        .where(MentorProviderResult.ceremony_id == ceremony_id)
        .with_for_update()
    )
    now = _now()
    if row is None:
        raise MentorCeremonyError(403, "AUTHORIZATION_DENIED")
    if (
        row.state != "pending"
        or row.start_dispatched_at is None
        or row.deleted_at is not None
        or _utc(row.expires_at) <= now
        or set(payload) != _PROVIDER_RESULT_FIELDS
    ):
        _deny_provider_result(db, row, now=now)
    try:
        signature = base64.b64decode(signature_b64, validate=True)
        public_key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(
                settings.mentor_identity_provider_public_key_b64,
                validate=True,
            )
        )
        public_key.verify(signature, _provider_result_bytes(payload))
    except (TypeError, ValueError, binascii.Error, InvalidSignature):
        _deny_provider_result(db, row, now=now)

    try:
        issued_at = _parse_provider_time(payload.get("issuedAt"))
        expires_at = _parse_provider_time(payload.get("expiresAt"))
    except MentorCeremonyError:
        _deny_provider_result(db, row, now=now)
    try:
        nonce = decrypt(row.nonce_ct)
        correlation = decrypt(row.correlation_ct)
    except Exception:
        raise MentorCeremonyError(503, "PROVIDER_UNAVAILABLE", retryable=True) from None
    expected = {
        "providerClass": row.provider_class,
        "assuranceClass": row.assurance_class,
        "policyVersion": row.policy_version,
        "issuer": settings.mentor_identity_provider_issuer,
        "audience": settings.mentor_identity_provider_audience,
        "algorithm": row.algorithm,
        "nonce": nonce,
        "correlation": correlation,
    }
    if (
        any(payload.get(key) != value for key, value in expected.items())
        or keyed_hash(str(payload.get("issuer"))) != row.issuer_hash
        or keyed_hash(str(payload.get("audience"))) != row.audience_hash
        or keyed_hash(str(payload.get("nonce"))) != row.nonce_hash
        or keyed_hash(str(payload.get("correlation"))) != row.correlation_hash
        or not isinstance(payload.get("providerSubject"), str)
        or not str(payload["providerSubject"]).strip()
        or payload.get("accountBindingClass") != "provider_account"
        or payload.get("userPresenceApproved") is not True
        or not isinstance(payload.get("evidenceDigest"), str)
        or re.fullmatch(r"[0-9a-f]{64}", str(payload["evidenceDigest"])) is None
        or issued_at < _utc(row.start_dispatched_at) - timedelta(seconds=5)
        or issued_at > now + timedelta(seconds=5)
        or expires_at <= issued_at
        or expires_at <= now
        or expires_at > _utc(row.expires_at)
    ):
        _deny_provider_result(db, row, now=now)
    row.provider_subject_hash = keyed_hash(str(payload["providerSubject"]))
    row.evidence_digest = str(payload["evidenceDigest"])
    row.key_version = active_key_version()
    row.issued_at = issued_at
    row.expires_at = expires_at
    row.state = "verified"
    db.commit()


def _find_ceremony(
    db: Session,
    request: Request,
    *,
    for_update: bool = True,
    allow_terminal: bool = False,
    allow_predecessor: bool = False,
) -> MentorCeremony:
    raw = request.cookies.get(CEREMONY_COOKIE)
    if not raw:
        raise MentorCeremonyError(401, "AUTHENTICATION_REQUIRED")
    presented_hash = _token_hash(raw)
    selector = MentorCeremony.token_hash == presented_hash
    if allow_predecessor:
        selector = or_(
            selector,
            MentorCeremony.predecessor_token_hash == presented_hash,
        )
    query = select(MentorCeremony).where(selector)
    if for_update:
        query = query.with_for_update()
    row = db.scalar(query)
    now = _now()
    if row is None:
        raise MentorCeremonyError(401, "AUTHENTICATION_REQUIRED")
    setattr(
        row,
        "_nyay22_predecessor_presented",
        row.predecessor_token_hash == presented_hash,
    )
    if row.state in {"exchanged", "expired", "revoked", "deleted"}:
        if allow_terminal:
            return row
        raise MentorCeremonyError(
            410,
            "AUTHORITY_TERMINAL",
            clear_cookie=(CEREMONY_COOKIE, MENTOR_COOKIE_PATH, "strict"),
        )
    if _utc(row.expires_at) <= now:
        row.state = "expired"
        row.terminal_at = row.expires_at
        _audit(
            db,
            action="mentor.ceremony.expired",
            state="expired",
            generation=row.generation,
            actor_user_id=row.actor_user_id,
        )
        db.commit()
        raise MentorCeremonyError(
            410,
            "AUTHORITY_TERMINAL",
            clear_cookie=(CEREMONY_COOKIE, MENTOR_COOKIE_PATH, "strict"),
        )
    return row


def _find_exchange_ceremony(db: Session, request: Request) -> MentorCeremony:
    """Resolve a lost exchange response through any surviving bound cookie."""

    if request.cookies.get(CEREMONY_COOKIE):
        return _find_ceremony(db, request, allow_terminal=True)
    raw_session = request.cookies.get(SESSION_COOKIE)
    raw_step_up = request.cookies.get(STEP_UP_COOKIE)
    ceremony_id = None
    if raw_session:
        issued = db.scalar(
            select(MentorSession).where(
                MentorSession.token_hash == _token_hash(raw_session)
            )
        )
        ceremony_id = issued.ceremony_id if issued is not None else None
    if ceremony_id is None and raw_step_up:
        issued_step_up = db.scalar(
            select(MentorAuthorityStepUp).where(
                MentorAuthorityStepUp.token_hash == _token_hash(raw_step_up)
            )
        )
        ceremony_id = (
            issued_step_up.ceremony_id if issued_step_up is not None else None
        )
    if ceremony_id is None:
        raise MentorCeremonyError(401, "AUTHENTICATION_REQUIRED")
    ceremony = _locked_row(db, MentorCeremony, ceremony_id)
    if ceremony is None:
        raise MentorCeremonyError(401, "AUTHENTICATION_REQUIRED")
    return ceremony


def _current_proof(
    db: Session, ceremony: MentorCeremony, now: datetime
) -> tuple[User, TutorProfile, TutorProfileOwnershipProof]:
    if ceremony.actor_user_id is None or ceremony.tutor_profile_id is None or ceremony.ownership_proof_id is None:
        raise MentorCeremonyError(503, "PROVIDER_UNAVAILABLE", retryable=True)
    user = _locked_row(db, User, ceremony.actor_user_id)
    profile = _locked_row(db, TutorProfile, ceremony.tutor_profile_id)
    proof = _locked_row(db, TutorProfileOwnershipProof, ceremony.ownership_proof_id)
    provider = db.scalar(
        select(MentorProviderResult)
        .where(MentorProviderResult.ceremony_id == ceremony.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        user is None
        or user.status != "active"
        or user.deleted_at is not None
        or profile is None
        or profile.status != "active"
        or profile.deleted_at is not None
        or profile.user_id != user.id
        or not _role_is_server_authorized(
            user=user,
            profile=profile,
            role=ceremony.requested_role or "",
        )
        or proof is None
        or proof.user_id != user.id
        or proof.tutor_profile_id != profile.id
        or proof.state != "current"
        or proof.deleted_at is not None
        or (
            proof.provider_class,
            proof.assurance_class,
            proof.policy_version,
        )
        not in _PROOF_POLICIES.get(ceremony.requested_role or "", frozenset())
        or _utc(proof.issued_at) > now
        or _utc(proof.expires_at) <= now
        or proof.revoked_at is not None
        or provider is None
        or provider.state != "consumed"
        or provider.deleted_at is not None
        or proof.provider_subject_hash != provider.provider_subject_hash
        or proof.evidence_digest != provider.evidence_digest
        or proof.key_version != provider.key_version
        or proof.provider_class != provider.provider_class
        or proof.assurance_class != provider.assurance_class
        or proof.policy_version != provider.policy_version
    ):
        raise MentorCeremonyError(403, "AUTHORIZATION_DENIED")
    return user, profile, proof


def _verification(proof: TutorProfileOwnershipProof, now: datetime) -> dict[str, Any]:
    return {
        "result": "current_positive",
        "provenanceClass": proof.provider_class,
        "policyVersion": proof.policy_version,
        "verifiedAt": _utc(proof.issued_at).isoformat(),
        "currentAt": now.isoformat(),
        "ownershipBinding": "tutor_profile_user_equals_actor",
    }


def _session_from_cookie(
    db: Session,
    request: Request,
    *,
    for_update: bool = True,
    allow_terminal: bool = False,
    allow_owner_conflict_for_retirement: bool = False,
) -> MentorSession:
    if not allow_owner_conflict_for_retirement:
        _reject_conflicting_session_class(db, request)
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        raise MentorCeremonyError(401, "AUTHENTICATION_REQUIRED")
    session = db.scalar(
        select(MentorSession).where(MentorSession.token_hash == _token_hash(raw))
    )
    now = _now()
    if session is None:
        raise MentorCeremonyError(401, "AUTHENTICATION_REQUIRED")
    if for_update:
        _user, owner_sessions, mentor_sessions = _lock_actor_session_classes(
            db, session.actor_user_id
        )
        session = next(
            (candidate for candidate in mentor_sessions if candidate.id == session.id),
            None,
        )
        if session is None:
            raise MentorCeremonyError(401, "AUTHENTICATION_REQUIRED")
        if (
            not allow_owner_conflict_for_retirement
            and any(row.status == "active" for row in owner_sessions)
        ):
            raise MentorCeremonyError(409, "SESSION_CONFLICT")
    if session.state != "active":
        if allow_terminal:
            return session
        raise MentorCeremonyError(
            410,
            "AUTHORITY_TERMINAL",
            clear_cookie=(SESSION_COOKIE, "/", "lax"),
        )
    if (
        _utc(session.expires_at) <= now
        or (_utc(session.last_seen_at) + timedelta(seconds=settings.mentor_session_idle_ttl_seconds)) <= now
    ):
        session.state = "expired"
        session.terminal_at = _session_expiry_boundary(session)
        _audit(
            db,
            action="mentor.session.expired",
            state="expired",
            generation=session.generation,
            actor_user_id=session.actor_user_id,
            authority_domain_hash=session.authority_domain_hash,
            purpose_code=session.purpose_code,
        )
        db.commit()
        raise MentorCeremonyError(
            410,
            "SESSION_EXPIRED",
            clear_cookie=(SESSION_COOKIE, "/", "lax"),
        )
    return session


def _lock_presented_session_ceremony(db: Session, request: Request) -> None:
    """Serialize and take the global ceremony-before-session lock."""

    raw = request.cookies.get(SESSION_COOKIE)
    if raw is None:
        return
    candidate = db.scalar(
        select(MentorSession).where(
            MentorSession.token_hash == _token_hash(raw)
        )
    )
    if candidate is not None:
        _serialize_session_authority(db, candidate.id)
        _locked_row(db, MentorCeremony, candidate.ceremony_id)


def _serialize_session_authority(db: Session, session_id: uuid.UUID) -> None:
    """Acquire one canonical transaction lock before authority row locks."""

    bind = db.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return
    raw = int.from_bytes(
        hashlib.sha256(f"nyay22-session-lock:{session_id}".encode()).digest()[:8],
        "big",
        signed=False,
    )
    key = raw if raw < 2**63 else raw - 2**64
    db.execute(select(func.pg_advisory_xact_lock(key)))


def _lock_deletion_ceremony_source_first(db: Session, request: Request) -> None:
    """Discover a deletion ceremony and lock its source authority first.

    Discovery is non-authorizing.  Authorizing fields are reread later under
    row locks.  This common first lock prevents a deletion-ceremony -> user /
    session-end user -> deletion-ceremony PostgreSQL cycle.
    """

    if request.cookies.get(SESSION_COOKIE):
        _lock_presented_session_ceremony(db, request)
    raw = request.cookies.get(CEREMONY_COOKIE)
    if not raw:
        return
    presented_hash = _token_hash(raw)
    candidates = list(
        db.scalars(
            select(MentorCeremony)
            .where(
                or_(
                    MentorCeremony.token_hash == presented_hash,
                    MentorCeremony.predecessor_token_hash == presented_hash,
                )
            )
            .limit(2)
        )
    )
    if len(candidates) != 1 or candidates[0].intent != "authority_deletion_step_up":
        return
    source = (candidates[0].metadata_json or {}).get("mentorSessionId")
    try:
        source_id = uuid.UUID(str(source))
    except (TypeError, ValueError, AttributeError):
        return
    session = db.get(MentorSession, source_id)
    if session is None:
        return
    _serialize_session_authority(db, session.id)
    _locked_row(db, MentorCeremony, session.ceremony_id)


def _locked_row(db: Session, model: Any, row_id: uuid.UUID | None) -> Any:
    if row_id is None:
        return None
    return db.scalar(
        select(model)
        .where(model.id == row_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _validate_live_session_graph(
    db: Session, session: MentorSession, now: datetime
) -> tuple[
    MentorEngagement,
    MentorSubjectConsent,
    TutorProfileOwnershipProof,
    TutorProfile,
]:
    # The actor/session rows are already locked by ``_session_from_cookie``.
    # Lock every downstream authority node before evaluating any disclosure.
    user = _locked_row(db, User, session.actor_user_id)
    engagement = _locked_row(db, MentorEngagement, session.engagement_id)
    consent = _locked_row(db, MentorConsent, session.consent_id)
    subject_consent = _locked_row(
        db, MentorSubjectConsent, session.subject_consent_id
    )
    proof = _locked_row(db, TutorProfileOwnershipProof, session.ownership_proof_id)
    profile = _locked_row(db, TutorProfile, session.tutor_profile_id)
    source_ceremony = _locked_row(db, MentorCeremony, session.ceremony_id)
    invitation = (
        _locked_row(db, MentorInvitation, engagement.invitation_id)
        if engagement is not None
        else None
    )
    provider = db.scalar(
        select(MentorProviderResult)
        .where(MentorProviderResult.ceremony_id == session.ceremony_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    registration = (
        _locked_row(db, StudentRegistration, engagement.subject_registration_id)
        if engagement is not None
        else None
    )
    subject_user = (
        _locked_row(db, User, registration.user_id)
        if registration is not None
        else None
    )
    permitted_now = {
        mapped
        for item in (
            set(consent.disclosure_classes if consent is not None else [])
            & set(
                subject_consent.disclosure_classes
                if subject_consent is not None
                else []
            )
        )
        if (mapped := _DISCLOSURE_TO_SLICE.get(item)) is not None
    }
    try:
        policy = _purpose_policy(
            role=session.mentor_role,
            purpose=session.purpose_code,
            consent_version=(
                subject_consent.version if subject_consent is not None else ""
            ),
            acceptance_version=(
                invitation.acceptance_text_version if invitation is not None else ""
            ),
            disclosures=list(
                invitation.disclosure_classes if invitation is not None else []
            ),
        )
    except MentorCeremonyError:
        raise MentorCeremonyError(403, "AUTHORIZATION_DENIED") from None
    if (
        user is None
        or user.status != "active"
        or user.deleted_at is not None
        or engagement is None
        or engagement.state != "active"
        or engagement.deleted_at is not None
        or engagement.mentor_user_id != session.actor_user_id
        or engagement.tutor_profile_id != session.tutor_profile_id
        or engagement.authority_domain_hash != session.authority_domain_hash
        or engagement.purpose_code != session.purpose_code
        or consent is None
        or consent.deleted_at is not None
        or consent.engagement_id != engagement.id
        or consent.purpose_code != session.purpose_code
        or consent.status != "granted"
        or subject_consent is None
        or subject_consent.deleted_at is not None
        or subject_consent.id != session.subject_consent_id
        or subject_consent.invitation_id != engagement.invitation_id
        or subject_consent.subject_registration_id
        != engagement.subject_registration_id
        or subject_consent.granted_by_user_id != invitation.initiator_user_id
        or consent.version != subject_consent.version
        or consent.version != invitation.consent_version
        or set(consent.disclosure_classes)
        - set(subject_consent.disclosure_classes)
        or set(consent.disclosure_classes) - set(invitation.disclosure_classes)
        or subject_consent.granting_session_hash
        != invitation.initiator_session_hash
        or subject_consent.purpose_policy_version != _PURPOSE_POLICY_VERSION
        or subject_consent.purpose_code != session.purpose_code
        or subject_consent.status != "granted"
        or _utc(subject_consent.expires_at) <= now
        or proof is None
        or proof.deleted_at is not None
        or proof.user_id != session.actor_user_id
        or proof.tutor_profile_id != session.tutor_profile_id
        or proof.state != "current"
        or proof.revoked_at is not None
        or _utc(proof.issued_at) > now
        or (
            proof.provider_class,
            proof.assurance_class,
            proof.policy_version,
        )
        not in _PROOF_POLICIES.get(session.mentor_role, frozenset())
        or _utc(proof.expires_at) <= now
        or provider is None
        or provider.state != "consumed"
        or provider.deleted_at is not None
        or proof.provider_subject_hash != provider.provider_subject_hash
        or proof.evidence_digest != provider.evidence_digest
        or proof.key_version != provider.key_version
        or proof.provider_class != provider.provider_class
        or proof.assurance_class != provider.assurance_class
        or proof.policy_version != provider.policy_version
        or profile is None
        or profile.deleted_at is not None
        or profile.user_id != session.actor_user_id
        or profile.status != "active"
        or not _role_is_server_authorized(
            user=user,
            profile=profile,
            role=session.mentor_role,
        )
        or invitation is None
        or invitation.deleted_at is not None
        or invitation.id != engagement.invitation_id
        or invitation.subject_registration_id != engagement.subject_registration_id
        or registration is None
        or registration.deleted_at is not None
        or registration.status != "active"
        or invitation.initiator_user_id != registration.user_id
        or subject_user is None
        or subject_user.role != "student"
        or subject_user.status != "active"
        or subject_user.deleted_at is not None
        or invitation.state != "accepted"
        or invitation.mentor_role != session.mentor_role
        or invitation.purpose_code != session.purpose_code
        or invitation.authority_domain_hash != session.authority_domain_hash
        or invitation.purpose_policy_version != _PURPOSE_POLICY_VERSION
        or source_ceremony is None
        or source_ceremony.deleted_at is not None
        or source_ceremony.state != "exchanged"
        or source_ceremony.intent != "mentor_session"
        or source_ceremony.actor_user_id != session.actor_user_id
        or source_ceremony.tutor_profile_id != session.tutor_profile_id
        or source_ceremony.ownership_proof_id != session.ownership_proof_id
        or source_ceremony.invitation_id != invitation.id
        or source_ceremony.purpose_code != session.purpose_code
        or set(session.permitted_profile_slices) - permitted_now
        or set(session.scopes) - set(_PURPOSE_SCOPES.get(session.purpose_code, ()))
        or set(invitation.disclosure_classes) - set(policy["disclosures"])
    ):
        raise MentorCeremonyError(403, "AUTHORIZATION_DENIED")
    return engagement, subject_consent, proof, profile


def _subject_sharing_allowed(db: Session, engagement: MentorEngagement) -> bool:
    return _subject_registration_sharing_allowed(
        db, engagement.subject_registration_id
    )


def _subject_registration_sharing_allowed(
    db: Session, subject_registration_id: uuid.UUID
) -> bool:
    registration = _locked_row(db, StudentRegistration, subject_registration_id)
    if (
        registration is None
        or registration.status != "active"
        or registration.deleted_at is not None
    ):
        return False
    subject_user = _locked_row(db, User, registration.user_id)
    if (
        subject_user is None
        or subject_user.role != "student"
        or subject_user.status != "active"
        or subject_user.deleted_at is not None
    ):
        return False
    profile = db.scalar(
        select(StudentProfile)
        .where(StudentProfile.registration_id == registration.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    access_mode = "limited" if registration.is_minor else "full"
    if profile is None or access_mode == "limited":
        # Keep the exact names in this branch: the structural contract verifies
        # that NYAY-5 guardian authority and limited mode are server inputs.
        guardian = db.scalar(
            select(GuardianConsent)
            .where(GuardianConsent.registration_id == registration.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if access_mode == "limited" or not has_authoritative_guardian_proof(guardian):
            return False
    return True


def _validate_invitation_consent(
    db: Session,
    invitation: MentorInvitation,
    now: datetime,
) -> MentorSubjectConsent:
    registration = _locked_row(
        db, StudentRegistration, invitation.subject_registration_id
    )
    subject_consent = db.scalar(
        select(MentorSubjectConsent)
        .where(MentorSubjectConsent.invitation_id == invitation.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    guardian = None
    if registration is not None and registration.is_minor:
        guardian = db.scalar(
            select(GuardianConsent)
            .where(GuardianConsent.registration_id == registration.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    try:
        _purpose_policy(
            role=invitation.mentor_role,
            purpose=invitation.purpose_code,
            consent_version=invitation.consent_version,
            acceptance_version=invitation.acceptance_text_version,
            disclosures=list(invitation.disclosure_classes),
        )
    except MentorCeremonyError:
        raise MentorCeremonyError(403, "AUTHORIZATION_DENIED") from None
    if (
        registration is None
        or invitation.initiator_user_id != registration.user_id
        or invitation.purpose_policy_version != _PURPOSE_POLICY_VERSION
        or re.fullmatch(r"[0-9a-f]{64}", invitation.initiator_session_hash)
        is None
        or re.fullmatch(r"[0-9a-f]{64}", invitation.creation_idempotency_hash)
        is None
        or subject_consent is None
        or subject_consent.granted_by_user_id != registration.user_id
        or subject_consent.granting_session_hash
        != invitation.initiator_session_hash
        or subject_consent.purpose_policy_version != _PURPOSE_POLICY_VERSION
        or re.fullmatch(
            r"[0-9a-f]{64}", subject_consent.grant_idempotency_hash
        )
        is None
        or (
            registration.is_minor
            and (
                guardian is None
                or not has_authoritative_guardian_proof(guardian)
                or subject_consent.guardian_consent_id != guardian.id
            )
        )
        or (not registration.is_minor and subject_consent.guardian_consent_id is not None)
        or subject_consent.status != "granted"
        or subject_consent.deleted_at is not None
        or subject_consent.subject_registration_id
        != invitation.subject_registration_id
        or subject_consent.purpose_code != invitation.purpose_code
        or subject_consent.version != invitation.consent_version
        or set(invitation.disclosure_classes)
        - set(subject_consent.disclosure_classes)
        or _utc(subject_consent.recorded_at) > now
        or _utc(subject_consent.expires_at) <= now
        or not _subject_registration_sharing_allowed(
            db, invitation.subject_registration_id
        )
    ):
        raise MentorCeremonyError(403, "AUTHORIZATION_DENIED")
    return subject_consent


def create_owner_mentor_prerequisites(
    db: Session,
    *,
    owner_session_id: uuid.UUID,
    matched_tutor_profile_id: uuid.UUID,
    purpose_code: str,
    disclosure_classes: list[str],
    idempotency_key: str,
    now: datetime | None = None,
) -> tuple[MentorInvitation, MentorSubjectConsent]:
    """Persist the independent owner handoff consumed by the ceremony.

    This is an internal service boundary for the authenticated owner surface,
    not a mentor-browser endpoint.  The caller supplies only database row
    identities already resolved by server policy.  This function locks and
    re-validates those rows, derives the mentor role and protected match from
    the current ownership proof, and records subject consent independently of
    any later mentor acceptance.
    """

    mentor_actor_candidate = db.scalar(
        select(TutorProfileOwnershipProof.user_id)
        .where(
            TutorProfileOwnershipProof.tutor_profile_id
            == matched_tutor_profile_id,
            TutorProfileOwnershipProof.state == "current",
            TutorProfileOwnershipProof.deleted_at.is_(None),
        )
        .limit(1)
    )
    owner_actor_candidate = db.scalar(
        select(AuthSession.user_id).where(AuthSession.id == owner_session_id)
    )
    lock_actors = sorted(
        {
            candidate
            for candidate in (mentor_actor_candidate, owner_actor_candidate)
            if candidate is not None
        },
        key=str,
    )
    if lock_actors:
        for candidate in lock_actors:
            _lock_authority_scope(
                db,
                actor_hint=candidate,
                fallback=f"actor:{candidate}",
            )
    else:
        _lock_authority_scope(
            db, fallback=f"profile:{matched_tutor_profile_id}"
        )
    current = _utc(now or _now())
    owner = _locked_row(db, User, owner_actor_candidate)
    owner_session = _locked_row(db, AuthSession, owner_session_id)
    if (
        owner_session is None
        or owner is None
        or owner_session.user_id != owner.id
        or owner_session.status != "active"
        or owner_session.deleted_at is not None
        or _utc(owner_session.expires_at) <= current
    ):
        raise MentorCeremonyError(403, "AUTHORIZATION_DENIED")
    registration = db.scalar(
        select(StudentRegistration)
        .where(StudentRegistration.user_id == owner_session.user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    profile = _locked_row(db, TutorProfile, matched_tutor_profile_id)
    proof_ids = list(
        db.scalars(
            select(TutorProfileOwnershipProof.id).where(
                TutorProfileOwnershipProof.tutor_profile_id
                == matched_tutor_profile_id,
                TutorProfileOwnershipProof.state == "current",
                TutorProfileOwnershipProof.deleted_at.is_(None),
            )
        )
    )
    proof = (
        _locked_row(db, TutorProfileOwnershipProof, proof_ids[0])
        if len(proof_ids) == 1
        else None
    )
    if purpose_code == "student_guidance":
        derived_role = "tutor"
    elif purpose_code in {
        "legal_education",
        "document_review",
        "case_discussion",
    }:
        derived_role = "lawyer_tutor"
    else:
        raise MentorCeremonyError(403, "AUTHORIZATION_DENIED")
    policy = _PURPOSE_POLICIES.get(purpose_code)
    if (
        owner is None
        or owner.role != "student"
        or owner.status != "active"
        or owner.deleted_at is not None
        or registration is None
        or registration.status != "active"
        or registration.deleted_at is not None
        or profile is None
        or proof is None
        or proof.user_id != profile.user_id
        or proof.state != "current"
        or proof.revoked_at is not None
        or proof.deleted_at is not None
        or _utc(proof.issued_at) > current
        or _utc(proof.expires_at) <= current
        or (
            proof.provider_class,
            proof.assurance_class,
            proof.policy_version,
        )
        not in _PROOF_POLICIES[derived_role]
        or policy is None
        or derived_role not in policy["roles"]
        or not isinstance(disclosure_classes, list)
        or len(disclosure_classes) != len(set(disclosure_classes))
        or set(disclosure_classes) - policy["disclosures"]
    ):
        raise MentorCeremonyError(403, "AUTHORIZATION_DENIED")

    guardian = None
    if registration.is_minor:
        guardian = db.scalar(
            select(GuardianConsent)
            .where(GuardianConsent.registration_id == registration.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if not has_authoritative_guardian_proof(guardian):
            raise MentorCeremonyError(403, "AUTHORIZATION_DENIED")

    payload = {
        "purposeCode": purpose_code,
        "disclosureClasses": list(disclosure_classes),
        "matchedTutorProfile": str(profile.id),
    }
    invitation_id = uuid.UUID(
        keyed_hash(
            "mentor-owner-invitation-binding:v1:"
            f"{owner_session.id}:{idempotency_key}"
        )[:32]
    )
    record, replay = _begin_idempotency(
        db,
        operation="owner-create-mentor-prerequisites",
        binding=f"owner-invitation:{invitation_id}",
        idempotency_key=idempotency_key,
        payload=payload,
    )
    if replay is not None:
        try:
            invitation_id = uuid.UUID(str(replay[1]["invitationBinding"]))
            consent_id = uuid.UUID(str(replay[1]["consentBinding"]))
        except (KeyError, TypeError, ValueError):
            raise MentorCeremonyError(409, "CONCURRENT_STATE_CHANGED") from None
        invitation = _locked_row(db, MentorInvitation, invitation_id)
        consent = _locked_row(db, MentorSubjectConsent, consent_id)
        if invitation is None or consent is None:
            raise MentorCeremonyError(409, "CONCURRENT_STATE_CHANGED")
        return invitation, consent

    invitation = MentorInvitation(
        id=invitation_id,
        subject_registration_id=registration.id,
        initiator_user_id=owner.id,
        initiator_session_hash=owner_session.token_hash,
        creation_idempotency_hash=keyed_hash(
            f"mentor-owner-idempotency:v1:{idempotency_key}"
        ),
        purpose_policy_version=_PURPOSE_POLICY_VERSION,
        mentor_match_hash=proof.provider_subject_hash,
        authority_domain_hash=keyed_hash(
            f"mentor-authority-domain:v1:{registration.id}:{invitation_id}"
        ),
        mentor_role=derived_role,
        purpose_code=purpose_code,
        consent_version=str(policy["consent_version"]),
        acceptance_text_version=str(policy["acceptance_version"]),
        disclosure_classes=list(disclosure_classes),
        state="pending",
        expires_at=current
        + timedelta(seconds=settings.mentor_ceremony_ttl_seconds),
    )
    db.add(invitation)
    db.flush()
    consent = MentorSubjectConsent(
        invitation_id=invitation.id,
        subject_registration_id=registration.id,
        granted_by_user_id=owner.id,
        granting_session_hash=owner_session.token_hash,
        grant_idempotency_hash=keyed_hash(
            f"mentor-owner-consent-idempotency:v1:{idempotency_key}"
        ),
        purpose_policy_version=_PURPOSE_POLICY_VERSION,
        guardian_consent_id=guardian.id if guardian is not None else None,
        purpose_code=purpose_code,
        version=str(policy["consent_version"]),
        disclosure_classes=list(disclosure_classes),
        status="granted",
        recorded_at=current,
        expires_at=invitation.expires_at,
    )
    db.add(consent)
    db.flush()
    _seal_idempotency(
        record,
        201,
        {
            "invitationBinding": str(invitation.id),
            "consentBinding": str(consent.id),
        },
    )
    _audit(
        db,
        action="mentor.subject_consent.recorded",
        state="granted",
        actor_user_id=owner.id,
        authority_domain_hash=invitation.authority_domain_hash,
        purpose_code=purpose_code,
        subject_consent_version=consent.version,
    )
    db.commit()
    return invitation, consent


def _session_projection(db: Session, session: MentorSession, *, touch: bool) -> dict[str, Any]:
    now = _now()
    engagement, subject_consent, proof, _profile = _validate_live_session_graph(
        db, session, now
    )
    if not _subject_sharing_allowed(db, engagement):
        raise MentorCeremonyError(403, "AUTHORIZATION_DENIED")
    if touch:
        session.last_seen_at = now
    absolute = max(1, int((_utc(session.expires_at) - _utc(session.issued_at)).total_seconds()))
    projection = {
        "schemaVersion": "mentor-session.v1",
        "sessionClass": "mentor",
        "mentorRole": session.mentor_role,
        "state": "active",
        "purposeCode": session.purpose_code,
        "scopes": list(session.scopes),
        "permittedProfileSlices": list(session.permitted_profile_slices),
        "sameActorVerified": True,
        "tutorProfileStatus": "active",
        "verification": _verification(proof, now),
        "subjectSharingEligibility": "allowed",
        "consent": {
            "purposeCode": subject_consent.purpose_code,
            "version": subject_consent.version,
            "status": "granted",
            "recordedAt": _utc(subject_consent.recorded_at).isoformat(),
        },
        "absoluteLifetimeSeconds": min(absolute, settings.mentor_session_absolute_ttl_seconds),
        "idleTimeoutSeconds": settings.mentor_session_idle_ttl_seconds,
        "issuedAt": _utc(session.issued_at).isoformat(),
        "expiresAt": _utc(session.expires_at).isoformat(),
    }
    return projection


def initiate(db: Session, request: Request, response: Response, idempotency_key: str | None, body: Any) -> dict[str, Any]:
    _lock_authority_scope(db, request, fallback="ceremony-initiate")
    payload = _body(body)
    if payload.get("privacyNoticeVersion") != settings.mentor_privacy_notice_version:
        raise MentorCeremonyError(400, "INVALID_REQUEST", field="request")
    _reject_conflicting_session_class(db, request)
    if request.cookies.get(SESSION_COOKIE) is not None:
        raise MentorCeremonyError(409, "SESSION_CONFLICT")
    bootstrap = request.cookies.get(BOOTSTRAP_COOKIE)
    existing_ceremony = request.cookies.get(CEREMONY_COOKIE)
    now = _now()
    bootstrap_row = None
    existing_row = None
    if bootstrap:
        bootstrap_row = db.scalar(
            select(MentorBootstrapAttempt)
            .where(MentorBootstrapAttempt.token_hash == _token_hash(bootstrap))
            .with_for_update()
        )
    if existing_ceremony:
        existing_row = db.scalar(
            select(MentorCeremony)
            .where(MentorCeremony.token_hash == _token_hash(existing_ceremony))
            .with_for_update()
        )
    if bootstrap_row is None and existing_row is None:
        raise MentorCeremonyError(401, "AUTHENTICATION_REQUIRED")
    if bootstrap_row is not None:
        if (
            bootstrap_row.state not in {"active", "consumed"}
            or bootstrap_row.deleted_at is not None
            or (
                bootstrap_row.state == "active"
                and _utc(bootstrap_row.expires_at) <= now
            )
        ):
            raise MentorCeremonyError(410, "AUTHORITY_TERMINAL")
        binding = f"bootstrap:{bootstrap_row.id}"
    else:
        assert existing_row is not None
        if (
            existing_row.deleted_at is not None
            or existing_row.bootstrap_attempt_id is None
        ):
            raise MentorCeremonyError(410, "AUTHORITY_TERMINAL")
        binding = f"bootstrap:{existing_row.bootstrap_attempt_id}"
    record, replay = _begin_idempotency(db, operation="initiate", binding=binding, idempotency_key=idempotency_key, payload=payload)
    if replay is not None:
        return _replay(db, response, replay)
    _consume_rate_budget(
        db,
        request=request,
        operation="initiate",
        binding=binding,
        now=now,
    )
    if (
        bootstrap_row is None
        or bootstrap_row.state != "active"
        or existing_row is not None
    ):
        db.rollback()
        raise MentorCeremonyError(409, "CEREMONY_REPLAYED")
    ceremony_id = uuid.uuid4()
    raw_token, token_seed_ct, token_seed_key_version = _new_seeded_token(
        "ceremony", ceremony_id
    )
    raw_nonce = _random_token()
    raw_correlation = _random_token()
    row = MentorCeremony(
        id=ceremony_id,
        bootstrap_attempt_id=bootstrap_row.id if bootstrap_row else None,
        token_hash=_token_hash(raw_token),
        token_seed_ct=token_seed_ct,
        token_seed_key_version=token_seed_key_version,
        challenge_hash=keyed_hash(raw_nonce),
        intent=payload["intent"],
        requested_role=payload["requestedMentorRole"],
        purpose_code=payload["purposeCode"],
        privacy_notice_version=payload["privacyNoticeVersion"],
        state="challenge_issued",
        generation=1,
        expires_at=now + timedelta(seconds=settings.mentor_ceremony_ttl_seconds),
    )
    db.add(row)
    db.flush()
    _add_provider_transaction(
        db,
        ceremony=row,
        requested_role=payload["requestedMentorRole"],
        raw_nonce=raw_nonce,
        raw_correlation=raw_correlation,
    )
    bootstrap_row.state = "consumed"
    bootstrap_row.consumed_at = now
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "accepted",
        "ceremonyState": "challenge_issued",
        "next": "external_identity",
        "intent": payload["intent"],
        "expiresInSeconds": settings.mentor_ceremony_ttl_seconds,
    }
    _seal_idempotency(
        record,
        202,
        result,
        cookie_effects=[
            {
                "action": "clear",
                "key": BOOTSTRAP_COOKIE,
                "path": MENTOR_COOKIE_PATH,
                "sameSite": "strict",
            },
            {
                "action": "set",
                "key": CEREMONY_COOKIE,
                "kind": "ceremony",
                "binding": str(row.id),
                "generation": row.generation,
                "maxAge": settings.mentor_ceremony_ttl_seconds,
                "path": MENTOR_COOKIE_PATH,
                "sameSite": "strict",
            },
        ],
    )
    _audit(db, action="mentor.ceremony.initiated", state="challenge_issued", generation=1)
    db.commit()
    response.status_code = 202
    _clear_cookie(response, key=BOOTSTRAP_COOKIE, path=MENTOR_COOKIE_PATH, same_site="strict")
    _set_cookie(response, key=CEREMONY_COOKIE, token=raw_token, max_age=settings.mentor_ceremony_ttl_seconds, path=MENTOR_COOKIE_PATH, same_site="strict")
    _headers(response)
    return result


def verify(db: Session, request: Request, response: Response, idempotency_key: str | None, body: Any) -> dict[str, Any]:
    _lock_authority_scope(db, request, fallback="ceremony-verify")
    payload = _body(body)
    _lock_deletion_ceremony_source_first(db, request)
    ceremony = _find_ceremony(
        db,
        request,
        allow_terminal=True,
        allow_predecessor=True,
    )
    _reject_conflicting_session_class(db, request)
    record, replay = _begin_idempotency(db, operation="verify", binding=f"ceremony:{ceremony.id}", idempotency_key=idempotency_key, payload=payload)
    if replay is not None:
        return _replay(db, response, replay)
    if getattr(ceremony, "_nyay22_predecessor_presented", False):
        db.rollback()
        raise MentorCeremonyError(409, "CEREMONY_REPLAYED")
    if ceremony.state != "challenge_issued":
        db.rollback()
        raise MentorCeremonyError(409, "CEREMONY_REPLAYED")
    now = _now()
    _consume_rate_budget(
        db,
        request=request,
        operation="verify",
        binding=f"ceremony:{ceremony.id}:g{ceremony.generation}",
        now=now,
    )
    user, profile, proof, invitation, provider = _derive_current_authority(
        db, ceremony, now
    )
    ceremony.actor_user_id = user.id
    ceremony.tutor_profile_id = profile.id
    ceremony.ownership_proof_id = proof.id
    ceremony.invitation_id = invitation.id if invitation is not None else None
    if ceremony.recovery and ceremony.intent == "mentor_session":
        _locked_user, owner_sessions, mentor_sessions = _lock_actor_session_classes(
            db, user.id
        )
        if any(row.status == "active" for row in owner_sessions):
            db.rollback()
            raise MentorCeremonyError(409, "SESSION_CONFLICT")
        ceremony.metadata_json = {
            "mandatoryRevocationSessionIds": sorted(
                str(row.id) for row in mentor_sessions if row.state == "active"
            )
        }
    provider.state = "consumed"
    provider.consumed_at = now
    previous_hash = ceremony.token_hash
    ceremony.generation += 1
    rotated_token = _seeded_token(
        "ceremony",
        ceremony.id,
        ceremony.generation,
        _decrypt_token_seed(ceremony),
    )
    ceremony.predecessor_token_hash = previous_hash
    ceremony.token_hash = _token_hash(rotated_token)
    ceremony.state = "proof_verified"
    ceremony.verified_at = now
    ceremony.verification_policy_version = proof.policy_version
    if ceremony.intent == "mentor_session":
        if invitation is None:
            db.rollback()
            raise MentorCeremonyError(403, "AUTHORIZATION_DENIED")
        # Do not disclose purpose, slice or receipt metadata until the
        # independently recorded subject/guardian boundary is current.
        _validate_invitation_consent(db, invitation, now)
        result = {
            "schemaVersion": "mentor-acceptance.v1",
            "status": "acceptance_required",
            "ceremonyState": "proof_verified",
            "intent": "mentor_session",
            "serverDerivedMentorRole": ceremony.requested_role,
            "purposeCode": invitation.purpose_code,
            "consentReceiptVersion": invitation.consent_version,
            "disclosureClasses": list(invitation.disclosure_classes),
            "acceptanceTextVersion": invitation.acceptance_text_version,
            "verification": _verification(proof, now),
            "expiresInSeconds": max(1, min(settings.mentor_ceremony_ttl_seconds, int((_utc(ceremony.expires_at) - now).total_seconds()))),
        }
    else:
        result = {
            "schemaVersion": "mentor-acceptance.v1",
            "status": "acceptance_required",
            "ceremonyState": "proof_verified",
            "intent": "authority_deletion_step_up",
            "deletionScope": "global_mentor_authority",
            "acceptanceTextVersion": ceremony.privacy_notice_version or "mentor-authority-deletion.v1",
            "verification": _verification(proof, now),
            "expiresInSeconds": min(settings.mentor_authority_step_up_ttl_seconds, max(1, int((_utc(ceremony.expires_at) - now).total_seconds()))),
        }
    _seal_idempotency(
        record,
        200,
        result,
        cookie_effects=[
            {
                "action": "clear",
                "key": CEREMONY_COOKIE,
                "path": MENTOR_COOKIE_PATH,
                "sameSite": "strict",
            },
            {
                "action": "set",
                "key": CEREMONY_COOKIE,
                "kind": "ceremony",
                "binding": str(ceremony.id),
                "generation": ceremony.generation,
                "maxAge": max(
                    1, int((_utc(ceremony.expires_at) - now).total_seconds())
                ),
                "path": MENTOR_COOKIE_PATH,
                "sameSite": "strict",
            },
        ],
    )
    _audit(
        db,
        action="mentor.ceremony.verified",
        state="proof_verified",
        generation=ceremony.generation,
        actor_user_id=user.id,
        authority_domain_hash=(
            invitation.authority_domain_hash if invitation is not None else None
        ),
        purpose_code=ceremony.purpose_code,
        policy_version=proof.policy_version,
        subject_consent_version=(
            invitation.consent_version if invitation is not None else None
        ),
    )
    db.commit()
    _clear_cookie(
        response,
        key=CEREMONY_COOKIE,
        path=MENTOR_COOKIE_PATH,
        same_site="strict",
    )
    _set_cookie(
        response,
        key=CEREMONY_COOKIE,
        token=rotated_token,
        max_age=max(1, int((_utc(ceremony.expires_at) - now).total_seconds())),
        path=MENTOR_COOKIE_PATH,
        same_site="strict",
    )
    _headers(response)
    return result


def exchange(db: Session, request: Request, response: Response, idempotency_key: str | None, body: Any) -> dict[str, Any]:
    _lock_authority_scope(db, request, fallback="ceremony-exchange")
    payload = _body(body)
    _lock_deletion_ceremony_source_first(db, request)
    ceremony = _find_exchange_ceremony(db, request)
    _reject_conflicting_session_class(db, request)
    record, replay = _begin_idempotency(db, operation="exchange", binding=f"ceremony:{ceremony.id}:g{ceremony.generation}", idempotency_key=idempotency_key, payload=payload)
    if replay is not None:
        _clear_cookie(response, key=CEREMONY_COOKIE, path=MENTOR_COOKIE_PATH, same_site="strict")
        return _replay(db, response, replay)
    if ceremony.state != "proof_verified" or payload.get("intent") != ceremony.intent:
        db.rollback()
        raise MentorCeremonyError(409, "CONCURRENT_STATE_CHANGED")
    now = _now()
    _consume_rate_budget(
        db,
        request=request,
        operation="exchange",
        binding=f"ceremony:{ceremony.id}:g{ceremony.generation}",
        now=now,
    )
    user, owner_sessions, mentor_sessions = _lock_actor_session_classes(
        db,
        ceremony.actor_user_id
        if ceremony.actor_user_id is not None
        else uuid.UUID(int=0),
    )
    if any(row.status == "active" for row in owner_sessions):
        db.rollback()
        raise MentorCeremonyError(409, "SESSION_CONFLICT")
    user, profile, proof = _current_proof(db, ceremony, now)
    if ceremony.intent == "mentor_session":
        invitation = _locked_row(db, MentorInvitation, ceremony.invitation_id)
        if (
            invitation is None
            or invitation.state != "pending"
            or payload.get("acceptPurpose") is not True
            or payload.get("purposeCode") != invitation.purpose_code
            or payload.get("consentReceiptVersion") != invitation.consent_version
            or payload.get("acceptanceTextVersion") != invitation.acceptance_text_version
            or _utc(invitation.expires_at) <= now
        ):
            db.rollback()
            raise MentorCeremonyError(403, "AUTHORIZATION_DENIED")
        subject_consent = _validate_invitation_consent(db, invitation, now)
        engagement = MentorEngagement(
            invitation_id=invitation.id,
            subject_registration_id=invitation.subject_registration_id,
            mentor_user_id=user.id,
            tutor_profile_id=profile.id,
            authority_domain_hash=invitation.authority_domain_hash,
            purpose_code=invitation.purpose_code,
            state="active",
            activated_at=now,
        )
        db.add(engagement)
        db.flush()
        if not _subject_sharing_allowed(db, engagement):
            db.rollback()
            raise MentorCeremonyError(403, "AUTHORIZATION_DENIED")
        consent = MentorConsent(
            engagement_id=engagement.id,
            purpose_code=invitation.purpose_code,
            version=invitation.consent_version,
            disclosure_classes=list(invitation.disclosure_classes),
            status="granted",
            recorded_at=now,
        )
        db.add(consent)
        db.flush()
        active_sessions = [
            row for row in mentor_sessions if row.state == "active"
        ]
        active_same_purpose = [
            row
            for row in active_sessions
            if row.purpose_code == invitation.purpose_code
        ]
        if active_same_purpose and not ceremony.recovery:
            db.rollback()
            raise MentorCeremonyError(409, "SESSION_CONFLICT")
        if ceremony.recovery:
            marked = set(
                (ceremony.metadata_json or {}).get(
                    "mandatoryRevocationSessionIds", []
                )
            )
            prior = [row for row in mentor_sessions if str(row.id) in marked]
            # Recovery is actor/profile-global, not purpose-local.  Verification
            # snapshots every live generation without revoking it.  Exchange
            # may proceed only when that exact snapshot is still the complete
            # active set; a session minted or rotated under any other purpose
            # after verification makes the recovery decision stale.
            if (
                any(row.state != "active" for row in prior)
                or {str(row.id) for row in active_sessions} != marked
                or len(prior) != len(marked)
            ):
                db.rollback()
                raise MentorCeremonyError(409, "CONCURRENT_STATE_CHANGED")
            for predecessor in prior:
                predecessor.state = "revoked"
                predecessor.terminal_at = now
        next_generation = 1
        if ceremony.recovery:
            next_generation = max(
                (row.generation for row in mentor_sessions), default=0
            ) + 1
            if next_generation > settings.mentor_session_max_generation:
                db.rollback()
                raise MentorCeremonyError(429, "RATE_LIMITED", retryable=False)
        mentor_session_id = uuid.uuid4()
        raw_token, token_seed_ct, token_seed_key_version = _new_seeded_token(
            "session", mentor_session_id, next_generation
        )
        slices = [
            mapped
            for item in invitation.disclosure_classes
            if (mapped := _DISCLOSURE_TO_SLICE.get(item)) is not None
        ]
        mentor_session = MentorSession(
            id=mentor_session_id,
            ceremony_id=ceremony.id,
            engagement_id=engagement.id,
            actor_user_id=user.id,
            tutor_profile_id=profile.id,
            ownership_proof_id=proof.id,
            consent_id=consent.id,
            subject_consent_id=subject_consent.id,
            authority_domain_hash=invitation.authority_domain_hash,
            token_hash=_token_hash(raw_token),
            token_seed_ct=token_seed_ct,
            token_seed_key_version=token_seed_key_version,
            mentor_role=ceremony.requested_role or "tutor",
            purpose_code=invitation.purpose_code,
            scopes=list(_PURPOSE_SCOPES[invitation.purpose_code]),
            permitted_profile_slices=slices,
            state="active",
            generation=next_generation,
            issued_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(seconds=settings.mentor_session_absolute_ttl_seconds),
        )
        db.add(mentor_session)
        invitation.state = "accepted"
        invitation.accepted_at = now
        ceremony.state = "exchanged"
        ceremony.terminal_at = now
        db.flush()
        result = _session_projection(db, mentor_session, touch=False)
        status_code = 201
        _set_cookie(response, key=SESSION_COOKIE, token=raw_token, max_age=settings.mentor_session_absolute_ttl_seconds, path="/", same_site="lax")
        _audit(
            db,
            action="mentor.acceptance.recorded",
            state="accepted",
            generation=next_generation,
            actor_user_id=user.id,
            authority_domain_hash=invitation.authority_domain_hash,
            purpose_code=invitation.purpose_code,
            policy_version=proof.policy_version,
            subject_consent_version=subject_consent.version,
            mentor_consent_version=consent.version,
        )
        _audit(
            db,
            action="mentor.session.issued",
            state="active",
            generation=next_generation,
            actor_user_id=user.id,
            authority_domain_hash=invitation.authority_domain_hash,
            purpose_code=invitation.purpose_code,
            policy_version=proof.policy_version,
            subject_consent_version=subject_consent.version,
            mentor_consent_version=consent.version,
        )
    else:
        live = _session_from_cookie(db, request)
        if (
            live.actor_user_id != user.id
            or live.tutor_profile_id != profile.id
            or payload.get("acceptAuthorityDeletionStepUp") is not True
            or payload.get("acceptanceTextVersion")
            != ceremony.privacy_notice_version
        ):
            db.rollback()
            raise MentorCeremonyError(403, "AUTHORIZATION_DENIED")
        step_up_id = uuid.uuid4()
        raw_token, token_seed_ct, token_seed_key_version = _new_seeded_token(
            "step-up", step_up_id
        )
        step_up = MentorAuthorityStepUp(
            id=step_up_id,
            ceremony_id=ceremony.id,
            actor_user_id=user.id,
            mentor_session_id=live.id,
            token_hash=_token_hash(raw_token),
            token_seed_ct=token_seed_ct,
            token_seed_key_version=token_seed_key_version,
            intent="authority_deletion_step_up",
            fingerprint=_fingerprint(
                "delete-authority",
                {
                    "actor": str(user.id),
                    "sessionGeneration": live.generation,
                    "retentionNoticeVersion": settings.mentor_retention_notice_version,
                },
            ),
            state="active",
            issued_at=now,
            expires_at=now + timedelta(seconds=settings.mentor_authority_step_up_ttl_seconds),
        )
        db.add(step_up)
        ceremony.state = "exchanged"
        ceremony.terminal_at = now
        result = {
            "schemaVersion": "mentor-authority-step-up.v1",
            "status": "step_up_ready",
            "intent": "authority_deletion_step_up",
            "deletionScope": "global_mentor_authority",
            "sameActorVerified": True,
            "verification": _verification(proof, now),
            "expiresInSeconds": settings.mentor_authority_step_up_ttl_seconds,
        }
        status_code = 200
        _set_cookie(response, key=STEP_UP_COOKIE, token=raw_token, max_age=settings.mentor_authority_step_up_ttl_seconds, path=STEP_UP_COOKIE_PATH, same_site="strict")
        _audit(
            db,
            action="mentor.authority.step_up_issued",
            state="active",
            actor_user_id=user.id,
            authority_domain_hash=live.authority_domain_hash,
            purpose_code=live.purpose_code,
            policy_version=proof.policy_version,
        )
    exchange_cookie_effects: list[dict[str, Any]] = [
        {
            "action": "clear",
            "key": CEREMONY_COOKIE,
            "path": MENTOR_COOKIE_PATH,
            "sameSite": "strict",
        },
    ]
    if ceremony.intent == "mentor_session":
        exchange_cookie_effects.append(
            {
                "action": "set",
                "key": SESSION_COOKIE,
                "kind": "session",
                "binding": str(mentor_session.id),
                "generation": mentor_session.generation,
                "maxAge": max(
                    1,
                    int((_utc(mentor_session.expires_at) - now).total_seconds()),
                ),
                "path": "/",
                "sameSite": "lax",
            }
        )
    else:
        exchange_cookie_effects.append(
            {
                "action": "set",
                "key": STEP_UP_COOKIE,
                "kind": "step-up",
                "binding": str(step_up.id),
                "generation": 1,
                "maxAge": settings.mentor_authority_step_up_ttl_seconds,
                "path": STEP_UP_COOKIE_PATH,
                "sameSite": "strict",
            }
        )
    _seal_idempotency(
        record,
        status_code,
        result,
        cookie_effects=exchange_cookie_effects,
    )
    db.commit()
    response.status_code = status_code
    _clear_cookie(response, key=CEREMONY_COOKIE, path=MENTOR_COOKIE_PATH, same_site="strict")
    _headers(response)
    return result


def read_session(db: Session, request: Request, response: Response) -> dict[str, Any]:
    _lock_authority_scope(db, request, fallback="session-read")
    _lock_presented_session_ceremony(db, request)
    owner_expiry_materialized = _reject_conflicting_session_class(db, request)
    session = _session_from_cookie(db, request)
    result = _session_projection(db, session, touch=False)
    # The sealed GET is a pure authority probe.  It may take read locks and
    # validate the graph, but cannot refresh idle authority or persist a rate
    # bucket merely because a SameSite=Lax cookie accompanied a top-level GET.
    if owner_expiry_materialized:
        db.commit()
    else:
        db.rollback()
    _headers(response)
    return result


def rotate(db: Session, request: Request, response: Response, idempotency_key: str | None, body: Any) -> dict[str, Any]:
    _lock_authority_scope(db, request, fallback="session-rotate")
    payload = _body(body)
    _lock_presented_session_ceremony(db, request)
    _reject_conflicting_session_class(db, request)
    predecessor = _session_from_cookie(db, request, allow_terminal=True)
    related_bindings = [
        f"session:{predecessor.id}:g{predecessor.generation}"
    ]
    if predecessor.state == "active":
        prior_generations = list(
            db.scalars(
                select(MentorSession)
                .where(MentorSession.successor_id == predecessor.id)
                .order_by(MentorSession.id)
                .with_for_update()
            )
        )
        related_bindings.extend(
            f"session:{row.id}:g{row.generation}" for row in prior_generations
        )
    existing = _existing_idempotency(
        db,
        operation="rotate",
        bindings=related_bindings,
        idempotency_key=idempotency_key,
        payload=payload,
    )
    if existing is not None:
        # Repeating the set effect is safe (the successor token is a
        # server-secret PRF over the committed row) and is required when the
        # caller restored the predecessor cookie after losing the response.
        return _replay(db, response, existing[1])
    record, replay = _begin_idempotency(db, operation="rotate", binding=f"session:{predecessor.id}:g{predecessor.generation}", idempotency_key=idempotency_key, payload=payload)
    if replay is not None:
        _clear_cookie(response, key=SESSION_COOKIE, path="/", same_site="lax")
        return _replay(db, response, replay)
    _consume_rate_budget(
        db,
        request=request,
        operation="rotate",
        binding=(
            f"authority:{predecessor.actor_user_id}:"
            f"{predecessor.authority_domain_hash}"
        ),
    )
    if predecessor.state != "active":
        db.rollback()
        raise MentorCeremonyError(410, "AUTHORITY_TERMINAL")
    if payload.get("purposeCode") != predecessor.purpose_code:
        db.rollback()
        raise MentorCeremonyError(409, "SESSION_STALE")
    if predecessor.generation >= settings.mentor_session_max_generation:
        db.rollback()
        raise MentorCeremonyError(429, "RATE_LIMITED", retryable=False)
    now = _now()
    _validate_live_session_graph(db, predecessor, now)
    successor_id = uuid.uuid4()
    raw_token, token_seed_ct, token_seed_key_version = _new_seeded_token(
        "session", successor_id, predecessor.generation + 1
    )
    predecessor.state = "rotated_out"
    predecessor.terminal_at = now
    # Retire the predecessor's partial-unique authority before inserting the
    # successor. Both statements remain in this transaction; the self-FK is
    # bound only once the successor row exists.
    db.flush()
    successor = MentorSession(
        ceremony_id=predecessor.ceremony_id,
        id=successor_id,
        engagement_id=predecessor.engagement_id,
        actor_user_id=predecessor.actor_user_id,
        tutor_profile_id=predecessor.tutor_profile_id,
        ownership_proof_id=predecessor.ownership_proof_id,
        consent_id=predecessor.consent_id,
        subject_consent_id=predecessor.subject_consent_id,
        authority_domain_hash=predecessor.authority_domain_hash,
        token_hash=_token_hash(raw_token),
        token_seed_ct=token_seed_ct,
        token_seed_key_version=token_seed_key_version,
        mentor_role=predecessor.mentor_role,
        purpose_code=predecessor.purpose_code,
        scopes=list(predecessor.scopes),
        permitted_profile_slices=list(predecessor.permitted_profile_slices),
        state="active",
        generation=predecessor.generation + 1,
        issued_at=now,
        last_seen_at=now,
        expires_at=min(_utc(predecessor.expires_at), now + timedelta(seconds=settings.mentor_session_absolute_ttl_seconds)),
    )
    db.add(successor)
    db.flush()
    predecessor.successor_id = successor.id
    result = _session_projection(db, successor, touch=False)
    _seal_idempotency(
        record,
        200,
        result,
        cookie_effects=[
            {
                "action": "clear",
                "key": SESSION_COOKIE,
                "path": "/",
                "sameSite": "lax",
            },
            {
                "action": "set",
                "key": SESSION_COOKIE,
                "kind": "session",
                "binding": str(successor.id),
                "generation": successor.generation,
                "maxAge": max(
                    1, int((_utc(successor.expires_at) - now).total_seconds())
                ),
                "path": "/",
                "sameSite": "lax",
            },
        ],
    )
    _audit(
        db,
        action="mentor.session.rotated",
        state="rotated_out",
        generation=predecessor.generation,
        actor_user_id=predecessor.actor_user_id,
        authority_domain_hash=predecessor.authority_domain_hash,
        purpose_code=predecessor.purpose_code,
    )
    db.commit()
    _clear_cookie(response, key=SESSION_COOKIE, path="/", same_site="lax")
    _set_cookie(response, key=SESSION_COOKIE, token=raw_token, max_age=max(1, int((_utc(successor.expires_at) - now).total_seconds())), path="/", same_site="lax")
    _headers(response)
    return result


def _retirement_target_from_presented_generation(
    db: Session,
    presented: MentorSession,
) -> MentorSession:
    """Follow an already-committed rotation chain to its effective authority.

    A revoke/logout request may have captured generation N immediately before
    a concurrent rotate commits generation N+1.  Both operations share the
    actor advisory lock, so the loser must reread and retire the successor—not
    mistake the now-terminal predecessor for the absence of authority.
    """

    current = presented
    visited = {current.id}
    while current.state == "rotated_out":
        if current.successor_id is None or current.successor_id in visited:
            raise MentorCeremonyError(
                409, "CONCURRENT_STATE_CHANGED", retryable=True
            )
        successor = db.scalar(
            select(MentorSession)
            .where(MentorSession.id == current.successor_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            successor is None
            or successor.actor_user_id != current.actor_user_id
            or successor.authority_domain_hash != current.authority_domain_hash
            or successor.purpose_code != current.purpose_code
            or successor.mentor_role != current.mentor_role
            or successor.ceremony_id != current.ceremony_id
            or successor.engagement_id != current.engagement_id
            or successor.tutor_profile_id != current.tutor_profile_id
            or successor.ownership_proof_id != current.ownership_proof_id
            or successor.consent_id != current.consent_id
            or successor.subject_consent_id != current.subject_consent_id
            or successor.generation != current.generation + 1
        ):
            raise MentorCeremonyError(
                409, "CONCURRENT_STATE_CHANGED", retryable=True
            )
        visited.add(successor.id)
        current = successor
    return current


def _end_session(db: Session, request: Request, response: Response, idempotency_key: str | None, body: Any, *, operation: str, state: str, action: str) -> dict[str, Any]:
    _lock_authority_scope(db, request, fallback=f"session-{operation}")
    payload = _body(body)
    _lock_presented_session_ceremony(db, request)
    presented_session = _session_from_cookie(
        db,
        request,
        allow_terminal=True,
        allow_owner_conflict_for_retirement=True,
    )
    session = _retirement_target_from_presented_generation(db, presented_session)
    record, replay = _begin_idempotency(
        db,
        operation=operation,
        binding=(
            f"session:{presented_session.id}:g{presented_session.generation}"
        ),
        idempotency_key=idempotency_key,
        payload=payload,
    )
    if replay is not None:
        _clear_cookie(response, key=SESSION_COOKIE, path="/", same_site="lax")
        return _replay(db, response, replay)
    _consume_rate_budget(
        db,
        request=request,
        operation=operation,
        binding=f"session:{session.id}:g{session.generation}",
    )
    if session.state != "active":
        db.rollback()
        raise MentorCeremonyError(410, "AUTHORITY_TERMINAL")
    if payload.get("purposeCode") != session.purpose_code:
        db.rollback()
        raise MentorCeremonyError(409, "SESSION_STALE")
    now = _now()
    session.state = state
    session.terminal_at = now
    candidate_ceremonies = list(
        db.scalars(
            select(MentorCeremony)
            .where(
                MentorCeremony.actor_user_id == session.actor_user_id,
                MentorCeremony.intent == "authority_deletion_step_up",
                MentorCeremony.state.in_(
                    ("pending_invitation", "challenge_issued", "proof_verified")
                ),
            )
            .order_by(MentorCeremony.id)
            .with_for_update()
        )
    )
    # Revoke only deletion ceremony authority derived from the presented
    # session.  Actor-wide retirement would silently terminate an unrelated
    # purpose session and violates the targeted revoke/logout contract.
    ceremonies = [
        ceremony
        for ceremony in candidate_ceremonies
        if (ceremony.metadata_json or {}).get("mentorSessionId")
        == str(session.id)
    ]
    for ceremony in ceremonies:
        ceremony.state = "revoked"
        ceremony.terminal_at = now
    provider_rows = list(
        db.scalars(
            select(MentorProviderResult)
            .where(
                MentorProviderResult.ceremony_id.in_(
                    [row.id for row in ceremonies] or [uuid.UUID(int=0)]
                ),
                MentorProviderResult.state.in_(("pending", "verified")),
            )
            .order_by(MentorProviderResult.id)
            .with_for_update()
        )
    )
    for provider in provider_rows:
        provider.state = "rejected"
        provider.consumed_at = now
    step_ups = list(
        db.scalars(
            select(MentorAuthorityStepUp)
            .where(
                MentorAuthorityStepUp.mentor_session_id == session.id,
                MentorAuthorityStepUp.state == "active",
            )
            .order_by(MentorAuthorityStepUp.id)
            .with_for_update()
        )
    )
    for step_up in step_ups:
        step_up.state = "revoked"
        step_up.consumed_at = now
    result = {
        "schemaVersion": "mentor-lifecycle.v1",
        "action": action,
        "state": state,
        "sessionAuthorityPresent": False,
        "auditEventRecorded": True,
        "effectiveAt": now.isoformat(),
    }
    _seal_idempotency(
        record,
        200,
        result,
        cookie_effects=[
            {
                "action": "clear",
                "key": SESSION_COOKIE,
                "path": "/",
                "sameSite": "lax",
            },
            {
                "action": "clear",
                "key": CEREMONY_COOKIE,
                "path": MENTOR_COOKIE_PATH,
                "sameSite": "strict",
            },
            {
                "action": "clear",
                "key": STEP_UP_COOKIE,
                "path": STEP_UP_COOKIE_PATH,
                "sameSite": "strict",
            },
        ],
    )
    _audit(
        db,
        action=f"mentor.session.{operation}",
        state=state,
        generation=session.generation,
        actor_user_id=session.actor_user_id,
        authority_domain_hash=session.authority_domain_hash,
        purpose_code=session.purpose_code,
    )
    db.commit()
    _clear_cookie(response, key=SESSION_COOKIE, path="/", same_site="lax")
    _clear_cookie(response, key=CEREMONY_COOKIE, path=MENTOR_COOKIE_PATH, same_site="strict")
    _clear_cookie(response, key=STEP_UP_COOKIE, path=STEP_UP_COOKIE_PATH, same_site="strict")
    _headers(response)
    return result


def revoke(db: Session, request: Request, response: Response, idempotency_key: str | None, body: Any) -> dict[str, Any]:
    return _end_session(db, request, response, idempotency_key, body, operation="revoke", state="revoked", action="revoked")


def logout(db: Session, request: Request, response: Response, idempotency_key: str | None, body: Any) -> dict[str, Any]:
    return _end_session(db, request, response, idempotency_key, body, operation="logout", state="logged_out", action="logged_out")


def recover(db: Session, request: Request, response: Response, idempotency_key: str | None, body: Any) -> dict[str, Any]:
    _lock_authority_scope(db, request, fallback="ceremony-recover")
    payload = _body(body)
    live = None
    bootstrap_row = None
    now = _now()
    if payload.get("intent") == "authority_deletion_step_up":
        if payload.get("stepUpNoticeVersion") != settings.mentor_authority_step_up_notice_version:
            raise MentorCeremonyError(400, "INVALID_REQUEST", field="request")
        _lock_presented_session_ceremony(db, request)
        live = _session_from_cookie(db, request)
        binding = f"session:{live.id}:g{live.generation}"
        requested_role = live.mentor_role
        purpose_code = live.purpose_code
    else:
        if payload.get("privacyNoticeVersion") != settings.mentor_privacy_notice_version:
            raise MentorCeremonyError(400, "INVALID_REQUEST", field="request")
        _reject_conflicting_session_class(db, request)
        bootstrap = request.cookies.get(BOOTSTRAP_COOKIE)
        if not bootstrap:
            raise MentorCeremonyError(401, "AUTHENTICATION_REQUIRED")
        bootstrap_row = db.scalar(
            select(MentorBootstrapAttempt)
            .where(MentorBootstrapAttempt.token_hash == _token_hash(bootstrap))
            .with_for_update()
        )
        if (
            bootstrap_row is None
            or bootstrap_row.state not in {"active", "consumed"}
            or bootstrap_row.deleted_at is not None
            or (
                bootstrap_row.state == "active"
                and _utc(bootstrap_row.expires_at) <= now
            )
        ):
            raise MentorCeremonyError(410, "AUTHORITY_TERMINAL")
        requested_role = payload["requestedMentorRole"]
        purpose_code = payload["purposeCode"]
        binding = f"bootstrap:{bootstrap_row.id}"
    record, replay = _begin_idempotency(db, operation="recover", binding=binding, idempotency_key=idempotency_key, payload=payload)
    if replay is not None:
        return _replay(db, response, replay)
    _consume_rate_budget(
        db,
        request=request,
        operation="recover",
        binding=binding,
        now=now,
    )
    if bootstrap_row is not None and bootstrap_row.state != "active":
        db.rollback()
        raise MentorCeremonyError(409, "CEREMONY_REPLAYED")
    ceremony_id = uuid.uuid4()
    raw_token, token_seed_ct, token_seed_key_version = _new_seeded_token(
        "ceremony", ceremony_id
    )
    raw_nonce = _random_token()
    raw_correlation = _random_token()
    ceremony = MentorCeremony(
        id=ceremony_id,
        bootstrap_attempt_id=bootstrap_row.id if bootstrap_row is not None else None,
        token_hash=_token_hash(raw_token),
        token_seed_ct=token_seed_ct,
        token_seed_key_version=token_seed_key_version,
        challenge_hash=keyed_hash(raw_nonce),
        intent=payload["intent"],
        requested_role=requested_role,
        purpose_code=purpose_code,
        privacy_notice_version=payload.get("privacyNoticeVersion") or payload.get("stepUpNoticeVersion"),
        state="challenge_issued",
        generation=1,
        actor_user_id=live.actor_user_id if live else None,
        tutor_profile_id=live.tutor_profile_id if live else None,
        ownership_proof_id=live.ownership_proof_id if live else None,
        recovery=True,
        metadata_json=(
            {"mentorSessionId": str(live.id)} if live is not None else None
        ),
        expires_at=now + timedelta(seconds=settings.mentor_ceremony_ttl_seconds),
    )
    db.add(ceremony)
    db.flush()
    _add_provider_transaction(
        db,
        ceremony=ceremony,
        requested_role=requested_role,
        raw_nonce=raw_nonce,
        raw_correlation=raw_correlation,
    )
    if bootstrap_row is not None:
        bootstrap_row.state = "consumed"
        bootstrap_row.consumed_at = now
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "accepted",
        "ceremonyState": "challenge_issued",
        "next": "external_identity",
        "intent": payload["intent"],
        "expiresInSeconds": settings.mentor_ceremony_ttl_seconds,
    }
    cookie_effects = [
        {
            "action": "set",
            "key": CEREMONY_COOKIE,
            "kind": "ceremony",
            "binding": str(ceremony.id),
            "generation": ceremony.generation,
            "maxAge": settings.mentor_ceremony_ttl_seconds,
            "path": MENTOR_COOKIE_PATH,
            "sameSite": "strict",
        }
    ]
    if bootstrap_row is not None:
        cookie_effects.insert(
            0,
            {
                "action": "clear",
                "key": BOOTSTRAP_COOKIE,
                "path": MENTOR_COOKIE_PATH,
                "sameSite": "strict",
            },
        )
    _seal_idempotency(
        record,
        202,
        result,
        cookie_effects=cookie_effects,
    )
    _audit(db, action="mentor.ceremony.recovery_started", state="challenge_issued")
    db.commit()
    response.status_code = 202
    if bootstrap_row is not None:
        _clear_cookie(
            response,
            key=BOOTSTRAP_COOKIE,
            path=MENTOR_COOKIE_PATH,
            same_site="strict",
        )
    _set_cookie(response, key=CEREMONY_COOKIE, token=raw_token, max_age=settings.mentor_ceremony_ttl_seconds, path=MENTOR_COOKIE_PATH, same_site="strict")
    _headers(response)
    return result


def delete_authority(db: Session, request: Request, response: Response, idempotency_key: str | None, body: Any) -> dict[str, Any]:
    _lock_authority_scope(db, request, fallback="authority-delete")
    payload = _body(body)
    _lock_presented_session_ceremony(db, request)
    session = _session_from_cookie(db, request, allow_terminal=True)
    raw_step_up = request.cookies.get(STEP_UP_COOKIE)
    if not raw_step_up:
        raise MentorCeremonyError(403, "STEP_UP_REQUIRED")
    step_up = db.scalar(select(MentorAuthorityStepUp).where(MentorAuthorityStepUp.token_hash == _token_hash(raw_step_up)).with_for_update())
    now = _now()
    if step_up is None:
        raise MentorCeremonyError(410, "STEP_UP_EXPIRED")
    if step_up.actor_user_id != session.actor_user_id or step_up.mentor_session_id != session.id:
        raise MentorCeremonyError(403, "AUTHORIZATION_DENIED")
    record, replay = _begin_idempotency(
        db,
        operation="delete-authority",
        binding=f"session:{session.id}:g{session.generation}:step:{step_up.id}",
        idempotency_key=idempotency_key,
        payload=payload,
    )
    if replay is not None:
        _clear_cookie(response, key=SESSION_COOKIE, path="/", same_site="lax")
        _clear_cookie(response, key=STEP_UP_COOKIE, path=STEP_UP_COOKIE_PATH, same_site="strict")
        return _replay(db, response, replay)
    _consume_rate_budget(
        db,
        request=request,
        operation="delete-authority",
        binding=f"session:{session.id}:g{session.generation}:step:{step_up.id}",
        now=now,
    )
    if (
        session.state != "active"
        or step_up.state != "active"
        or _utc(step_up.expires_at) <= now
    ):
        db.rollback()
        raise MentorCeremonyError(410, "STEP_UP_EXPIRED")
    _validate_live_session_graph(db, session, now)
    authority_proof = db.get(
        TutorProfileOwnershipProof, session.ownership_proof_id
    )
    if (
        authority_proof is None
        or authority_proof.state != "current"
        or authority_proof.deleted_at is not None
    ):
        raise MentorCeremonyError(403, "AUTHORIZATION_DENIED")
    # Only the revalidated proof bound to the presented live session may
    # discover pre-session authority.  Historical actor proofs can be retired
    # below, but their reusable provider-subject digests must never select a
    # different actor's current invitation or ceremony.
    authority_subject_hashes = [authority_proof.provider_subject_hash]
    expected_fingerprint = _fingerprint(
        "delete-authority",
        {
            "actor": str(session.actor_user_id),
            "sessionGeneration": session.generation,
            "retentionNoticeVersion": settings.mentor_retention_notice_version,
        },
    )
    if (
        payload.get("confirmation") != "delete_mentor_authority"
        or payload.get("retentionNoticeVersion")
        != settings.mentor_retention_notice_version
        or payload.get("expectedStepUpIntent")
        != "authority_deletion_step_up"
        or step_up.fingerprint != expected_fingerprint
    ):
        db.rollback()
        raise MentorCeremonyError(400, "INVALID_REQUEST", field="request")
    sessions = list(
        db.scalars(
            select(MentorSession)
            .where(MentorSession.actor_user_id == session.actor_user_id)
            .order_by(MentorSession.id)
            .with_for_update()
        )
    )
    for row in sessions:
        if row.state not in MENTOR_SESSION_TERMINAL_STATES or row.state == "rotated_out":
            row.state = "deleted"
            row.terminal_at = now
    proofs = list(db.scalars(select(TutorProfileOwnershipProof).where(TutorProfileOwnershipProof.user_id == session.actor_user_id).order_by(TutorProfileOwnershipProof.id).with_for_update()))
    for proof in proofs:
        proof.state = "deleted"
        proof.revoked_at = now
    engagements = list(db.scalars(select(MentorEngagement).where(MentorEngagement.mentor_user_id == session.actor_user_id).order_by(MentorEngagement.id).with_for_update()))
    engagement_ids = [row.id for row in engagements]
    invitation_ids = [row.invitation_id for row in engagements]
    mentor_consents = list(
        db.scalars(
            select(MentorConsent)
            .where(MentorConsent.engagement_id.in_(engagement_ids or [uuid.UUID(int=0)]))
            .order_by(MentorConsent.id)
            .with_for_update()
        )
    )
    invitations = list(
        db.scalars(
            select(MentorInvitation)
            .where(
                or_(
                    MentorInvitation.id.in_(
                        invitation_ids or [uuid.UUID(int=0)]
                    ),
                    MentorInvitation.mentor_match_hash.in_(
                        authority_subject_hashes
                    ),
                )
            )
            .order_by(MentorInvitation.id)
            .with_for_update()
        )
    )
    invitation_ids = sorted({row.id for row in invitations})
    subject_consents = list(
        db.scalars(
            select(MentorSubjectConsent)
            .where(MentorSubjectConsent.invitation_id.in_(invitation_ids or [uuid.UUID(int=0)]))
            .order_by(MentorSubjectConsent.id)
            .with_for_update()
        )
    )
    # PostgreSQL cannot apply an unqualified ``FOR UPDATE`` to the nullable
    # side of an outer join.  Select provider-bound ceremony ids in a subquery
    # and lock only the authoritative ceremony rows.  Provider rows are locked
    # independently below before any of their protected fields are retired.
    provider_bound_ceremonies = select(
        MentorProviderResult.ceremony_id
    ).where(
        MentorProviderResult.provider_subject_hash.in_(
            authority_subject_hashes
        )
    )
    ceremonies = list(
        db.scalars(
            select(MentorCeremony)
            .where(
                or_(
                    MentorCeremony.actor_user_id == session.actor_user_id,
                    MentorCeremony.id.in_(provider_bound_ceremonies),
                )
            )
            .order_by(MentorCeremony.id)
            .with_for_update()
        )
    )
    ceremony_ids = [row.id for row in ceremonies]
    bootstrap_ids = [
        row.bootstrap_attempt_id
        for row in ceremonies
        if row.bootstrap_attempt_id is not None
    ]
    bootstrap_attempts = list(
        db.scalars(
            select(MentorBootstrapAttempt)
            .where(
                MentorBootstrapAttempt.id.in_(
                    bootstrap_ids or [uuid.UUID(int=0)]
                )
            )
            .order_by(MentorBootstrapAttempt.id)
            .with_for_update()
        )
    )
    provider_results = list(
        db.scalars(
            select(MentorProviderResult)
            .where(MentorProviderResult.ceremony_id.in_(ceremony_ids or [uuid.UUID(int=0)]))
            .order_by(MentorProviderResult.id)
            .with_for_update()
        )
    )
    step_ups = list(
        db.scalars(
            select(MentorAuthorityStepUp)
            .where(MentorAuthorityStepUp.actor_user_id == session.actor_user_id)
            .order_by(MentorAuthorityStepUp.id)
            .with_for_update()
        )
    )
    for engagement in engagements:
        engagement.state = "deleted"
        engagement.terminal_at = now
    for consent in mentor_consents:
        consent.status = "deleted"
        consent.revoked_at = now
    for consent in subject_consents:
        consent.status = "deleted"
        consent.revoked_at = now
    for invitation in invitations:
        invitation.state = "deleted"
        invitation.terminal_at = now
    for ceremony in ceremonies:
        ceremony.state = "deleted"
        ceremony.terminal_at = now
    for provider in provider_results:
        if provider.state in {"pending", "verified"}:
            provider.state = "rejected"
            provider.consumed_at = now
        provider.nonce_ct = encrypt("")
        provider.correlation_ct = encrypt("")
        provider.nonce_hash = keyed_hash("")
        provider.correlation_hash = keyed_hash("")
    for bootstrap in bootstrap_attempts:
        bootstrap.state = "expired"
        bootstrap.consumed_at = bootstrap.consumed_at or now
    for candidate in step_ups:
        candidate.state = "consumed" if candidate.id == step_up.id else "deleted"
        candidate.consumed_at = now
    audit_link_hashes = {
        keyed_hash(f"mentor-audit-link:v1:{row.authority_domain_hash}")
        for row in sessions
    }
    audit_links = list(
        db.scalars(
            select(MentorAuditLink)
            .where(MentorAuditLink.correlation_hash.in_(audit_link_hashes))
            .order_by(MentorAuditLink.id)
            .with_for_update()
        )
    ) if audit_link_hashes else []
    for link in audit_links:
        link.link_key_ct = None
        link.actor_link_ct = None
        link.key_version = None
        link.erased_at = now
    result = {
        "schemaVersion": "mentor-lifecycle.v1",
        "action": "authority_deletion_scheduled",
        "state": "deletion_pending",
        "sessionAuthorityPresent": False,
        "stepUpAuthorityPresent": False,
        "auditEventRecorded": True,
        "effectiveAt": now.isoformat(),
    }
    _seal_idempotency(
        record,
        202,
        result,
        cookie_effects=[
            {
                "action": "clear",
                "key": SESSION_COOKIE,
                "path": "/",
                "sameSite": "lax",
            },
            {
                "action": "clear",
                "key": CEREMONY_COOKIE,
                "path": MENTOR_COOKIE_PATH,
                "sameSite": "strict",
            },
            {
                "action": "clear",
                "key": STEP_UP_COOKIE,
                "path": STEP_UP_COOKIE_PATH,
                "sameSite": "strict",
            },
            {
                "action": "clear",
                "key": BOOTSTRAP_COOKIE,
                "path": MENTOR_COOKIE_PATH,
                "sameSite": "strict",
            },
        ],
    )
    _audit(
        db,
        action="mentor.authority.deletion_scheduled",
        state="deleted",
        generation=session.generation,
        # The deletion event is aggregate-only.  Existing reversible actor
        # links were destroyed above and this event must not create a new one.
        actor_user_id=None,
        authority_domain_hash=session.authority_domain_hash,
        purpose_code=session.purpose_code,
    )
    db.commit()
    response.status_code = 202
    _clear_cookie(response, key=SESSION_COOKIE, path="/", same_site="lax")
    _clear_cookie(response, key=CEREMONY_COOKIE, path=MENTOR_COOKIE_PATH, same_site="strict")
    _clear_cookie(response, key=STEP_UP_COOKIE, path=STEP_UP_COOKIE_PATH, same_site="strict")
    _clear_cookie(response, key=BOOTSTRAP_COOKIE, path=MENTOR_COOKIE_PATH, same_site="strict")
    _headers(response)
    return result


def lock_subject_mentor_erasure_boundary(
    db: Session,
    subject_registration_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> SubjectMentorErasureBoundary:
    """Prelock every mentor authority scope before registration erasure locks.

    Discovery is deliberately non-authorizing.  The returned marker proves
    only that the transaction acquired the stable subject, mentor-actor and
    domain advisory locks in deterministic order; the complete graph is read
    again with row locks by ``retire_subject_mentor_authority``.
    """

    current = _utc(now or _now())
    registration_discovery = db.execute(
        select(
            StudentRegistration.user_id,
            StudentRegistration.updated_at,
        ).where(
            StudentRegistration.id == subject_registration_id
        )
    ).one_or_none()
    if registration_discovery is None:
        raise MentorCeremonyError(409, "CONCURRENT_STATE_CHANGED", retryable=True)
    subject_user_id, registration_updated_at = registration_discovery
    domains = set(
        db.scalars(
            select(MentorInvitation.authority_domain_hash).where(
                MentorInvitation.subject_registration_id
                == subject_registration_id,
                MentorInvitation.deleted_at.is_(None),
            )
        )
    )
    domains.update(
        db.scalars(
            select(MentorEngagement.authority_domain_hash).where(
                MentorEngagement.subject_registration_id
                == subject_registration_id,
                MentorEngagement.deleted_at.is_(None),
            )
        )
    )
    domains.update(
        db.scalars(
            select(MentorInvitation.authority_domain_hash)
            .join(
                MentorSubjectConsent,
                MentorSubjectConsent.invitation_id == MentorInvitation.id,
            )
            .where(
                MentorSubjectConsent.subject_registration_id
                == subject_registration_id,
                MentorSubjectConsent.deleted_at.is_(None),
                MentorInvitation.deleted_at.is_(None),
            )
        )
    )

    actor_ids: set[uuid.UUID] = set()
    if subject_user_id is not None:
        # Owner prerequisite creation takes this same actor lock before the
        # registration row, so no new subject graph can appear behind the
        # erasure inventory.
        actor_ids.add(subject_user_id)
    actor_ids.update(
        value
        for value in db.scalars(
            select(MentorEngagement.mentor_user_id).where(
                MentorEngagement.subject_registration_id
                == subject_registration_id,
                MentorEngagement.mentor_user_id.is_not(None),
                MentorEngagement.deleted_at.is_(None),
            )
        )
        if value is not None
    )
    actor_ids.update(
        value
        for value in db.scalars(
            select(MentorSession.actor_user_id)
            .join(
                MentorEngagement,
                MentorSession.engagement_id == MentorEngagement.id,
            )
            .where(
                MentorEngagement.subject_registration_id
                == subject_registration_id,
                MentorSession.actor_user_id.is_not(None),
                MentorSession.deleted_at.is_(None),
            )
        )
        if value is not None
    )
    actor_ids.update(
        value
        for value in db.scalars(
            select(MentorCeremony.actor_user_id)
            .join(
                MentorInvitation,
                MentorCeremony.invitation_id == MentorInvitation.id,
            )
            .where(
                MentorInvitation.subject_registration_id
                == subject_registration_id,
                MentorCeremony.actor_user_id.is_not(None),
                MentorCeremony.deleted_at.is_(None),
                MentorInvitation.deleted_at.is_(None),
            )
        )
        if value is not None
    )
    mentor_matches = set(
        db.scalars(
            select(MentorInvitation.mentor_match_hash).where(
                MentorInvitation.subject_registration_id
                == subject_registration_id,
                MentorInvitation.deleted_at.is_(None),
            )
        )
    )
    if mentor_matches:
        actor_ids.update(
            value
            for value in db.scalars(
                select(TutorProfileOwnershipProof.user_id).where(
                    TutorProfileOwnershipProof.provider_subject_hash.in_(
                        mentor_matches
                    ),
                    TutorProfileOwnershipProof.state == "current",
                    TutorProfileOwnershipProof.deleted_at.is_(None),
                    TutorProfileOwnershipProof.user_id.is_not(None),
                )
            )
            if value is not None
        )

    ordered_actors = tuple(sorted(actor_ids, key=str))
    ordered_domains = tuple(sorted(domains))
    for actor_id in ordered_actors:
        _lock_authority_scope(
            db,
            actor_hint=actor_id,
            fallback=f"subject-erasure:{subject_registration_id}",
        )
    for authority_domain_hash in ordered_domains:
        _lock_authority_scope(
            db,
            fallback=f"authority-domain:{authority_domain_hash}",
        )
    policy_digest = _retention_policy_digest()
    inventory_digest = _boundary_inventory_digest(
        registration_id=subject_registration_id,
        subject_user_id=subject_user_id,
        registration_updated_at=registration_updated_at,
        authority_domains=ordered_domains,
        actor_ids=ordered_actors,
        policy_digest=policy_digest,
        current=current,
    )
    nonce = secrets.token_hex(32)
    boundary = SubjectMentorErasureBoundary(
        registration_id=subject_registration_id,
        subject_user_id=subject_user_id,
        registration_updated_at=registration_updated_at,
        authority_domains=ordered_domains,
        actor_ids=ordered_actors,
        policy_digest=policy_digest,
        inventory_digest=inventory_digest,
        current=current,
        _nonce=nonce,
        _guard=_SUBJECT_ERASURE_BOUNDARY_GUARD,
    )
    transaction = db.get_transaction()
    if transaction is None:
        raise RuntimeError("mentor erasure boundary requires a transaction")
    db.info.setdefault(_SUBJECT_ERASURE_STATE_KEY, {})[nonce] = {
        "boundary": boundary,
        "transaction": transaction,
        "consumed": False,
        "phase": "prelocked",
    }
    return boundary


def _retention_tombstone(label: str) -> str:
    """Return a non-recomputable, row/field-unique 64-hex tombstone."""

    return hashlib.sha256(
        secrets.token_bytes(32) + label.encode("ascii", errors="ignore")
    ).hexdigest()


def _retention_rows(
    db: Session,
    model: Any,
    *criteria: Any,
    limit: int,
    skip_locked: bool = True,
) -> list[Any]:
    if limit <= 0:
        return []
    return list(
        db.scalars(
            select(model)
            .where(*criteria)
            .order_by(model.id)
            .limit(limit)
            .with_for_update(skip_locked=skip_locked)
            .execution_options(populate_existing=True)
        )
    )


def _retention_graph_rows(
    db: Session,
    model: Any,
    *criteria: Any,
    limit: int,
) -> list[Any]:
    """Boundedly block for every selected graph row; never omit a held node."""

    return _retention_rows(
        db,
        model,
        *criteria,
        limit=limit,
        skip_locked=False,
    )


def _materialize_mentor_expirations(
    db: Session,
    *,
    current: datetime,
    limit: int,
) -> int:
    """Make elapsed live rows terminal before any retention-age decision."""

    changed = 0

    def room() -> int:
        return max(0, limit - changed)

    rows = _retention_rows(
        db,
        MentorBootstrapAttempt,
        MentorBootstrapAttempt.state == "active",
        MentorBootstrapAttempt.expires_at <= current,
        MentorBootstrapAttempt.deleted_at.is_(None),
        limit=room(),
    )
    for row in rows:
        row.state = "expired"
        row.consumed_at = row.expires_at
    changed += len(rows)

    rows = _retention_rows(
        db,
        MentorCeremony,
        MentorCeremony.state.in_(
            ("pending_invitation", "challenge_issued", "proof_verified")
        ),
        MentorCeremony.expires_at <= current,
        MentorCeremony.deleted_at.is_(None),
        limit=room(),
    )
    for row in rows:
        row.state = "expired"
        row.terminal_at = row.expires_at
    changed += len(rows)

    rows = _retention_rows(
        db,
        MentorProviderResult,
        MentorProviderResult.state.in_(("pending", "verified")),
        MentorProviderResult.expires_at <= current,
        MentorProviderResult.deleted_at.is_(None),
        limit=room(),
    )
    for row in rows:
        row.state = "expired"
        row.consumed_at = row.expires_at
    changed += len(rows)

    rows = _retention_rows(
        db,
        MentorInvitation,
        MentorInvitation.state.in_(("pending", "accepted")),
        MentorInvitation.expires_at <= current,
        MentorInvitation.deleted_at.is_(None),
        limit=room(),
    )
    for row in rows:
        row.state = "expired"
        row.terminal_at = row.expires_at
    changed += len(rows)

    rows = _retention_rows(
        db,
        MentorSubjectConsent,
        MentorSubjectConsent.status == "granted",
        MentorSubjectConsent.expires_at <= current,
        MentorSubjectConsent.deleted_at.is_(None),
        limit=room(),
    )
    for row in rows:
        row.status = "expired"
        row.revoked_at = row.expires_at
    changed += len(rows)

    rows = _retention_rows(
        db,
        TutorProfileOwnershipProof,
        TutorProfileOwnershipProof.state == "current",
        TutorProfileOwnershipProof.expires_at <= current,
        TutorProfileOwnershipProof.deleted_at.is_(None),
        limit=room(),
    )
    for row in rows:
        row.state = "expired"
        row.revoked_at = row.expires_at
    changed += len(rows)

    rows = _retention_rows(
        db,
        MentorSession,
        MentorSession.state == "active",
        or_(
            MentorSession.expires_at <= current,
            MentorSession.last_seen_at
            <= current
            - timedelta(seconds=settings.mentor_session_idle_ttl_seconds),
        ),
        MentorSession.deleted_at.is_(None),
        limit=room(),
    )
    for row in rows:
        row.state = "expired"
        row.terminal_at = _session_expiry_boundary(row)
    changed += len(rows)

    rows = _retention_rows(
        db,
        MentorAuthorityStepUp,
        MentorAuthorityStepUp.state == "active",
        MentorAuthorityStepUp.expires_at <= current,
        MentorAuthorityStepUp.deleted_at.is_(None),
        limit=room(),
    )
    for row in rows:
        row.state = "expired"
        row.consumed_at = row.expires_at
    changed += len(rows)

    # Once an invitation/subject grant has elapsed and no active session
    # remains, its dependent engagement/mentor-consent rows are no longer live.
    if room() > 0:
        engagements = _retention_rows(
            db,
            MentorEngagement,
            MentorEngagement.state.in_(("pending", "active")),
            MentorEngagement.deleted_at.is_(None),
            limit=room(),
        )
        for engagement in engagements:
            invitation = db.get(MentorInvitation, engagement.invitation_id)
            subject_consent = db.scalar(
                select(MentorSubjectConsent).where(
                    MentorSubjectConsent.invitation_id == engagement.invitation_id
                )
            )
            active_session = db.scalar(
                select(MentorSession.id).where(
                    MentorSession.engagement_id == engagement.id,
                    MentorSession.state == "active",
                )
            )
            if (
                active_session is None
                and (
                    invitation is None
                    or invitation.state not in {"pending", "accepted"}
                    or subject_consent is None
                    or subject_consent.status != "granted"
                )
            ):
                engagement.state = "expired"
                engagement.terminal_at = current
                changed += 1
                if changed >= limit:
                    break

    if room() > 0:
        consents = _retention_rows(
            db,
            MentorConsent,
            MentorConsent.status == "granted",
            MentorConsent.deleted_at.is_(None),
            limit=room(),
        )
        for consent in consents:
            engagement = db.get(MentorEngagement, consent.engagement_id)
            if engagement is None or engagement.state not in {"pending", "active"}:
                consent.status = "expired"
                consent.revoked_at = current
                changed += 1
                if changed >= limit:
                    break
    return changed


def _related_idempotency_scope_hashes(graph: dict[str, list[Any]]) -> set[str]:
    values: set[str] = set()
    for row in graph["invitations"]:
        values.add(
            _scope_hash(
                "owner-create-mentor-prerequisites",
                f"owner-invitation:{row.id}",
                {},
            )
        )
    for row in graph["bootstraps"]:
        binding = f"bootstrap:{row.id}"
        values.update(
            _scope_hash(operation, binding, {})
            for operation in ("initiate", "recover")
        )
    for row in graph["ceremonies"]:
        values.add(_scope_hash("verify", f"ceremony:{row.id}", {}))
        values.add(
            _scope_hash(
                "exchange", f"ceremony:{row.id}:g{row.generation}", {}
            )
        )
    for row in graph["sessions"]:
        binding = f"session:{row.id}:g{row.generation}"
        values.update(
            _scope_hash(operation, binding, {})
            for operation in ("rotate", "revoke", "logout", "recover")
        )
        for step_up in graph["step_ups"]:
            if step_up.mentor_session_id == row.id:
                values.add(
                    _scope_hash(
                        "delete-authority",
                        f"{binding}:step:{step_up.id}",
                        {},
                    )
                )
    return values


_RETENTION_GRAPH_KEYS = (
    "bootstraps",
    "invitations",
    "engagements",
    "sessions",
    "mentor_consents",
    "subject_consents",
    "step_ups",
    "ceremonies",
    "provider_results",
    "proofs",
    "idempotency",
    "audit_links",
)


def _empty_retention_graph() -> dict[str, list[Any]]:
    return {name: [] for name in _RETENTION_GRAPH_KEYS}


def _load_orphan_ceremony_graph(
    db: Session,
    ceremony_id: uuid.UUID,
    *,
    current: datetime,
) -> tuple[dict[str, list[Any]], int]:
    """Lock one complete pre-authority ceremony graph.

    A pre-proof ceremony has no actor/domain yet, so it cannot be discovered
    through the normal authority-domain scan.  The ceremony-scoped advisory
    lock is acquired by the caller before this bounded, blocking row-lock
    inventory.  Any evidence that the row joined an authority/session graph
    makes this helper return an empty graph for the domain worker to own.
    """

    graph = _empty_retention_graph()
    ceremonies = _retention_graph_rows(
        db,
        MentorCeremony,
        MentorCeremony.id == ceremony_id,
        MentorCeremony.deleted_at.is_(None),
        limit=2,
    )
    if len(ceremonies) != 1:
        return graph, 0
    ceremony = ceremonies[0]
    if ceremony.actor_user_id is not None or ceremony.invitation_id is not None:
        return graph, 0
    if db.scalar(
        select(MentorSession.id)
        .where(
            MentorSession.ceremony_id == ceremony.id,
            MentorSession.deleted_at.is_(None),
        )
        .limit(1)
    ) is not None or db.scalar(
        select(MentorAuthorityStepUp.id)
        .where(
            MentorAuthorityStepUp.ceremony_id == ceremony.id,
            MentorAuthorityStepUp.deleted_at.is_(None),
        )
        .limit(1)
    ) is not None:
        return graph, 0

    graph["ceremonies"] = ceremonies

    if ceremony.bootstrap_attempt_id is not None:
        graph["bootstraps"] = _retention_graph_rows(
            db,
            MentorBootstrapAttempt,
            MentorBootstrapAttempt.id == ceremony.bootstrap_attempt_id,
            MentorBootstrapAttempt.deleted_at.is_(None),
            limit=2,
        )

    graph["provider_results"] = _retention_graph_rows(
        db,
        MentorProviderResult,
        MentorProviderResult.ceremony_id == ceremony.id,
        MentorProviderResult.deleted_at.is_(None),
        limit=257,
    )

    scope_hashes = _related_idempotency_scope_hashes(graph)
    graph["idempotency"] = _retention_graph_rows(
        db,
        MentorIdempotencyRecord,
        MentorIdempotencyRecord.scope_hash.in_(
            scope_hashes or {_retention_tombstone("empty-orphan-scope")}
        ),
        limit=257,
    )
    # Expiry materialization is intentionally performed by the caller only
    # after the complete graph passes the global hard-cap decision.
    return graph, 0


def _load_standalone_bootstrap_graph(
    db: Session,
    bootstrap_id: uuid.UUID,
    *,
    current: datetime,
) -> tuple[dict[str, list[Any]], int]:
    """Lock a never-used bootstrap only when it still has no ceremony."""

    graph = _empty_retention_graph()
    rows = _retention_graph_rows(
        db,
        MentorBootstrapAttempt,
        MentorBootstrapAttempt.id == bootstrap_id,
        MentorBootstrapAttempt.deleted_at.is_(None),
        limit=2,
    )
    if len(rows) != 1:
        return graph, 0
    if db.scalar(
        select(MentorCeremony.id)
        .where(
            MentorCeremony.bootstrap_attempt_id == bootstrap_id,
            MentorCeremony.deleted_at.is_(None),
        )
        .limit(1)
    ) is not None:
        return graph, 0
    bootstrap = rows[0]
    materialized = 0
    if bootstrap.state == "active" and _utc(bootstrap.expires_at) <= current:
        bootstrap.state = "expired"
        bootstrap.consumed_at = bootstrap.expires_at
        materialized = 1
    graph["bootstraps"] = rows
    return graph, materialized


def _load_standalone_proof_graph(
    db: Session,
    proof_id: uuid.UUID,
    *,
    current: datetime,
) -> tuple[dict[str, list[Any]], int]:
    """Lock an expired proof only when no authority row still references it."""

    graph = _empty_retention_graph()
    rows = _retention_graph_rows(
        db,
        TutorProfileOwnershipProof,
        TutorProfileOwnershipProof.id == proof_id,
        TutorProfileOwnershipProof.deleted_at.is_(None),
        limit=2,
    )
    if len(rows) != 1:
        return graph, 0
    if db.scalar(
        select(MentorCeremony.id)
        .where(
            MentorCeremony.ownership_proof_id == proof_id,
            MentorCeremony.deleted_at.is_(None),
        )
        .limit(1)
    ) is not None or db.scalar(
        select(MentorSession.id)
        .where(
            MentorSession.ownership_proof_id == proof_id,
            MentorSession.deleted_at.is_(None),
        )
        .limit(1)
    ) is not None:
        return graph, 0
    proof = rows[0]
    materialized = 0
    if proof.state == "current" and _utc(proof.expires_at) <= current:
        proof.state = "expired"
        proof.revoked_at = proof.expires_at
        materialized = 1
    graph["proofs"] = rows
    return graph, materialized


def _load_authority_domain_graph(
    db: Session,
    authority_domain_hash: str,
) -> dict[str, list[Any]]:
    """Lock one complete domain graph in deterministic table/id order."""

    graph: dict[str, list[Any]] = {}
    graph["invitations"] = _retention_graph_rows(
        db,
        MentorInvitation,
        MentorInvitation.authority_domain_hash == authority_domain_hash,
        MentorInvitation.deleted_at.is_(None),
        limit=257,
    )
    invitation_ids = [row.id for row in graph["invitations"]]
    graph["engagements"] = _retention_graph_rows(
        db,
        MentorEngagement,
        or_(
            MentorEngagement.authority_domain_hash == authority_domain_hash,
            MentorEngagement.invitation_id.in_(
                invitation_ids or [uuid.UUID(int=0)]
            ),
        ),
        MentorEngagement.deleted_at.is_(None),
        limit=257,
    )
    engagement_ids = [row.id for row in graph["engagements"]]
    graph["sessions"] = _retention_graph_rows(
        db,
        MentorSession,
        or_(
            MentorSession.authority_domain_hash == authority_domain_hash,
            MentorSession.engagement_id.in_(
                engagement_ids or [uuid.UUID(int=0)]
            ),
        ),
        MentorSession.deleted_at.is_(None),
        limit=257,
    )
    session_ids = [row.id for row in graph["sessions"]]
    graph["mentor_consents"] = _retention_graph_rows(
        db,
        MentorConsent,
        MentorConsent.engagement_id.in_(
            engagement_ids or [uuid.UUID(int=0)]
        ),
        MentorConsent.deleted_at.is_(None),
        limit=257,
    )
    graph["subject_consents"] = _retention_graph_rows(
        db,
        MentorSubjectConsent,
        MentorSubjectConsent.invitation_id.in_(
            invitation_ids or [uuid.UUID(int=0)]
        ),
        MentorSubjectConsent.deleted_at.is_(None),
        limit=257,
    )
    graph["step_ups"] = _retention_graph_rows(
        db,
        MentorAuthorityStepUp,
        MentorAuthorityStepUp.mentor_session_id.in_(
            session_ids or [uuid.UUID(int=0)]
        ),
        MentorAuthorityStepUp.deleted_at.is_(None),
        limit=257,
    )
    ceremony_ids = {
        row.ceremony_id for row in graph["sessions"] if row.ceremony_id is not None
    }
    ceremony_ids.update(
        row.ceremony_id
        for row in graph["step_ups"]
        if row.ceremony_id is not None
    )
    graph["ceremonies"] = _retention_graph_rows(
        db,
        MentorCeremony,
        or_(
            MentorCeremony.id.in_(ceremony_ids or {uuid.UUID(int=0)}),
            MentorCeremony.invitation_id.in_(
                invitation_ids or [uuid.UUID(int=0)]
            ),
        ),
        MentorCeremony.deleted_at.is_(None),
        limit=257,
    )
    ceremony_ids.update(row.id for row in graph["ceremonies"])
    bootstrap_ids = [
        row.bootstrap_attempt_id
        for row in graph["ceremonies"]
        if row.bootstrap_attempt_id is not None
    ]
    graph["bootstraps"] = _retention_graph_rows(
        db,
        MentorBootstrapAttempt,
        MentorBootstrapAttempt.id.in_(bootstrap_ids or [uuid.UUID(int=0)]),
        MentorBootstrapAttempt.deleted_at.is_(None),
        limit=257,
    )
    graph["provider_results"] = _retention_graph_rows(
        db,
        MentorProviderResult,
        MentorProviderResult.ceremony_id.in_(
            ceremony_ids or {uuid.UUID(int=0)}
        ),
        MentorProviderResult.deleted_at.is_(None),
        limit=257,
    )
    candidate_proof_ids = {
        row.ownership_proof_id
        for row in (*graph["ceremonies"], *graph["sessions"])
        if row.ownership_proof_id is not None
    }
    current_ceremony_ids = {row.id for row in graph["ceremonies"]}
    current_session_ids = {row.id for row in graph["sessions"]}
    proof_ids: set[uuid.UUID] = set()
    for proof_id in candidate_proof_ids:
        externally_linked = db.scalar(
            select(MentorCeremony.id)
            .where(
                MentorCeremony.ownership_proof_id == proof_id,
                MentorCeremony.deleted_at.is_(None),
                MentorCeremony.id.not_in(
                    current_ceremony_ids or {uuid.UUID(int=0)}
                ),
            )
            .limit(1)
        ) is not None or db.scalar(
            select(MentorSession.id)
            .where(
                MentorSession.ownership_proof_id == proof_id,
                MentorSession.deleted_at.is_(None),
                MentorSession.id.not_in(
                    current_session_ids or {uuid.UUID(int=0)}
                ),
            )
            .limit(1)
        ) is not None
        if not externally_linked:
            proof_ids.add(proof_id)
    graph["proofs"] = _retention_graph_rows(
        db,
        TutorProfileOwnershipProof,
        TutorProfileOwnershipProof.id.in_(proof_ids or {uuid.UUID(int=0)}),
        TutorProfileOwnershipProof.deleted_at.is_(None),
        limit=257,
    )
    scope_hashes = _related_idempotency_scope_hashes(
        {**graph, "idempotency": [], "audit_links": []}
    )
    graph["idempotency"] = _retention_graph_rows(
        db,
        MentorIdempotencyRecord,
        MentorIdempotencyRecord.scope_hash.in_(
            scope_hashes or {_retention_tombstone("empty-scope")}
        ),
        limit=257,
    )
    graph["audit_links"] = _retention_graph_rows(
        db,
        MentorAuditLink,
        MentorAuditLink.correlation_hash
        == keyed_hash(f"mentor-audit-link:v1:{authority_domain_hash}"),
        MentorAuditLink.erased_at.is_(None),
        limit=257,
    )
    return graph


def _materialize_authority_domain_expirations(
    graph: dict[str, list[Any]],
    *,
    current: datetime,
) -> int:
    """Terminalize a locked graph at its authoritative expiry boundaries."""

    changed = 0

    def transition(row: Any, *, state_field: str, state: str, time_field: str, boundary: datetime) -> None:
        nonlocal changed
        setattr(row, state_field, state)
        setattr(row, time_field, boundary)
        changed += 1

    for row in graph["bootstraps"]:
        if row.state == "active" and _utc(row.expires_at) <= current:
            transition(
                row,
                state_field="state",
                state="expired",
                time_field="consumed_at",
                boundary=row.expires_at,
            )
    for row in graph["invitations"]:
        if row.state in {"pending", "accepted"} and _utc(row.expires_at) <= current:
            transition(
                row,
                state_field="state",
                state="expired",
                time_field="terminal_at",
                boundary=row.expires_at,
            )
    for row in graph["proofs"]:
        if row.state == "current" and _utc(row.expires_at) <= current:
            transition(
                row,
                state_field="state",
                state="expired",
                time_field="revoked_at",
                boundary=row.expires_at,
            )
    for row in graph["ceremonies"]:
        if (
            row.state in {"pending_invitation", "challenge_issued", "proof_verified"}
            and _utc(row.expires_at) <= current
        ):
            transition(
                row,
                state_field="state",
                state="expired",
                time_field="terminal_at",
                boundary=row.expires_at,
            )
    for row in graph["provider_results"]:
        if row.state in {"pending", "verified"} and _utc(row.expires_at) <= current:
            transition(
                row,
                state_field="state",
                state="expired",
                time_field="consumed_at",
                boundary=row.expires_at,
            )
    for row in graph["subject_consents"]:
        if row.status == "granted" and _utc(row.expires_at) <= current:
            transition(
                row,
                state_field="status",
                state="expired",
                time_field="revoked_at",
                boundary=row.expires_at,
            )
    for row in graph["step_ups"]:
        if row.state == "active" and _utc(row.expires_at) <= current:
            transition(
                row,
                state_field="state",
                state="expired",
                time_field="consumed_at",
                boundary=row.expires_at,
            )

    proof_by_id = {row.id: row for row in graph["proofs"]}
    ceremony_by_id = {row.id: row for row in graph["ceremonies"]}
    engagement_by_id = {row.id: row for row in graph["engagements"]}
    consent_by_id = {row.id: row for row in graph["mentor_consents"]}
    subject_consent_by_id = {row.id: row for row in graph["subject_consents"]}
    invitation_by_id = {row.id: row for row in graph["invitations"]}
    provider_by_ceremony = {
        row.ceremony_id: row
        for row in graph["provider_results"]
        if row.ceremony_id is not None
    }
    for row in graph["sessions"]:
        if row.state != "active":
            continue
        boundaries: list[datetime] = []
        absolute = row.expires_at
        idle = _utc(row.last_seen_at) + timedelta(
            seconds=settings.mentor_session_idle_ttl_seconds
        )
        if _utc(absolute) <= current:
            boundaries.append(absolute)
        if idle <= current:
            boundaries.append(idle)
        proof = proof_by_id.get(row.ownership_proof_id)
        if proof is not None and proof.state != "current":
            boundaries.append(proof.revoked_at or proof.expires_at)
        ceremony = ceremony_by_id.get(row.ceremony_id)
        if ceremony is not None and ceremony.state != "exchanged":
            boundaries.append(ceremony.terminal_at or ceremony.expires_at)
        engagement = engagement_by_id.get(row.engagement_id)
        if engagement is not None and engagement.state not in {"pending", "active"}:
            boundaries.append(engagement.terminal_at or row.expires_at)
        consent = consent_by_id.get(row.consent_id)
        if consent is not None and consent.status != "granted":
            boundaries.append(consent.revoked_at or row.expires_at)
        subject_consent = subject_consent_by_id.get(row.subject_consent_id)
        if subject_consent is not None and subject_consent.status != "granted":
            boundaries.append(subject_consent.revoked_at or subject_consent.expires_at)
        invitation = (
            invitation_by_id.get(engagement.invitation_id)
            if engagement is not None
            else None
        )
        if invitation is not None and invitation.state != "accepted":
            boundaries.append(invitation.terminal_at or invitation.expires_at)
        provider = provider_by_ceremony.get(row.ceremony_id)
        if provider is not None and provider.state != "consumed":
            boundaries.append(provider.consumed_at or provider.expires_at)
        if boundaries:
            transition(
                row,
                state_field="state",
                state="expired",
                time_field="terminal_at",
                boundary=min(boundaries, key=_utc),
            )

    invitation_by_id = {row.id: row for row in graph["invitations"]}
    subject_by_invitation = {
        row.invitation_id: row
        for row in graph["subject_consents"]
        if row.invitation_id is not None
    }
    sessions_by_engagement: dict[uuid.UUID, list[MentorSession]] = {}
    for session in graph["sessions"]:
        if session.engagement_id is not None:
            sessions_by_engagement.setdefault(session.engagement_id, []).append(session)
    for engagement in graph["engagements"]:
        if engagement.state not in {"pending", "active"}:
            continue
        invitation = invitation_by_id.get(engagement.invitation_id)
        subject_consent = subject_by_invitation.get(engagement.invitation_id)
        sessions = sessions_by_engagement.get(engagement.id, [])
        invalid_boundaries: list[datetime] = []
        if invitation is None or invitation.state not in {"pending", "accepted"}:
            if invitation is not None:
                invalid_boundaries.append(
                    invitation.terminal_at or invitation.expires_at
                )
        if subject_consent is None or subject_consent.status != "granted":
            if subject_consent is not None:
                invalid_boundaries.append(
                    subject_consent.revoked_at or subject_consent.expires_at
                )
        if sessions and not any(session.state == "active" for session in sessions):
            invalid_boundaries.extend(
                session.terminal_at
                for session in sessions
                if session.terminal_at is not None
            )
        if invalid_boundaries:
            transition(
                engagement,
                state_field="state",
                state="expired",
                time_field="terminal_at",
                boundary=min(invalid_boundaries, key=_utc),
            )

    engagement_by_id = {row.id: row for row in graph["engagements"]}
    for consent in graph["mentor_consents"]:
        engagement = engagement_by_id.get(consent.engagement_id)
        if (
            consent.status == "granted"
            and engagement is not None
            and engagement.state not in {"pending", "active"}
        ):
            transition(
                consent,
                state_field="status",
                state="expired",
                time_field="revoked_at",
                boundary=engagement.terminal_at or current,
            )
    return changed


def _candidate_retention_actor_ids(
    db: Session,
    authority_domain_hash: str,
) -> list[uuid.UUID]:
    """Discover every actor lock for one domain without authorizing the graph."""

    actor_ids = {
        value
        for value in db.scalars(
            select(MentorSession.actor_user_id).where(
                MentorSession.authority_domain_hash == authority_domain_hash,
                MentorSession.actor_user_id.is_not(None),
                MentorSession.deleted_at.is_(None),
            )
        )
        if value is not None
    }
    actor_ids.update(
        value
        for value in db.scalars(
            select(MentorEngagement.mentor_user_id).where(
                MentorEngagement.authority_domain_hash == authority_domain_hash,
                MentorEngagement.mentor_user_id.is_not(None),
                MentorEngagement.deleted_at.is_(None),
            )
        )
        if value is not None
    )
    invitation_ids = list(
        db.scalars(
            select(MentorInvitation.id).where(
                MentorInvitation.authority_domain_hash == authority_domain_hash,
                MentorInvitation.deleted_at.is_(None),
            )
        )
    )
    mentor_matches = set(
        db.scalars(
            select(MentorInvitation.mentor_match_hash).where(
                MentorInvitation.authority_domain_hash
                == authority_domain_hash,
                MentorInvitation.deleted_at.is_(None),
            )
        )
    )
    if mentor_matches:
        actor_ids.update(
            value
            for value in db.scalars(
                select(TutorProfileOwnershipProof.user_id).where(
                    TutorProfileOwnershipProof.provider_subject_hash.in_(
                        mentor_matches
                    ),
                    TutorProfileOwnershipProof.state == "current",
                    TutorProfileOwnershipProof.deleted_at.is_(None),
                    TutorProfileOwnershipProof.user_id.is_not(None),
                )
            )
            if value is not None
        )
    if invitation_ids:
        actor_ids.update(
            value
            for value in db.scalars(
                select(MentorCeremony.actor_user_id).where(
                    MentorCeremony.invitation_id.in_(invitation_ids),
                    MentorCeremony.actor_user_id.is_not(None),
                    MentorCeremony.deleted_at.is_(None),
                )
            )
            if value is not None
        )
    return sorted(actor_ids, key=str)


def _subject_domain_candidates(
    db: Session,
    subject_registration_id: uuid.UUID,
) -> set[str]:
    """Discover subject-linked mentor domains without taking row locks."""

    domains = set(
        db.scalars(
            select(MentorInvitation.authority_domain_hash).where(
                MentorInvitation.subject_registration_id
                == subject_registration_id,
                MentorInvitation.deleted_at.is_(None),
            )
        )
    )
    domains.update(
        db.scalars(
            select(MentorEngagement.authority_domain_hash).where(
                MentorEngagement.subject_registration_id
                == subject_registration_id,
                MentorEngagement.deleted_at.is_(None),
            )
        )
    )
    domains.update(
        db.scalars(
            select(MentorInvitation.authority_domain_hash)
            .join(
                MentorSubjectConsent,
                MentorSubjectConsent.invitation_id == MentorInvitation.id,
            )
            .where(
                MentorSubjectConsent.subject_registration_id
                == subject_registration_id,
                MentorSubjectConsent.deleted_at.is_(None),
                MentorInvitation.deleted_at.is_(None),
            )
        )
    )
    return domains


def _terminalize_subject_mentor_graph(
    graph: dict[str, list[Any]],
    *,
    current: datetime,
) -> None:
    """Reversibly retire every browser authority in a locked subject graph."""

    for row in graph["bootstraps"]:
        row.state = "expired"
        row.consumed_at = row.consumed_at or current
    for row in graph["invitations"]:
        row.state = "deleted"
        row.terminal_at = row.terminal_at or current
    for row in graph["ceremonies"]:
        row.state = "deleted"
        row.terminal_at = row.terminal_at or current
    for row in graph["provider_results"]:
        if row.state in {"pending", "verified"}:
            row.state = "rejected"
        row.consumed_at = row.consumed_at or current
    for row in graph["subject_consents"]:
        row.status = "deleted"
        row.revoked_at = row.revoked_at or current
    for row in graph["engagements"]:
        row.state = "deleted"
        row.terminal_at = row.terminal_at or current
    for row in graph["mentor_consents"]:
        row.status = "deleted"
        row.revoked_at = row.revoked_at or current
    for row in graph["sessions"]:
        row.state = "deleted"
        row.terminal_at = row.terminal_at or current
    for row in graph["step_ups"]:
        row.state = "deleted"
        row.consumed_at = row.consumed_at or current


def _load_prelocked_subject_mentor_graphs(
    db: Session,
    boundary: SubjectMentorErasureBoundary,
    locked_registration: StudentRegistration,
) -> list[tuple[str, dict[str, list[Any]]]]:
    """Re-read complete subject graphs after the opaque advisory prelock."""

    validate_subject_mentor_erasure_boundary(
        db, boundary, locked_registration.id
    )
    if (
        locked_registration.id != boundary.registration_id
        or locked_registration.user_id != boundary.subject_user_id
        or _utc(locked_registration.updated_at)
        != _utc(boundary.registration_updated_at)
    ):
        raise MentorCeremonyError(
            409, "CONCURRENT_STATE_CHANGED", retryable=True
        )
    discovered = _subject_domain_candidates(db, boundary.registration_id)
    if discovered != set(boundary.authority_domains):
        raise MentorCeremonyError(
            409, "CONCURRENT_STATE_CHANGED", retryable=True
        )
    locked: list[tuple[str, dict[str, list[Any]]]] = []
    rediscovered_actors: set[uuid.UUID] = {boundary.subject_user_id}
    for authority_domain_hash in boundary.authority_domains:
        actors = set(_candidate_retention_actor_ids(db, authority_domain_hash))
        rediscovered_actors.update(actors)
        graph = _load_authority_domain_graph(db, authority_domain_hash)
        linked_subjects = {
            value
            for rows, field in (
                (graph["invitations"], "subject_registration_id"),
                (graph["subject_consents"], "subject_registration_id"),
                (graph["engagements"], "subject_registration_id"),
            )
            for row in rows
            if (value := getattr(row, field, None)) is not None
        }
        if linked_subjects != {boundary.registration_id}:
            raise MentorCeremonyError(
                409, "CONCURRENT_STATE_CHANGED", retryable=True
            )
        locked.append((authority_domain_hash, graph))
    if rediscovered_actors != set(boundary.actor_ids):
        raise MentorCeremonyError(
            409, "CONCURRENT_STATE_CHANGED", retryable=True
        )
    return locked


def _combine_subject_mentor_graphs(
    locked: list[tuple[str, dict[str, list[Any]]]],
) -> tuple[dict[str, list[Any]], int]:
    """Return one globally de-duplicated, deterministic subject inventory."""

    combined: dict[str, list[Any]] = {
        name: []
        for name in (
            "bootstraps",
            "invitations",
            "proofs",
            "ceremonies",
            "provider_results",
            "subject_consents",
            "engagements",
            "mentor_consents",
            "sessions",
            "step_ups",
            "idempotency",
            "audit_links",
        )
    }
    seen: set[tuple[str, uuid.UUID]] = set()
    for _domain, graph in locked:
        for name, rows in graph.items():
            target = combined.setdefault(name, [])
            for row in rows:
                identity = (name, row.id)
                if identity in seen:
                    continue
                seen.add(identity)
                target.append(row)
    for rows in combined.values():
        rows.sort(key=lambda row: str(row.id))
    return combined, len(seen)


def _subject_graph_identity_digest(graph: dict[str, list[Any]]) -> str:
    """Return a stable, non-reversible identity for one exact locked graph.

    Observation time is deliberately excluded.  Repeated sightings of an
    unchanged oversized graph must update one NYAY-19 review-register row
    instead of manufacturing an unbounded alert stream.
    """

    identities = [
        f"{name}:{row.id}"
        for name in sorted(graph)
        for row in sorted(graph[name], key=lambda candidate: str(candidate.id))
    ]
    return hashlib.sha256("\n".join(identities).encode("utf-8")).hexdigest()


def _consume_subject_erasure_boundary(
    db: Session,
    boundary: SubjectMentorErasureBoundary,
    *,
    phase: str,
) -> None:
    state = db.info.setdefault(_SUBJECT_ERASURE_STATE_KEY, {}).get(
        boundary._nonce
    )
    if (
        state is None
        or state.get("boundary") is not boundary
        or state.get("transaction") is not db.get_transaction()
        or state.get("consumed") is not False
        or state.get("phase") != "prelocked"
    ):
        raise RuntimeError("mentor erasure boundary was not prelocked")
    state["consumed"] = True
    state["phase"] = phase


def preflight_subject_mentor_authority_for_privacy_request(
    db: Session,
    boundary: SubjectMentorErasureBoundary,
    locked_registration: StudentRegistration,
    *,
    now: datetime | None = None,
) -> bool:
    """Reject an oversized deletion graph before OTP proof consumption.

    ``False`` means the transaction contains only a durable, digest-bound
    NYAY-19 review alert.  The mentor graph and the caller's one-shot recovery
    authority remain untouched, so the caller may safely commit that alert and
    return the canonical concurrent-state response.
    """

    current = _utc(now or _now())
    locked = _load_prelocked_subject_mentor_graphs(
        db, boundary, locked_registration
    )
    combined, total_rows = _combine_subject_mentor_graphs(locked)
    if total_rows <= SUBJECT_GRAPH_HARD_CAP:
        return True
    _record_blocked_retention_graph(
        db,
        authority_domain_hash=_subject_graph_identity_digest(combined),
        reason_code="GRAPH_EXCEEDS_HARD_CAP",
        row_count=total_rows,
        current=current,
    )
    _consume_subject_erasure_boundary(db, boundary, phase="blocked")
    db.flush()
    return False


def retire_subject_mentor_authority_for_privacy_request(
    db: Session,
    boundary: SubjectMentorErasureBoundary,
    *,
    now: datetime | None = None,
) -> int:
    """Atomically freeze subject-linked mentor bearers with a deletion DSR."""

    current = _utc(now or _now())
    registration = db.get(StudentRegistration, boundary.registration_id)
    if registration is None:
        raise MentorCeremonyError(
            409, "CONCURRENT_STATE_CHANGED", retryable=True
        )
    locked = _load_prelocked_subject_mentor_graphs(
        db, boundary, registration
    )
    combined, total_rows = _combine_subject_mentor_graphs(locked)
    if total_rows > SUBJECT_GRAPH_HARD_CAP:
        # Oversized means no graph mutation.  Persist only the digest-bound
        # NYAY-19 review alert so the condition cannot become a silent skip.
        _record_blocked_retention_graph(
            db,
            authority_domain_hash=_subject_graph_identity_digest(combined),
            reason_code="GRAPH_EXCEEDS_HARD_CAP",
            row_count=total_rows,
            current=current,
        )
        _consume_subject_erasure_boundary(db, boundary, phase="blocked")
        db.flush()
        return -1
    _terminalize_subject_mentor_graph(combined, current=current)
    for _domain, _graph in locked:
        db.add(
            AuditEvent(
                actor_user_id=None,
                actor_role="system",
                action="mentor.subject_authority.retired",
                resource_type="mentor_authority",
                resource_id=None,
                after_state={"outcome": "retired"},
            )
        )
    _consume_subject_erasure_boundary(db, boundary, phase="retired")
    db.flush()
    return len(locked)


def _graph_is_cutoff_eligible(
    graph: dict[str, list[Any]],
    *,
    current: datetime,
    terminal_cutoff: datetime,
) -> bool:
    tests: tuple[tuple[str, set[str], str, tuple[str, ...]], ...] = (
        ("bootstraps", {"consumed", "expired"}, "state", ("consumed_at", "updated_at")),
        ("invitations", {"expired", "revoked", "deleted"}, "state", ("terminal_at", "updated_at")),
        ("proofs", {"expired", "revoked", "deleted"}, "state", ("revoked_at", "updated_at")),
        ("ceremonies", {"exchanged", "expired", "revoked", "deleted"}, "state", ("terminal_at", "updated_at")),
        ("provider_results", {"consumed", "rejected", "expired"}, "state", ("consumed_at", "updated_at")),
        ("subject_consents", {"revoked", "expired", "deleted"}, "status", ("revoked_at", "updated_at")),
        ("engagements", {"expired", "revoked", "deleted"}, "state", ("terminal_at", "updated_at")),
        ("mentor_consents", {"revoked", "expired", "deleted"}, "status", ("revoked_at", "updated_at")),
        ("sessions", set(MENTOR_SESSION_TERMINAL_STATES), "state", ("terminal_at", "updated_at")),
        ("step_ups", {"consumed", "expired", "revoked", "deleted"}, "state", ("consumed_at", "updated_at")),
        ("idempotency", {"succeeded", "failed", "erased"}, "state", ("updated_at",)),
    )
    for name, terminal_states, state_field, time_fields in tests:
        for row in graph[name]:
            if getattr(row, state_field) not in terminal_states:
                return False
            terminal_time = next(
                (
                    _utc(value)
                    for field in time_fields
                    if isinstance((value := getattr(row, field, None)), datetime)
                ),
                None,
            )
            if terminal_time is None or terminal_time > terminal_cutoff:
                return False
    return all(_utc(row.expires_at) <= current for row in graph["audit_links"])


def _sever_authority_graph(
    graph: dict[str, list[Any]],
    *,
    current: datetime,
) -> dict[str, int]:
    counts = {name: len(rows) for name, rows in graph.items()}

    for row in graph["bootstraps"]:
        row.token_hash = _retention_tombstone("bootstrap-token")
        row.metadata_json = None
        row.deleted_at = current
    for row in graph["invitations"]:
        row.subject_registration_id = None
        row.initiator_user_id = None
        row.initiator_session_hash = _retention_tombstone("invitation-session")
        row.creation_idempotency_hash = _retention_tombstone("invitation-idempotency")
        row.mentor_match_hash = _retention_tombstone("invitation-match")
        row.authority_domain_hash = _retention_tombstone("invitation-domain")
        row.disclosure_classes = []
        row.metadata_json = None
        row.deleted_at = current
    for row in graph["proofs"]:
        row.user_id = None
        row.tutor_profile_id = None
        row.provider_subject_hash = _retention_tombstone("proof-subject")
        row.evidence_digest = _retention_tombstone("proof-evidence")
        row.key_version = "erased"
        row.metadata_json = None
        row.deleted_at = current
    for row in graph["ceremonies"]:
        row.bootstrap_attempt_id = None
        row.actor_user_id = None
        row.tutor_profile_id = None
        row.ownership_proof_id = None
        row.invitation_id = None
        row.token_hash = _retention_tombstone("ceremony-token")
        row.predecessor_token_hash = None
        row.challenge_hash = _retention_tombstone("ceremony-challenge")
        row.token_seed_ct = None
        row.token_seed_key_version = None
        row.metadata_json = None
        row.deleted_at = current
    for row in graph["provider_results"]:
        row.ceremony_id = None
        row.state = "expired"
        row.issuer_hash = _retention_tombstone("provider-issuer")
        row.audience_hash = _retention_tombstone("provider-audience")
        row.nonce_hash = _retention_tombstone("provider-nonce")
        row.correlation_hash = _retention_tombstone("provider-correlation")
        row.provider_subject_hash = _retention_tombstone("provider-subject")
        row.evidence_digest = _retention_tombstone("provider-evidence")
        row.key_version = "erased"
        row.nonce_ct = None
        row.correlation_ct = None
        row.transaction_key_version = None
        row.metadata_json = None
        row.deleted_at = current
    for row in graph["subject_consents"]:
        row.invitation_id = None
        row.subject_registration_id = None
        row.granted_by_user_id = None
        row.guardian_consent_id = None
        row.granting_session_hash = _retention_tombstone("subject-session")
        row.grant_idempotency_hash = _retention_tombstone("subject-idempotency")
        row.disclosure_classes = []
        row.metadata_json = None
        row.deleted_at = current
    for row in graph["engagements"]:
        row.invitation_id = None
        row.subject_registration_id = None
        row.mentor_user_id = None
        row.tutor_profile_id = None
        row.authority_domain_hash = _retention_tombstone("engagement-domain")
        row.metadata_json = None
        row.deleted_at = current
    for row in graph["mentor_consents"]:
        row.engagement_id = None
        row.disclosure_classes = []
        row.metadata_json = None
        row.deleted_at = current
    for row in graph["sessions"]:
        row.ceremony_id = None
        row.engagement_id = None
        row.actor_user_id = None
        row.tutor_profile_id = None
        row.ownership_proof_id = None
        row.consent_id = None
        row.subject_consent_id = None
        row.successor_id = None
        row.authority_domain_hash = _retention_tombstone("session-domain")
        row.token_hash = _retention_tombstone("session-token")
        row.token_seed_ct = None
        row.token_seed_key_version = None
        row.scopes = []
        row.permitted_profile_slices = []
        row.metadata_json = None
        row.deleted_at = current
    for row in graph["step_ups"]:
        row.ceremony_id = None
        row.actor_user_id = None
        row.mentor_session_id = None
        row.token_hash = _retention_tombstone("step-up-token")
        row.token_seed_ct = None
        row.token_seed_key_version = None
        row.fingerprint = _retention_tombstone("step-up-fingerprint")
        row.metadata_json = None
        row.deleted_at = current
    for row in graph["idempotency"]:
        row.scope_hash = _retention_tombstone("idempotency-scope")
        row.idempotency_key_hash = _retention_tombstone("idempotency-key")
        row.request_fingerprint = _retention_tombstone("idempotency-request")
        row.state = "erased"
        row.outcome_status = None
        row.outcome_ct = None
        row.key_version = None
    for row in graph["audit_links"]:
        row.correlation_hash = _retention_tombstone("audit-correlation")
        row.link_key_ct = None
        row.actor_link_ct = None
        row.key_version = None
        row.erased_at = current
    return counts


def _record_blocked_retention_graph(
    db: Session,
    *,
    authority_domain_hash: str,
    reason_code: str,
    row_count: int,
    current: datetime,
) -> None:
    graph_key_hash = keyed_hash(
        f"mentor-retention-blocked:v1:{authority_domain_hash}"
    )
    row = db.scalar(
        select(MentorRetentionBlockedGraph)
        .where(MentorRetentionBlockedGraph.graph_key_hash == graph_key_hash)
        .with_for_update()
    )
    if row is None:
        db.add(
            MentorRetentionBlockedGraph(
                graph_key_hash=graph_key_hash,
                reason_code=reason_code,
                observed_row_count=row_count,
                state="open",
                first_detected_at=current,
                last_detected_at=current,
                occurrence_count=1,
                review_queue="nyay19_retention_review",
            )
        )
    else:
        row.reason_code = reason_code
        row.observed_row_count = row_count
        row.state = "open"
        row.last_detected_at = current
        row.occurrence_count += 1


def _assert_subject_graph_severed(
    db: Session,
    boundary: SubjectMentorErasureBoundary,
    graph: dict[str, list[Any]],
) -> str:
    """Prove the locked graph has only approved, non-linkable fields left."""

    required_nulls: dict[str, tuple[str, ...]] = {
        "invitations": ("subject_registration_id", "initiator_user_id"),
        "proofs": ("user_id", "tutor_profile_id"),
        "ceremonies": (
            "bootstrap_attempt_id",
            "actor_user_id",
            "tutor_profile_id",
            "ownership_proof_id",
            "invitation_id",
            "token_seed_ct",
            "token_seed_key_version",
            "metadata_json",
        ),
        "provider_results": (
            "ceremony_id",
            "nonce_ct",
            "correlation_ct",
            "transaction_key_version",
            "metadata_json",
        ),
        "subject_consents": (
            "invitation_id",
            "subject_registration_id",
            "granted_by_user_id",
            "guardian_consent_id",
            "metadata_json",
        ),
        "engagements": (
            "invitation_id",
            "subject_registration_id",
            "mentor_user_id",
            "tutor_profile_id",
            "metadata_json",
        ),
        "mentor_consents": ("engagement_id", "metadata_json"),
        "sessions": (
            "ceremony_id",
            "engagement_id",
            "actor_user_id",
            "tutor_profile_id",
            "ownership_proof_id",
            "consent_id",
            "subject_consent_id",
            "successor_id",
            "token_seed_ct",
            "token_seed_key_version",
            "metadata_json",
        ),
        "step_ups": (
            "ceremony_id",
            "actor_user_id",
            "mentor_session_id",
            "token_seed_ct",
            "token_seed_key_version",
            "metadata_json",
        ),
        "audit_links": ("link_key_ct", "actor_link_ct", "key_version"),
    }
    required_empty: dict[str, tuple[str, ...]] = {
        "invitations": ("disclosure_classes",),
        "subject_consents": ("disclosure_classes",),
        "mentor_consents": ("disclosure_classes",),
        "sessions": ("scopes", "permitted_profile_slices"),
    }
    digest_rows: list[str] = []
    for name in sorted(graph):
        for row in graph[name]:
            if name not in {"idempotency", "audit_links"} and getattr(
                row, "deleted_at", None
            ) is None:
                raise RuntimeError("mentor graph severance proof failed")
            for field in required_nulls.get(name, ()):
                if getattr(row, field, None) is not None:
                    raise RuntimeError("mentor graph severance proof failed")
            for field in required_empty.get(name, ()):
                if getattr(row, field, None) != []:
                    raise RuntimeError("mentor graph severance proof failed")
            if getattr(row, "metadata_json", None) is not None:
                raise RuntimeError("mentor graph severance proof failed")
            if name == "idempotency" and (
                row.outcome_status is not None
                or row.outcome_ct is not None
                or row.key_version is not None
                or row.state != "erased"
            ):
                raise RuntimeError("mentor graph severance proof failed")
            digest_rows.append(f"{name}:{row.id}")

    remaining_subject_link = any(
        db.scalar(statement.limit(1)) is not None
        for statement in (
            select(MentorInvitation.id).where(
                MentorInvitation.subject_registration_id
                == boundary.registration_id
            ),
            select(MentorSubjectConsent.id).where(
                MentorSubjectConsent.subject_registration_id
                == boundary.registration_id
            ),
            select(MentorEngagement.id).where(
                MentorEngagement.subject_registration_id
                == boundary.registration_id
            ),
        )
    )
    if remaining_subject_link:
        raise RuntimeError("mentor graph severance proof failed")
    return hashlib.sha256("\n".join(digest_rows).encode("utf-8")).hexdigest()


def prepare_subject_mentor_registration_erasure(
    db: Session,
    boundary: SubjectMentorErasureBoundary,
    locked_registration: StudentRegistration,
) -> SubjectMentorErasureApproval | str:
    """Issue an erasure approval only after a cutoff-bound zero-link proof."""

    locked = _load_prelocked_subject_mentor_graphs(
        db, boundary, locked_registration
    )
    graph, total_rows = _combine_subject_mentor_graphs(locked)
    current = boundary.current

    # The cap is global across all domains.  Oversized graphs remain
    # bit-identical; only a digest-only NYAY-19 review alert is permitted.
    if total_rows > SUBJECT_GRAPH_HARD_CAP:
        _record_blocked_retention_graph(
            db,
            authority_domain_hash=_subject_graph_identity_digest(graph),
            reason_code="GRAPH_EXCEEDS_HARD_CAP",
            row_count=total_rows,
            current=current,
        )
        _consume_subject_erasure_boundary(db, boundary, phase="deferred")
        db.flush()
        return "DEFER"

    terminal_cutoff = current - timedelta(
        seconds=settings.mentor_terminal_retention_seconds
    )
    audit_window = timedelta(
        seconds=settings.mentor_audit_link_retention_seconds
    )
    audit_cutoff = current - audit_window
    cutoff_eligible = _graph_is_cutoff_eligible(
        graph,
        current=current,
        terminal_cutoff=terminal_cutoff,
    ) and all(
        _utc(row.expires_at) - audit_window <= audit_cutoff
        for row in graph["audit_links"]
    )
    if not cutoff_eligible:
        # Never mutate a live or still-retained authority graph.  The immutable
        # aggregate event is deliberately PII-free and keeps deferral visible.
        db.add(
            AuditEvent(
                actor_user_id=None,
                actor_role="system",
                action="mentor.subject_authority.retention_deferred",
                resource_type="mentor_authority",
                resource_id=None,
                after_state={"outcome": "deferred"},
            )
        )
        _consume_subject_erasure_boundary(db, boundary, phase="deferred")
        db.flush()
        return "DEFER"

    _sever_authority_graph(graph, current=current)
    db.flush()
    zero_link_digest = _assert_subject_graph_severed(db, boundary, graph)
    approval = SubjectMentorErasureApproval(
        registration_id=boundary.registration_id,
        policy_digest=boundary.policy_digest,
        inventory_digest=boundary.inventory_digest,
        zero_link_digest=zero_link_digest,
        _nonce=boundary._nonce,
        _guard=_SUBJECT_ERASURE_APPROVAL_GUARD,
    )
    state = db.info.setdefault(_SUBJECT_ERASURE_STATE_KEY, {})[
        boundary._nonce
    ]
    state.update(
        {
            "approval": approval,
            "phase": "approved",
            "consumed": False,
        }
    )
    return approval


def run_mentor_retention(
    db: Session,
    *,
    now: datetime | None = None,
    batch_size: int | None = None,
) -> dict[str, int]:
    """Materialize expiry and atomically sever complete terminal graphs.

    Every connected authority graph is either severed in one transaction or
    left bit-identical.  Graphs beyond the approved bound create a durable,
    digest-only NYAY-19 review alert; the worker never silently skips or
    partially claims erasure.  Immutable aggregate ``AuditEvent`` rows remain.
    """

    current = _utc(now or _now())
    limit = batch_size if batch_size is not None else settings.mentor_retention_batch_size
    if (
        type(limit) is not int
        or limit < 1
        or limit > settings.mentor_retention_batch_size
        or limit > 256
    ):
        raise MentorCeremonyError(503, "PROVIDER_UNAVAILABLE", retryable=True)
    if not _RETENTION_GUARD.acquire(blocking=False):
        raise MentorCeremonyError(409, "CONCURRENT_STATE_CHANGED", retryable=True)
    try:
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            acquired = db.scalar(select(func.pg_try_advisory_xact_lock(0x4E59415922)))
            if acquired is not True:
                raise MentorCeremonyError(
                    409, "CONCURRENT_STATE_CHANGED", retryable=True
                )

        terminal_cutoff = current - timedelta(
            seconds=settings.mentor_terminal_retention_seconds
        )
        counts = {
            "materialized_expirations": 0,
            "severed_graphs": 0,
            "blocked_graphs": 0,
            "bootstraps": 0,
            "invitations": 0,
            "ceremonies": 0,
            "provider_results": 0,
            "subject_consents": 0,
            "engagements": 0,
            "mentor_consents": 0,
            "sessions": 0,
            "step_ups": 0,
            "proofs": 0,
            "idempotency": 0,
            "audit_links": 0,
            "rate_buckets": 0,
        }
        remaining = limit
        blocked_graph_seen = False

        domain_candidates = set(
            db.scalars(
                select(MentorSession.authority_domain_hash)
                .where(
                    or_(
                        and_(
                            MentorSession.terminal_at.is_not(None),
                            MentorSession.terminal_at <= terminal_cutoff,
                        ),
                        and_(
                            MentorSession.state == "active",
                            or_(
                                MentorSession.expires_at <= terminal_cutoff,
                                MentorSession.last_seen_at
                                <= terminal_cutoff
                                - timedelta(
                                    seconds=settings.mentor_session_idle_ttl_seconds
                                ),
                            ),
                        ),
                    ),
                    MentorSession.deleted_at.is_(None),
                )
                .order_by(MentorSession.authority_domain_hash)
                .limit(257)
            )
        )
        domain_candidates.update(
            db.scalars(
                select(MentorEngagement.authority_domain_hash)
                .where(
                    MentorEngagement.terminal_at.is_not(None),
                    MentorEngagement.terminal_at <= terminal_cutoff,
                    MentorEngagement.deleted_at.is_(None),
                )
                .order_by(MentorEngagement.authority_domain_hash)
                .limit(257)
            )
        )
        domain_candidates.update(
            db.scalars(
                select(MentorInvitation.authority_domain_hash)
                .where(
                    or_(
                        and_(
                            MentorInvitation.terminal_at.is_not(None),
                            MentorInvitation.terminal_at <= terminal_cutoff,
                        ),
                        and_(
                            MentorInvitation.state.in_(("pending", "accepted")),
                            MentorInvitation.expires_at <= terminal_cutoff,
                        ),
                    ),
                    MentorInvitation.deleted_at.is_(None),
                )
                .order_by(MentorInvitation.authority_domain_hash)
                .limit(257)
            )
        )
        domain_candidates.update(
            db.scalars(
                select(MentorSession.authority_domain_hash)
                .join(
                    TutorProfileOwnershipProof,
                    TutorProfileOwnershipProof.id
                    == MentorSession.ownership_proof_id,
                )
                .where(
                    TutorProfileOwnershipProof.state == "current",
                    TutorProfileOwnershipProof.expires_at <= terminal_cutoff,
                    TutorProfileOwnershipProof.deleted_at.is_(None),
                    MentorSession.deleted_at.is_(None),
                )
                .order_by(MentorSession.authority_domain_hash)
                .limit(257)
            )
        )
        domain_candidates.update(
            db.scalars(
                select(MentorInvitation.authority_domain_hash)
                .join(
                    MentorSubjectConsent,
                    MentorSubjectConsent.invitation_id == MentorInvitation.id,
                )
                .where(
                    MentorSubjectConsent.status == "granted",
                    MentorSubjectConsent.expires_at <= terminal_cutoff,
                    MentorSubjectConsent.deleted_at.is_(None),
                    MentorInvitation.deleted_at.is_(None),
                )
                .order_by(MentorInvitation.authority_domain_hash)
                .limit(257)
            )
        )
        domain_candidates.update(
            db.scalars(
                select(MentorInvitation.authority_domain_hash)
                .join(
                    MentorCeremony,
                    MentorCeremony.invitation_id == MentorInvitation.id,
                )
                .where(
                    MentorCeremony.state.in_(
                        ("pending_invitation", "challenge_issued", "proof_verified")
                    ),
                    MentorCeremony.expires_at <= terminal_cutoff,
                    MentorCeremony.deleted_at.is_(None),
                    MentorInvitation.deleted_at.is_(None),
                )
                .order_by(MentorInvitation.authority_domain_hash)
                .limit(257)
            )
        )

        for authority_domain_hash in sorted(domain_candidates):
            actor_ids = _candidate_retention_actor_ids(
                db, authority_domain_hash
            )
            if actor_ids:
                # Every authority mutation uses the same actor-keyed lock.
                # Multiple actors indicate a corrupt graph; lock them in one
                # deterministic order, then re-read the complete graph.
                for actor_id in actor_ids:
                    _lock_authority_scope(
                        db,
                        actor_hint=actor_id,
                        fallback=f"authority-domain:{authority_domain_hash}",
                    )
            else:
                _lock_authority_scope(
                    db,
                    fallback=f"authority-domain:{authority_domain_hash}",
                )
            graph = _load_authority_domain_graph(db, authority_domain_hash)
            graph_size = sum(len(rows) for rows in graph.values())
            if graph_size == 0:
                continue
            # Cap decisions precede even expiry materialization. An oversized
            # graph is graph-bit-identical and only emits its NYAY-19 alert.
            if graph_size > SUBJECT_GRAPH_HARD_CAP:
                _record_blocked_retention_graph(
                    db,
                    authority_domain_hash=authority_domain_hash,
                    reason_code="GRAPH_EXCEEDS_HARD_CAP",
                    row_count=graph_size,
                    current=current,
                )
                counts["blocked_graphs"] += 1
                blocked_graph_seen = True
                continue
            if graph_size > settings.mentor_retention_batch_size:
                _record_blocked_retention_graph(
                    db,
                    authority_domain_hash=authority_domain_hash,
                    reason_code="GRAPH_EXCEEDS_BATCH",
                    row_count=graph_size,
                    current=current,
                )
                counts["blocked_graphs"] += 1
                blocked_graph_seen = True
                continue
            materialized = _materialize_authority_domain_expirations(
                graph,
                current=current,
            )
            if not _graph_is_cutoff_eligible(
                graph, current=current, terminal_cutoff=terminal_cutoff
            ):
                counts["materialized_expirations"] += materialized
                remaining = max(0, remaining - materialized)
                continue
            if graph_size > remaining:
                counts["materialized_expirations"] += materialized
                remaining = max(0, remaining - materialized)
                continue
            severed = _sever_authority_graph(graph, current=current)
            db.flush()
            counts["materialized_expirations"] += materialized
            counts["severed_graphs"] += 1
            remaining -= graph_size
            for name, value in severed.items():
                counts[name] += value

        # Pre-proof ceremonies have no actor/domain yet, so a domain-only
        # inventory would retain their provider transaction secrets forever.
        # Discover only opaque row ids, acquire the same ceremony-scoped lock
        # used by public operations, and then lock/recheck the complete orphan
        # graph without SKIP LOCKED before making an erasure decision.
        if remaining > 0:
            orphan_ceremony_ids = list(
                db.scalars(
                    select(MentorCeremony.id)
                    .where(
                        MentorCeremony.actor_user_id.is_(None),
                        MentorCeremony.invitation_id.is_(None),
                        or_(
                            and_(
                                MentorCeremony.state.in_(
                                    ("exchanged", "expired", "revoked", "deleted")
                                ),
                                MentorCeremony.terminal_at.is_not(None),
                                MentorCeremony.terminal_at <= terminal_cutoff,
                            ),
                            and_(
                                MentorCeremony.state.in_(
                                    (
                                        "pending_invitation",
                                        "challenge_issued",
                                        "proof_verified",
                                    )
                                ),
                                MentorCeremony.expires_at <= terminal_cutoff,
                            ),
                        ),
                        MentorCeremony.deleted_at.is_(None),
                    )
                    .order_by(MentorCeremony.id)
                    .limit(257)
                )
            )
            for ceremony_id in orphan_ceremony_ids:
                if remaining <= 0:
                    break
                _lock_authority_scope(
                    db,
                    ceremony_id=ceremony_id,
                    fallback=f"orphan-ceremony:{ceremony_id}",
                )
                graph, materialized = _load_orphan_ceremony_graph(
                    db,
                    ceremony_id,
                    current=current,
                )
                graph_size = sum(len(rows) for rows in graph.values())
                if graph_size == 0:
                    continue
                graph_key = keyed_hash(
                    f"mentor-retention-orphan-ceremony:v1:{ceremony_id}"
                )
                if graph_size > SUBJECT_GRAPH_HARD_CAP:
                    _record_blocked_retention_graph(
                        db,
                        authority_domain_hash=graph_key,
                        reason_code="GRAPH_EXCEEDS_HARD_CAP",
                        row_count=graph_size,
                        current=current,
                    )
                    counts["blocked_graphs"] += 1
                    blocked_graph_seen = True
                    continue
                if graph_size > settings.mentor_retention_batch_size:
                    _record_blocked_retention_graph(
                        db,
                        authority_domain_hash=graph_key,
                        reason_code="GRAPH_EXCEEDS_BATCH",
                        row_count=graph_size,
                        current=current,
                    )
                    counts["blocked_graphs"] += 1
                    blocked_graph_seen = True
                    continue
                materialized = _materialize_authority_domain_expirations(
                    graph, current=current
                )
                if not _graph_is_cutoff_eligible(
                    graph,
                    current=current,
                    terminal_cutoff=terminal_cutoff,
                ):
                    counts["materialized_expirations"] += materialized
                    remaining = max(0, remaining - materialized)
                    continue
                if graph_size > remaining:
                    counts["materialized_expirations"] += materialized
                    remaining = max(0, remaining - materialized)
                    continue
                severed = _sever_authority_graph(graph, current=current)
                db.flush()
                counts["materialized_expirations"] += materialized
                counts["severed_graphs"] += 1
                remaining -= graph_size
                for name, value in severed.items():
                    counts[name] += value

        # A bootstrap that was never exchanged for a ceremony is its own
        # bounded, non-authoritative graph.  Linked bootstraps are deliberately
        # excluded and are handled with their ceremony above.
        if remaining > 0:
            standalone_bootstraps = list(
                db.execute(
                    select(
                        MentorBootstrapAttempt.id,
                        MentorBootstrapAttempt.token_hash,
                    )
                    .where(
                        or_(
                            and_(
                                MentorBootstrapAttempt.state.in_(
                                    ("consumed", "expired")
                                ),
                                MentorBootstrapAttempt.consumed_at.is_not(None),
                                MentorBootstrapAttempt.consumed_at
                                <= terminal_cutoff,
                            ),
                            and_(
                                MentorBootstrapAttempt.state == "active",
                                MentorBootstrapAttempt.expires_at
                                <= terminal_cutoff,
                            ),
                        ),
                        MentorBootstrapAttempt.deleted_at.is_(None),
                        ~MentorBootstrapAttempt.id.in_(
                            select(MentorCeremony.bootstrap_attempt_id).where(
                                MentorCeremony.bootstrap_attempt_id.is_not(None),
                                MentorCeremony.deleted_at.is_(None),
                            )
                        ),
                    )
                    .order_by(MentorBootstrapAttempt.id)
                    .limit(remaining)
                )
            )
            for bootstrap_id, bootstrap_token_hash in standalone_bootstraps:
                if remaining <= 0:
                    break
                _lock_authority_scope(
                    db,
                    fallback=f"bootstrap:{bootstrap_token_hash}",
                )
                graph, materialized = _load_standalone_bootstrap_graph(
                    db,
                    bootstrap_id,
                    current=current,
                )
                graph_size = sum(len(rows) for rows in graph.values())
                if graph_size != 1 or not _graph_is_cutoff_eligible(
                    graph,
                    current=current,
                    terminal_cutoff=terminal_cutoff,
                ):
                    counts["materialized_expirations"] += materialized
                    remaining = max(0, remaining - materialized)
                    continue
                severed = _sever_authority_graph(graph, current=current)
                db.flush()
                counts["materialized_expirations"] += materialized
                counts["severed_graphs"] += 1
                remaining -= graph_size
                for name, value in severed.items():
                    counts[name] += value

        # Ownership proofs can predate any ceremony.  Once their authoritative
        # expiry is beyond the retention window and no surviving ceremony or
        # session references them, erase their identity linkage under the
        # actor lock.  Shared proofs stay intact until the last dependent graph
        # has been severed.
        if remaining > 0:
            standalone_proofs = list(
                db.execute(
                    select(
                        TutorProfileOwnershipProof.id,
                        TutorProfileOwnershipProof.user_id,
                    )
                    .where(
                        or_(
                            and_(
                                TutorProfileOwnershipProof.state.in_(
                                    ("expired", "revoked", "deleted")
                                ),
                                TutorProfileOwnershipProof.revoked_at.is_not(None),
                                TutorProfileOwnershipProof.revoked_at
                                <= terminal_cutoff,
                            ),
                            and_(
                                TutorProfileOwnershipProof.state == "current",
                                TutorProfileOwnershipProof.expires_at
                                <= terminal_cutoff,
                            ),
                        ),
                        TutorProfileOwnershipProof.deleted_at.is_(None),
                        ~TutorProfileOwnershipProof.id.in_(
                            select(MentorCeremony.ownership_proof_id).where(
                                MentorCeremony.ownership_proof_id.is_not(None),
                                MentorCeremony.deleted_at.is_(None),
                            )
                        ),
                        ~TutorProfileOwnershipProof.id.in_(
                            select(MentorSession.ownership_proof_id).where(
                                MentorSession.ownership_proof_id.is_not(None),
                                MentorSession.deleted_at.is_(None),
                            )
                        ),
                    )
                    .order_by(TutorProfileOwnershipProof.id)
                    .limit(remaining)
                )
            )
            for proof_id, proof_actor_id in standalone_proofs:
                if remaining <= 0:
                    break
                _lock_authority_scope(
                    db,
                    actor_hint=proof_actor_id,
                    fallback=f"proof:{proof_id}",
                )
                graph, materialized = _load_standalone_proof_graph(
                    db,
                    proof_id,
                    current=current,
                )
                graph_size = sum(len(rows) for rows in graph.values())
                if graph_size != 1 or not _graph_is_cutoff_eligible(
                    graph,
                    current=current,
                    terminal_cutoff=terminal_cutoff,
                ):
                    counts["materialized_expirations"] += materialized
                    remaining = max(0, remaining - materialized)
                    continue
                severed = _sever_authority_graph(graph, current=current)
                db.flush()
                counts["materialized_expirations"] += materialized
                counts["severed_graphs"] += 1
                remaining -= graph_size
                for name, value in severed.items():
                    counts[name] += value

        # Expiry materialization intentionally runs after all actor/domain lock
        # acquisition.  Its SKIP LOCKED scan may defer a busy row, but it can
        # never omit a node from a graph being severed or create the inverse
        # row-lock -> advisory-lock order.
        # The generic sweep cannot prove that a row is outside a graph whose
        # bounded inventory was refused.  If any graph was blocked, defer this
        # sweep rather than mutate even one potentially connected row.  The
        # durable NYAY-19 register makes the deferral visible and actionable.
        newly_materialized = (
            0
            if blocked_graph_seen
            else _materialize_mentor_expirations(
                db, current=current, limit=remaining
            )
        )
        counts["materialized_expirations"] += newly_materialized
        remaining -= newly_materialized

        # Short-lived abuse buckets are not part of an authority graph.  They
        # are safe to delete only after their own closed expiry and within the
        # same aggregate batch budget.
        buckets = _retention_rows(
            db,
            MentorRateBucket,
            MentorRateBucket.expires_at <= current,
            limit=remaining,
        )
        for row in buckets:
            db.delete(row)
        counts["rate_buckets"] = len(buckets)
        db.commit()
        return counts
    except Exception:
        db.rollback()
        raise
    finally:
        _RETENTION_GUARD.release()


def materialize_subject_mentor_privacy_export(
    db: Session,
    subject_registration_id: uuid.UUID,
) -> dict[str, Any]:
    """Return human-meaningful mentor history without security internals/IDs."""

    invitations = list(
        db.scalars(
            select(MentorInvitation)
            .where(MentorInvitation.subject_registration_id == subject_registration_id)
            .order_by(MentorInvitation.created_at, MentorInvitation.id)
        )
    )
    invitation_ids = [row.id for row in invitations]
    ceremonies: dict[uuid.UUID, list[MentorCeremony]] = {}
    for row in db.scalars(
        select(MentorCeremony)
        .where(
            MentorCeremony.invitation_id.in_(
                invitation_ids or [uuid.UUID(int=0)]
            )
        )
        .order_by(MentorCeremony.created_at, MentorCeremony.id)
    ):
        if row.invitation_id is not None:
            ceremonies.setdefault(row.invitation_id, []).append(row)
    consents = {
        row.invitation_id: row
        for row in db.scalars(
            select(MentorSubjectConsent).where(
                MentorSubjectConsent.invitation_id.in_(
                    invitation_ids or [uuid.UUID(int=0)]
                )
            )
        )
    }
    return {
        "schema_version": "mentor-subject-history-export.v1",
        "mentor_history": [
            {
                "mentor_role": row.mentor_role,
                "purpose_code": row.purpose_code,
                "invitation_state": row.state,
                "consent": (
                    {
                        "status": consents[row.id].status,
                        "version": consents[row.id].version,
                        "disclosure_classes": list(
                            consents[row.id].disclosure_classes
                        ),
                    }
                    if row.id in consents
                    else None
                ),
                "ceremonies": [
                    {
                        "intent": ceremony.intent,
                        "state": ceremony.state,
                        "recovery": ceremony.recovery,
                        "verification_policy_version": (
                            ceremony.verification_policy_version
                        ),
                        "verified_at": (
                            _utc(ceremony.verified_at).isoformat()
                            if ceremony.verified_at is not None
                            else None
                        ),
                        "terminal_at": (
                            _utc(ceremony.terminal_at).isoformat()
                            if ceremony.terminal_at is not None
                            else None
                        ),
                    }
                    for ceremony in ceremonies.get(row.id, [])
                ],
            }
            for row in invitations
        ],
    }
