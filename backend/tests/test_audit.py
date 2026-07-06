"""Tests for the audit event service (SAATHI-338)."""
from __future__ import annotations

import uuid

from app.db.models.audit import AuditEvent
from app.services.audit_service import record_audit_event, redact, serialize_audit_event


def test_redaction_of_sensitive_keys() -> None:
    dirty = {"email": "a@b.com", "otp": "123456", "name": "Aarav", "nested": {"token": "x", "ok": 1}}
    clean = redact(dirty)
    assert clean["email"] == "[redacted]"
    assert clean["otp"] == "[redacted]"
    assert clean["name"] == "Aarav"
    assert clean["nested"]["token"] == "[redacted]"
    assert clean["nested"]["ok"] == 1


def test_record_audit_event_hashes_and_redacts(db_session) -> None:
    actor = uuid.uuid4()
    res = uuid.uuid4()
    event = record_audit_event(
        db_session,
        action="application.submit",
        resource_type="internship_application",
        resource_id=res,
        actor_user_id=actor,
        actor_role="student",
        after_state={"status": "applied", "email": "a@b.com"},
        ip="203.0.113.5",
        user_agent="Mozilla/5.0",
    )
    db_session.commit()

    assert isinstance(event.id, uuid.UUID)
    assert event.created_at is not None
    # sensitive value redacted, non-sensitive kept
    assert event.after_state["email"] == "[redacted]"
    assert event.after_state["status"] == "applied"
    # raw ip/ua never stored in the clear
    assert event.ip_hash and event.ip_hash != "203.0.113.5" and len(event.ip_hash) == 64
    assert event.user_agent_hash and event.user_agent_hash != "Mozilla/5.0"


def test_audit_event_is_append_only_shape() -> None:
    cols = set(AuditEvent.__table__.columns.keys())
    assert "created_at" in cols
    assert "updated_at" not in cols and "deleted_at" not in cols


def test_serialize_audit_event(db_session) -> None:
    event = record_audit_event(
        db_session, action="x.do", resource_type="thing", after_state={"a": 1}
    )
    db_session.commit()
    data = serialize_audit_event(event)
    assert data["action"] == "x.do"
    assert data["resource_type"] == "thing"
    assert data["after_state"] == {"a": 1}
    assert "created_at" in data
