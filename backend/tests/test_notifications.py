"""Notification & reminder tests (SAATHI-340/379/380)."""
from __future__ import annotations

from app.services.audit_service import record_audit_event
from app.services.notifications import (
    Channel,
    DeliveryStatus,
    NotificationMessage,
    NotificationService,
    ReminderRule,
    due_reminders,
)


def _msg(channel=Channel.EMAIL) -> NotificationMessage:
    return NotificationMessage(
        channel=channel,
        template_key="internship.status_changed",
        to_ref="user-ref-123",  # opaque, not a real email/phone
        variables={"application_id": "abc", "status": "under_review"},
    )


def test_noop_provider_dispatch_returns_sent() -> None:
    svc = NotificationService()
    assert svc.dispatch(_msg()) is DeliveryStatus.SENT
    assert svc.dispatch(_msg(Channel.WHATSAPP)) is DeliveryStatus.SENT


def test_safe_log_view_excludes_recipient_and_values() -> None:
    view = _msg().safe_log_view()
    assert "to_ref" not in view  # recipient never in log view
    assert view["variable_keys"] == ["application_id", "status"]  # keys only
    assert "abc" not in str(view) and "under_review" not in str(view)  # no values


def test_dispatch_emits_privacy_safe_audit(db_session) -> None:
    svc = NotificationService()
    svc.dispatch(_msg(), audit=record_audit_event, session=db_session)
    db_session.commit()
    from app.db.models.audit import AuditEvent

    ev = db_session.query(AuditEvent).filter_by(action="notification.dispatch").one()
    # audit after_state carries only the safe view (no recipient/values)
    assert ev.after_state["channel"] == "email"
    assert "to_ref" not in ev.after_state
    assert ev.after_state["status"] == "sent"


def test_due_reminders_selection() -> None:
    rules = [
        ReminderRule(channel=Channel.PUSH, offset_minutes=60),
        ReminderRule(channel=Channel.EMAIL, offset_minutes=1440),
        ReminderRule(channel=Channel.SMS, offset_minutes=15, enabled=False),
    ]
    # 30 min to event: the 60-min and 1440-min enabled rules fire; disabled SMS never.
    fired = due_reminders(rules, minutes_to_event=30)
    channels = {r.channel for r in fired}
    assert Channel.PUSH in channels and Channel.EMAIL in channels
    assert Channel.SMS not in channels
