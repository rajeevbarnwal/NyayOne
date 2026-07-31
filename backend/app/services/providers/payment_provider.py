"""Payment provider seam (SAATHI-123 / SAATHI-127 P2).

Mirrors the approved OTP provider seam (``app.services.otp_sender``): a
Protocol, a deterministic in-process adapter for dev/test, a real config-driven
adapter that fails closed, and a ``build_payment_provider()`` resolver that
returns ``None`` when the deployment is not fully configured.

Money rules (frozen product decisions):
* INR only, INTEGER PAISE only. No floats, no Decimal rupees, no other currency.
* A hold becomes a session ONLY on a signature-VERIFIED provider event whose
  ``event_type`` maps to ``paid``. Failure/expiry RELEASES the slot.

Card-data rules (non-negotiable):
* This module NEVER accepts, returns, persists or logs a PAN, a CVV or a
  payment OTP. The tokenised surface accepts a provider *token id* only
  (``tok_test_success`` and friends); ``_reject_card_data`` actively refuses
  anything that looks like cardholder data so a mis-wired caller fails loudly
  instead of leaking.
* Only issuer display crumbs (brand, last four, expiry month/year) cross the
  seam, matching the columns that exist on ``payment_orders``.
* Raw webhook bodies never leave this module: callers receive a typed event
  plus a ``payload_digest`` (SHA-256 hex) for the ledger.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.core.config import has_secret, settings

# --------------------------------------------------------------------------- #
# Typed error
# --------------------------------------------------------------------------- #


class PaymentProviderError(Exception):
    """Provider-boundary failure.

    ``retryable`` distinguishes "the provider might succeed if we ask again"
    (timeout, 5xx, transport error) from "asking again cannot help" (invalid
    signature, declined token, misconfiguration). The outbox relay and the
    service layer both branch on it; nothing else about the provider leaks.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "PROVIDER_ERROR",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"PaymentProviderError(code={self.code!r}, "
            f"retryable={self.retryable!r})"
        )


# --------------------------------------------------------------------------- #
# Typed value objects crossing the seam
# --------------------------------------------------------------------------- #

#: Provider-neutral event outcomes. Only ``paid`` may create a session.
EVENT_PAID = "paid"
EVENT_FAILED = "failed"
EVENT_EXPIRED = "expired"
EVENT_PENDING = "pending"
EVENT_TYPES = (EVENT_PAID, EVENT_FAILED, EVENT_EXPIRED, EVENT_PENDING)


@dataclass(frozen=True)
class PaymentOrderResult:
    """What the provider gives back when an order/intent is created."""

    provider: str
    provider_order_ref: str
    amount_paise: int
    currency: str
    status: str = "created"


@dataclass(frozen=True)
class PaymentEventData:
    """A verified, provider-neutral payment event.

    ``signature_verified`` is only ever True: an adapter raises rather than
    returning an unverified event, so the service layer cannot accidentally
    act on a forged webhook. The field exists because the
    ``payment_events.signature_verified`` column records the fact.
    """

    provider: str
    provider_event_id: str
    event_type: str
    provider_order_ref: str
    amount_paise: int
    currency: str
    payload_digest: str
    raw_event_type: str = ""
    brand: str | None = None
    masked_last4: str | None = None
    expiry_month: int | None = None
    expiry_year: int | None = None
    signature_verified: bool = True


@dataclass(frozen=True)
class PaymentRefundResult:
    """Provider outcome for a refund request. Amount is integer paise."""

    provider: str
    provider_refund_ref: str
    amount_paise: int
    status: str = "succeeded"


# --------------------------------------------------------------------------- #
# Protocol
# --------------------------------------------------------------------------- #


@runtime_checkable
class PaymentProvider(Protocol):
    """The only payment surface the domain services are allowed to know."""

    name: str

    def create_order(
        self,
        *,
        amount_paise: int,
        currency: str,
        idempotency_key: str,
        reference: str,
    ) -> PaymentOrderResult: ...

    def verify_event(self, signature: str, raw_body: bytes) -> PaymentEventData: ...

    def refund(
        self,
        *,
        provider_order_ref: str,
        amount_paise: int,
        idempotency_key: str,
        reason: str,
    ) -> PaymentRefundResult: ...


# --------------------------------------------------------------------------- #
# Shared guards / helpers
# --------------------------------------------------------------------------- #

#: Test-surface token ids. A *token id* is an opaque provider handle produced by
#: the provider's own client-side tokenisation step; it is NOT card data.
TOKEN_SUCCESS = "tok_test_success"
TOKEN_DECLINED = "tok_test_declined"
TOKEN_PENDING = "tok_test_pending"
TOKEN_TIMEOUT = "tok_test_timeout"
TEST_TOKENS = (TOKEN_SUCCESS, TOKEN_DECLINED, TOKEN_PENDING, TOKEN_TIMEOUT)

_TOKEN_RE = re.compile(r"^tok_[A-Za-z0-9_]{3,60}$")
# 13-19 consecutive digits (optionally space/dash grouped) smells like a PAN;
# a bare 3-4 digit group passed as a "token" smells like a CVV/OTP.
_PAN_RE = re.compile(r"^[0-9][0-9 \-]{11,22}[0-9]$")
_SHORT_NUMERIC_RE = re.compile(r"^[0-9]{3,8}$")

_DEV_DEFAULT_SECRETS = frozenset(
    {"", "changeme", "change-me", "test", "secret", "razorpay", "dev", "dev-secret"}
)


def _reject_card_data(token: str) -> None:
    """Fail loudly if a caller hands us anything resembling card data.

    Defence in depth for the "never persist or log raw PAN/CVV/payment-OTP"
    rule: the seam refuses the value outright, so it can never reach a log
    line, an audit payload or a provider call.
    """
    candidate = (token or "").strip()
    if not candidate:
        raise PaymentProviderError(
            "payment token id is required", code="TOKEN_REQUIRED"
        )
    stripped = candidate.replace(" ", "").replace("-", "")
    if _PAN_RE.match(candidate) or (stripped.isdigit() and len(stripped) >= 12):
        raise PaymentProviderError(
            "refusing a card-number-shaped value: pass a provider token id",
            code="CARD_DATA_REFUSED",
        )
    if _SHORT_NUMERIC_RE.match(candidate):
        raise PaymentProviderError(
            "refusing a CVV/OTP-shaped value: pass a provider token id",
            code="CARD_DATA_REFUSED",
        )
    if not _TOKEN_RE.match(candidate):
        raise PaymentProviderError(
            "malformed provider token id", code="TOKEN_INVALID"
        )


def _assert_money(amount_paise: int, currency: str) -> None:
    if isinstance(amount_paise, bool) or not isinstance(amount_paise, int):
        raise PaymentProviderError(
            "amount must be integer paise", code="AMOUNT_INVALID"
        )
    if amount_paise < 0:
        raise PaymentProviderError(
            "amount must not be negative", code="AMOUNT_INVALID"
        )
    if currency != "INR":
        raise PaymentProviderError(
            "only INR is supported", code="CURRENCY_UNSUPPORTED"
        )


def digest_body(raw_body: bytes) -> str:
    """SHA-256 hex digest of a webhook body — the only thing we may persist."""
    if isinstance(raw_body, str):  # pragma: no cover - defensive
        raw_body = raw_body.encode("utf-8")
    return hashlib.sha256(raw_body).hexdigest()


def _hmac_hex(secret: bytes, raw_body: bytes) -> str:
    return hmac.new(secret, raw_body, hashlib.sha256).hexdigest()


# --------------------------------------------------------------------------- #
# Deterministic adapter (dev/test; no network, no card data)
# --------------------------------------------------------------------------- #

