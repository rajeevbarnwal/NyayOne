"""Audit event service + helper API (SAATHI-338).

Records immutable audit events for state-changing operations. Enforces
compliance-safe defaults: sensitive keys are redacted from before/after state,
and raw IP / user-agent are stored only as salted hashes — never in the clear.
"""
from __future__ import annotations

import hashlib
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.db.models.audit import AuditEvent

# Keys whose values must never be persisted in audit before/after snapshots.
SENSITIVE_KEYS = frozenset(
    {
        "password", "token", "access_token", "refresh_token", "otp", "secret",
        "api_key", "authorization", "aadhaar", "bar_enrolment_no", "email",
        "phone", "vector", "embedding", "raw_body", "prompt",
    }
)
REDACTED = "[redacted]"


def redact(payload: Any) -> Any:
    """Recursively redact sensitive keys from a dict/list before it is stored."""
    if isinstance(payload, dict):
        return {k: (REDACTED if k.lower() in SENSITIVE_KEYS else redact(v)) for k, v in payload.items()}
    if isinstance(payload, list):
        return [redact(v) for v in payload]
    return payload


def _hash(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def record_audit_event(
    session: Session,
    *,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
    before_state: dict | None = None,
    after_state: dict | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    flush: bool = True,
) -> AuditEvent:
    """Create and persist an audit event with redaction + hashing applied.

    Does not commit — the caller's unit of work owns the transaction so the
    audit row lives or dies with the business change it records.
    """
    event = AuditEvent(
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        before_state=redact(before_state) if before_state is not None else None,
        after_state=redact(after_state) if after_state is not None else None,
        ip_hash=_hash(ip),
        user_agent_hash=_hash(user_agent),
    )
    session.add(event)
    if flush:
        session.flush()
    return event


def serialize_audit_event(event: AuditEvent) -> dict:
    return {
        "id": str(event.id),
        "actor_user_id": str(event.actor_user_id) if event.actor_user_id else None,
        "actor_role": event.actor_role,
        "action": event.action,
        "resource_type": event.resource_type,
        "resource_id": str(event.resource_id) if event.resource_id else None,
        "before_state": event.before_state,
        "after_state": event.after_state,
        "ip_hash": event.ip_hash,
        "user_agent_hash": event.user_agent_hash,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }
