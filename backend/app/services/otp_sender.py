"""OTP delivery provider seam (SAATHI-448 critical #3).

Production wires a real SMS/email provider here via configuration. When no
provider is configured the resolver returns None and the API layer fails closed
(503) — it must NEVER claim an OTP was sent. The raw code is passed only to the
provider and is never logged or returned.
"""
from __future__ import annotations

from typing import Protocol

from app.core.config import settings


class OtpSendError(Exception):
    """Raised when a configured provider fails to deliver — triggers rollback."""


class OtpSender(Protocol):
    def send(self, destination: str, code: str) -> None: ...


class CapturingSender:
    """Test/dev double that records deliveries without emitting anything."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, destination: str, code: str) -> None:
        self.sent.append((destination, code))


def build_otp_sender() -> OtpSender | None:
    """Resolve the configured provider, or None when delivery is not configured.

    No real SMS/email provider is wired in this environment, so this returns None
    and the API fails closed. A deployment sets `otp_delivery_enabled=True` and
    provides a concrete provider binding.
    """
    if not getattr(settings, "otp_delivery_enabled", False):
        return None
    return None  # placeholder for the concrete provider binding