#: Signature key for the deterministic adapter. Deliberately a fixed,
#: publicly-known TEST value: the adapter is only ever selected when
#: ``settings.payment_provider == "deterministic"``, which production must not
#: use. Tests forge both valid and invalid signatures with ``sign()``.
DETERMINISTIC_SIGNING_KEY = b"legalsaathi-deterministic-payment-test-key"


class DeterministicPaymentAdapter:
    """In-process payment provider with a fully deterministic, tokenised surface.

    Behaviour is a pure function of the provider *token id*:

    ==========================  ===========================================
    token id                    outcome
    ==========================  ===========================================
    ``tok_test_success``        webhook event ``paid``
    ``tok_test_declined``       webhook event ``failed``
    ``tok_test_pending``        webhook event ``pending`` (no side effects)
    ``tok_test_timeout``        RETRYABLE ``PaymentProviderError``
    ==========================  ===========================================

    Signature scheme: ``HMAC-SHA256(DETERMINISTIC_SIGNING_KEY, raw_body)`` in
    lowercase hex, compared with :func:`hmac.compare_digest` exactly as the real
    adapter does. ``sign()``/``make_event_body()`` let tests forge a valid
    signature, and any other value is a forged one.
    """

    name = "deterministic"

    def __init__(self, signing_key: bytes = DETERMINISTIC_SIGNING_KEY) -> None:
        self._key = signing_key
        # Observability for tests only: refs, never card data or tokens' effects.
        self.created_orders: list[str] = []
        self.refunds: list[tuple[str, int]] = []

    # -- signing helpers (test surface) ---------------------------------- #
    def sign(self, raw_body: bytes) -> str:
        """Return the valid signature for ``raw_body``."""
        if isinstance(raw_body, str):
            raw_body = raw_body.encode("utf-8")
        return _hmac_hex(self._key, raw_body)

    def make_event_body(
        self,
        *,
        provider_order_ref: str,
        amount_paise: int,
        token: str = TOKEN_SUCCESS,
        event_id: str | None = None,
        currency: str = "INR",
        brand: str | None = "TESTCARD",
        masked_last4: str | None = "4242",
        expiry_month: int | None = 12,
        expiry_year: int | None = 2030,
    ) -> tuple[bytes, str]:
        """Build ``(raw_body, valid_signature)`` for a deterministic webhook.

        ``token`` selects the outcome; it is a token *id*, never card data.
        ``masked_last4`` is an issuer display crumb (4 chars) — the schema has
        no column able to hold more, by design.
        """
        _reject_card_data(token)
        _assert_money(amount_paise, currency)
        if token == TOKEN_TIMEOUT:
            raise PaymentProviderError(
                "provider timed out", code="PROVIDER_TIMEOUT", retryable=True
            )
        payload = {
            "provider": self.name,
            "event_id": event_id
            or f"det_evt_{hashlib.sha256((provider_order_ref + token).encode()).hexdigest()[:20]}",
            "token": token,
            "event_type": self._event_type_for(token),
            "order_ref": provider_order_ref,
            "amount_paise": amount_paise,
            "currency": currency,
            "brand": brand,
            "masked_last4": masked_last4,
            "expiry_month": expiry_month,
            "expiry_year": expiry_year,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return raw, self.sign(raw)

    @staticmethod
    def _event_type_for(token: str) -> str:
        return {
            TOKEN_SUCCESS: EVENT_PAID,
            TOKEN_DECLINED: EVENT_FAILED,
            TOKEN_PENDING: EVENT_PENDING,
        }.get(token, EVENT_FAILED)

    # -- Protocol ------------------------------------------------------- #
    def create_order(
        self,
        *,
        amount_paise: int,
        currency: str,
        idempotency_key: str,
        reference: str,
    ) -> PaymentOrderResult:
        _assert_money(amount_paise, currency)
        if not idempotency_key:
            raise PaymentProviderError(
                "idempotency key is required", code="IDEMPOTENCY_REQUIRED"
            )
        ref = "det_ord_" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:24]
        self.created_orders.append(ref)
        return PaymentOrderResult(
            provider=self.name,
            provider_order_ref=ref,
            amount_paise=amount_paise,
            currency=currency,
        )

    def verify_event(self, signature: str, raw_body: bytes) -> PaymentEventData:
        if isinstance(raw_body, str):
            raw_body = raw_body.encode("utf-8")
        expected = self.sign(raw_body)
        if not signature or not hmac.compare_digest(expected, str(signature)):
            raise PaymentProviderError(
                "webhook signature verification failed",
                code="SIGNATURE_INVALID",
            )
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except Exception as exc:  # never echo the body back
            raise PaymentProviderError(
                f"malformed webhook body: {type(exc).__name__}",
                code="PAYLOAD_MALFORMED",
            ) from exc
        event_type = str(payload.get("event_type") or "")
        if event_type not in EVENT_TYPES:
            raise PaymentProviderError(
                "unsupported event type", code="EVENT_TYPE_UNSUPPORTED"
            )
        return PaymentEventData(
            provider=self.name,
            provider_event_id=str(payload["event_id"]),
            event_type=event_type,
            raw_event_type=event_type,
            provider_order_ref=str(payload["order_ref"]),
            amount_paise=int(payload["amount_paise"]),
            currency=str(payload.get("currency") or "INR"),
            payload_digest=digest_body(raw_body),
            brand=payload.get("brand"),
            masked_last4=payload.get("masked_last4"),
            expiry_month=payload.get("expiry_month"),
            expiry_year=payload.get("expiry_year"),
        )

    def refund(
        self,
        *,
        provider_order_ref: str,
        amount_paise: int,
        idempotency_key: str,
        reason: str,
    ) -> PaymentRefundResult:
        _assert_money(amount_paise, "INR")
        if amount_paise == 0:
            raise PaymentProviderError(
                "refund amount must be positive", code="AMOUNT_INVALID"
            )
        if provider_order_ref.endswith("_timeout"):  # test hook for retryables
            raise PaymentProviderError(
                "provider timed out", code="PROVIDER_TIMEOUT", retryable=True
            )
        ref = "det_rfnd_" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:22]
        self.refunds.append((provider_order_ref, amount_paise))
        return PaymentRefundResult(
            provider=self.name, provider_refund_ref=ref, amount_paise=amount_paise
        )


