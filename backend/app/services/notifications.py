"""Notification & reminder scaffolding (SAATHI-340).

Provider interfaces for email, SMS/WhatsApp, and push with DEV/NO-OP adapters only
(no real providers wired). Payloads are privacy-safe: sensitive content is never
logged, and dispatch emits an audit event (redaction handled by the audit service).
Built to run on top of the worker foundation (SAATHI-336).
"""
from __future__ import annotations

import abc
import uuid
from dataclasses import dataclass, field
from enum import Enum


class Channel(str, Enum):
    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    PUSH = "push"
    IN_APP = "in_app"


class DeliveryStatus(str, Enum):
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"


@dataclass
class NotificationMessage:
    channel: Channel
    template_key: str            # references a template; body is rendered by provider
    to_ref: str                  # opaque recipient ref/token — NOT a raw email/phone
    variables: dict = field(default_factory=dict)  # non-sensitive template vars only
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def safe_log_view(self) -> dict:
        """Privacy-safe projection for logs: no recipient, no variable values."""
        return {
            "id": self.id,
            "channel": self.channel.value,
            "template_key": self.template_key,
            "variable_keys": sorted(self.variables.keys()),  # keys only, never values
        }


class NotificationProvider(abc.ABC):
    channel: Channel

    @abc.abstractmethod
    def send(self, message: NotificationMessage) -> DeliveryStatus: ...


class NoOpProvider(NotificationProvider):
    """Dev/no-op adapter: records the send without contacting any external service."""

    def __init__(self, channel: Channel) -> None:
        self.channel = channel
        self.sent: list[str] = []

    def send(self, message: NotificationMessage) -> DeliveryStatus:
        self.sent.append(message.id)
        return DeliveryStatus.SENT


class NotificationService:
    """Routes a message to the channel's provider. Dev registry = no-op providers.
    Optionally records a privacy-safe audit event on dispatch."""

    def __init__(self, providers: dict[Channel, NotificationProvider] | None = None) -> None:
        self.providers = providers or {c: NoOpProvider(c) for c in Channel}

    def dispatch(self, message: NotificationMessage, *, audit=None, session=None) -> DeliveryStatus:
        provider = self.providers[message.channel]
        status = provider.send(message)
        if audit is not None and session is not None:
            # after_state carries only the privacy-safe view (no recipient/content).
            audit(
                session,
                action="notification.dispatch",
                resource_type="notification",
                after_state={**message.safe_log_view(), "status": status.value},
            )
        return status


# --- Reminder scheduling interfaces (model/service shape; no persistence here) ---

@dataclass
class ReminderRule:
    """Reminder relative to a source event (aligned to calendar_reminders in the
    data model): channel + minutes-before offset + enabled flag."""

    channel: Channel
    offset_minutes: int
    enabled: bool = True
    id: str = field(default_factory=lambda: uuid.uuid4().hex)


def due_reminders(rules: list[ReminderRule], minutes_to_event: int) -> list[ReminderRule]:
    """Pure selection: which enabled rules fire given minutes remaining to the event."""
    return [r for r in rules if r.enabled and minutes_to_event <= r.offset_minutes]
