"""OTP delivery provider seam (SAATHI-448 A1).

A deployment binds a concrete provider via configuration. When delivery is
enabled the resolver returns a real, non-None adapter; when it is disabled (or
misconfigured) it returns None and the API layer fails closed (503) — it must
NEVER claim an OTP was sent. The raw code is passed only to the provider's
``send`` and is never logged or returned.

Providers:
- ``HttpOtpSender``   — real adapter, POSTs to a configured provider endpoint.
- ``CapturingSender`` — in-memory double for tests/dev; records deliveries.
- ``NullSender``      — explicit "disabled"; resolver returns None instead.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.core.config import settings


class OtpSendError(Exception):
    """Raised when a configured provider fails to deliver."""


@runtime_checkable
class IdempotentOtpSender(Protocol):
    """Provider contract required by non-test deployments (NYAY-4)."""

    def send_idempotent(
        self,
        destination: str,
        code: str,
        *,
        idempotency_token: str,
    ) -> str | None: ...


class CapturingSender:
    """Test/dev double that records deliveries without emitting anything."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self._idempotent: dict[str, tuple[str, str, str]] = {}

    def send_idempotent(
        self,
        destination: str,
        code: str,
        *,
        idempotency_token: str,
    ) -> str | None:
        existing = self._idempotent.get(idempotency_token)
        if existing is not None:
            if existing[:2] != (destination, code):
                raise OtpSendError("otp provider idempotency conflict")
            return existing[2]
        receipt = f"capture-{len(self._idempotent) + 1}"
        self._idempotent[idempotency_token] = (destination, code, receipt)
        self.sent.append((destination, code))
        return receipt


class HttpOtpSender:
    """Real provider adapter. POSTs {to, message} to a configured HTTP endpoint.

    Uses httpx (already a backend dependency). Any transport/HTTP error is
    normalised to OtpSendError so callers never see provider internals, and the
    raw code is never logged.
    """

    def __init__(self, url: str, token: str | None = None, timeout_s: float = 10.0) -> None:
        self._url = url
        self._token = token
        self._timeout_s = timeout_s

    def send_idempotent(
        self,
        destination: str,
        code: str,
        *,
        idempotency_token: str,
    ) -> str | None:
        import httpx

        headers = {
            "Idempotency-Key": idempotency_token,
            **(
                {"Authorization": f"Bearer {self._token}"}
                if self._token
                else {}
            ),
        }
        try:
            resp = httpx.post(
                self._url,
                json={
                    "to": destination,
                    "message": f"Your NyayOne verification code is {code}",
                    "idempotency_key": idempotency_token,
                },
                headers=headers,
                timeout=self._timeout_s,
            )
            resp.raise_for_status()
            return resp.headers.get("X-Provider-Receipt")
        except Exception as exc:  # normalise everything; never leak the code
            raise OtpSendError(f"otp provider send failed: {type(exc).__name__}") from exc


def build_otp_sender() -> IdempotentOtpSender | None:
    """Resolve the configured provider, or None when delivery is not configured.

    Contract (SAATHI-448 A1): when delivery is enabled AND a concrete provider is
    selected, this MUST return a non-None sender. It returns None only when
    delivery is disabled or the provider is explicitly "none".
    """
    if not getattr(settings, "otp_delivery_enabled", False):
        return None
    provider = (getattr(settings, "otp_provider", "none") or "none").lower()
    if provider == "capturing":
        if (settings.app_env or "").strip().casefold() not in {"test", "testing"}:
            return None
        return CapturingSender()
    if provider == "http":
        if not settings.otp_provider_url:
            # Enabled but not fully configured — fail closed rather than pretend.
            return None
        if not getattr(settings, "otp_provider_supports_idempotency", False):
            return None
        token = settings.otp_provider_token.get_secret_value() if settings.otp_provider_token else None
        return HttpOtpSender(settings.otp_provider_url, token, settings.otp_provider_timeout_s)
    return None  # "none" or unknown → fail closed