class FailingPaymentAdapter:
    """Test double whose every call raises a configurable typed error.

    Used to prove that provider failure surfaces as a TYPED, correctly-flagged
    error (retryable vs not) instead of an opaque exception.
    """

    name = "deterministic"

    def __init__(self, *, retryable: bool = True, code: str = "PROVIDER_TIMEOUT") -> None:
        self._retryable = retryable
        self._code = code

    def _boom(self):
        raise PaymentProviderError(
            "provider unavailable", code=self._code, retryable=self._retryable
        )

    def create_order(self, **_kwargs) -> PaymentOrderResult:
        self._boom()

    def verify_event(self, signature: str, raw_body: bytes) -> PaymentEventData:
        self._boom()

    def refund(self, **_kwargs) -> PaymentRefundResult:
        self._boom()


# --------------------------------------------------------------------------- #
# Razorpay adapter (real boundary)
# --------------------------------------------------------------------------- #

#: Razorpay event names -> provider-neutral outcomes.
_RAZORPAY_EVENT_MAP = {
    "payment.captured": EVENT_PAID,
    "order.paid": EVENT_PAID,
    "payment.failed": EVENT_FAILED,
    "payment.authorized": EVENT_PENDING,
    "order.expired": EVENT_EXPIRED,
    "payment.pending": EVENT_PENDING,
}


class RazorpayAdapter:
    """Razorpay boundary. Config-driven, fails closed, no vendor SDK required.

    * The constructor validates configuration and raises a non-retryable
      ``PaymentProviderError`` when the key id/secret is missing or is a known
      development placeholder. ``build_payment_provider()`` converts that into
      ``None`` so the API layer fails closed with PROVIDER_UNAVAILABLE and never
      claims a payment was taken.
    * ``verify_event`` performs a REAL ``HMAC-SHA256`` over the exact raw body
      and compares with :func:`hmac.compare_digest` (constant time). The webhook
      secret defaults to the API key secret, matching Razorpay's scheme.
    * Network calls use ``httpx`` (already a backend dependency) exactly like
      ``HttpOtpSender``; every transport/HTTP failure is normalised to
      ``PaymentProviderError``, with ``retryable`` set from the status class.
      The secret is never logged and the raw body never leaves this class.
    """

    name = "razorpay"
    api_base = "https://api.razorpay.com/v1"

    def __init__(
        self,
        key_id: str | None,
        key_secret: str | None,
        *,
        webhook_secret: str | None = None,
        timeout_s: float = 10.0,
    ) -> None:
        if not key_id or key_id.strip().lower() in _DEV_DEFAULT_SECRETS:
            raise PaymentProviderError(
                "razorpay key id is not configured", code="PROVIDER_MISCONFIGURED"
            )
        if not key_secret or key_secret.strip().lower() in _DEV_DEFAULT_SECRETS:
            raise PaymentProviderError(
                "razorpay key secret is missing or a development default",
                code="PROVIDER_MISCONFIGURED",
            )
        self._key_id = key_id
        self._key_secret = key_secret
        self._webhook_secret = webhook_secret or key_secret
        self._timeout_s = timeout_s

    # -- Protocol ------------------------------------------------------- #
    def create_order(
        self,
        *,
        amount_paise: int,
        currency: str,
        idempotency_key: str,
        reference: str,
    ) -> PaymentOrderResult:
        _assert_money(amount_paise, currency)
        payload = {
            # Razorpay speaks the smallest currency unit: paise. No conversion.
            "amount": amount_paise,
            "currency": currency,
            "receipt": reference,
            "notes": {"idempotency_key": idempotency_key},
        }
        data = self._post("/orders", payload, idempotency_key)
        return PaymentOrderResult(
            provider=self.name,
            provider_order_ref=str(data.get("id") or ""),
            amount_paise=int(data.get("amount") or amount_paise),
            currency=str(data.get("currency") or currency),
        )

    def verify_event(self, signature: str, raw_body: bytes) -> PaymentEventData:
        if isinstance(raw_body, str):
            raw_body = raw_body.encode("utf-8")
        expected = _hmac_hex(self._webhook_secret.encode("utf-8"), raw_body)
        if not signature or not hmac.compare_digest(expected, str(signature)):
            raise PaymentProviderError(
                "webhook signature verification failed", code="SIGNATURE_INVALID"
            )
        try:
            body = json.loads(raw_body.decode("utf-8"))
        except Exception as exc:
            raise PaymentProviderError(
                f"malformed webhook body: {type(exc).__name__}",
                code="PAYLOAD_MALFORMED",
            ) from exc
        raw_event = str(body.get("event") or "")
        event_type = _RAZORPAY_EVENT_MAP.get(raw_event)
        if event_type is None:
            raise PaymentProviderError(
                "unsupported event type", code="EVENT_TYPE_UNSUPPORTED"
            )
        entity = (
            body.get("payload", {}).get("payment", {}).get("entity")
            or body.get("payload", {}).get("order", {}).get("entity")
            or {}
        )
        card = entity.get("card") or {}
        return PaymentEventData(
            provider=self.name,
            # Razorpay sends x-razorpay-event-id; fall back to the entity id so
            # the UNIQUE replay guard always has a value.
            provider_event_id=str(
                body.get("event_id") or body.get("id") or entity.get("id") or ""
            ),
            event_type=event_type,
            raw_event_type=raw_event,
            provider_order_ref=str(entity.get("order_id") or entity.get("id") or ""),
            amount_paise=int(entity.get("amount") or 0),
            currency=str(entity.get("currency") or "INR"),
            payload_digest=digest_body(raw_body),
            # Display crumbs only: network name and last4. NEVER the PAN, never
            # a CVV, never the payment OTP - Razorpay does not send them and we
            # would refuse to map them if it did.
            brand=(card.get("network") or None),
            masked_last4=(str(card["last4"])[-4:] if card.get("last4") else None),
            expiry_month=card.get("expiry_month"),
            expiry_year=card.get("expiry_year"),
        )

    def refund(
        self,
        *,
        provider_order_ref: str,
        amount_paise: int,
        idempotency_key: str,
        reason: str,
    ) -> PaymentRefundResult:
        _assert_money(amount_paise, "INR")
        data = self._post(
            f"/payments/{provider_order_ref}/refund",
            {"amount": amount_paise, "notes": {"reason": reason}},
            idempotency_key,
        )
        return PaymentRefundResult(
            provider=self.name,
            provider_refund_ref=str(data.get("id") or ""),
            amount_paise=int(data.get("amount") or amount_paise),
            status="succeeded" if data.get("status") == "processed" else "pending",
        )

    # -- transport ------------------------------------------------------ #
    def _post(self, path: str, payload: dict, idempotency_key: str) -> dict:
        import httpx

        try:
            resp = httpx.post(
                f"{self.api_base}{path}",
                json=payload,
                auth=(self._key_id, self._key_secret),
                headers={"X-Idempotency-Key": idempotency_key},
                timeout=self._timeout_s,
            )
        except Exception as exc:  # transport failures are worth retrying
            raise PaymentProviderError(
                f"razorpay transport failure: {type(exc).__name__}",
                code="PROVIDER_UNREACHABLE",
                retryable=True,
            ) from exc
        if resp.status_code >= 500 or resp.status_code == 429:
            raise PaymentProviderError(
                f"razorpay responded {resp.status_code}",
                code="PROVIDER_UNAVAILABLE",
                retryable=True,
            )
        if resp.status_code >= 400:
            raise PaymentProviderError(
                f"razorpay rejected the request ({resp.status_code})",
                code="PROVIDER_REJECTED",
            )
        try:
            return resp.json()
        except Exception as exc:
            raise PaymentProviderError(
                f"razorpay returned an unparsable body: {type(exc).__name__}",
                code="PAYLOAD_MALFORMED",
                retryable=True,
            ) from exc


# --------------------------------------------------------------------------- #
# DI selector (mirrors build_otp_sender)
# --------------------------------------------------------------------------- #


def build_payment_provider() -> PaymentProvider | None:
    """Resolve the configured payment provider, or ``None`` when unusable.

    Contract, identical in shape to ``build_otp_sender``: returns a concrete
    adapter when the deployment is properly configured, and ``None`` when it is
    not ("none"/unknown provider, or a real provider whose secret is missing or
    still a development default). Callers MUST treat ``None`` as
    PROVIDER_UNAVAILABLE and must never fabricate a payment outcome.
    """
    provider = (getattr(settings, "payment_provider", "none") or "none").lower()
    if provider == "deterministic":
        return DeterministicPaymentAdapter()
    if provider == "razorpay":
        if not has_secret(settings.razorpay_key_id) or not has_secret(
            settings.razorpay_key_secret
        ):
            return None  # fail closed rather than pretend
        try:
            return RazorpayAdapter(
                settings.razorpay_key_id.get_secret_value(),
                settings.razorpay_key_secret.get_secret_value(),
            )
        except PaymentProviderError:
            return None  # misconfigured -> fail closed
    return None
