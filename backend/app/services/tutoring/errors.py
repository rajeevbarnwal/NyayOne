"""Typed domain errors for the Wave 2 tutoring services (SAATHI-123 / 127 P2).

Every failure the domain can express is a subclass of :class:`TutoringError`
carrying a STABLE machine code. P3 maps ``code``/``status_code``/``extra`` onto
the HTTP envelope; nothing in the service layer raises bare ``ValueError`` or
``HTTPException``, so the same errors are reusable by workers and CLI tooling.

Codes are contract. Do not rename one without a P3/P4 contract change:

==============================  ======  =======================================
code                            HTTP    meaning
==============================  ======  =======================================
SLOT_UNAVAILABLE                409     slot is not bookable (taken/past/gone)
HOLD_EXPIRED                    409     the 10-minute hold TTL elapsed
HOLD_CONFLICT                   409     another caller won this slot
PAYMENT_UNVERIFIED              400     webhook signature did not verify
AMOUNT_MISMATCH                 422     amount/currency/refund arithmetic wrong
PAYMENT_AMOUNT_MISMATCH         422     the CLIENT proposed an amount/currency
                                        that is not the server-authoritative
                                        price (order creation only)
SESSION_PRICE_INVALID           422     a non-positive / non-integer session
                                        price was offered to a pricing seam
DUPLICATE_EVENT                 409     provider_event_id already applied
REFUND_DUPLICATE                409     a succeeded refund already exists
ATTENDANCE_TOO_EARLY            409     recorded before the scheduled end
ATTENDANCE_STALE_VERSION        409     optimistic version check failed
REVIEW_BLOCKED                  409     attendance absent/disputed, or not owner
REVIEW_DUPLICATE                409     one review per session
REVIEW_EDIT_WINDOW_CLOSED       409     past edit_deadline_at (7 days)
GRANT_EXPIRED                   410     join credential TTL elapsed
GRANT_REVOKED                   410     join credential revoked
PROVIDER_UNAVAILABLE            503     payment/video provider unusable
==============================  ======  =======================================

Supporting codes (same style, needed for a complete surface): NOT_FOUND,
FORBIDDEN, VALIDATION_ERROR, IDEMPOTENCY_KEY_REUSE, SESSION_NOT_ENDED,
SESSION_STATE_INVALID, SESSION_STALE_VERSION, REFUND_NOT_ALLOWED,
RESCHEDULE_WINDOW_CLOSED, ATTENDANCE_STATE_INVALID, REVIEW_NOT_MODERATABLE,
ADMIN_EXCEPTION_UNAUTHORISED, VIDEO_UNVERIFIED.

Privacy: an error message may contain ids, codes and counts ONLY. Never an
email, mobile, name, narrative, token, PAN, CVV or OTP — these messages reach
logs and API bodies.
"""
from __future__ import annotations


class TutoringError(Exception):
    """Base class. ``code`` is the stable contract; ``retryable`` hints retry."""

    code = "TUTORING_ERROR"
    status_code = 422
    retryable = False

    def __init__(self, message: str | None = None, **extra: object) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code
        self.extra = extra

    def to_dict(self) -> dict:
        payload: dict[str, object] = {"code": self.code, "message": self.message}
        payload.update(self.extra)
        return payload

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"{type(self).__name__}(code={self.code!r}, extra={self.extra!r})"


# --------------------------- generic ------------------------------------------
class NotFound(TutoringError):
    code = "NOT_FOUND"
    status_code = 404


class Forbidden(TutoringError):
    code = "FORBIDDEN"
    status_code = 403


class ValidationError(TutoringError):
    code = "VALIDATION_ERROR"
    status_code = 422


# --------------------------- availability / booking ---------------------------
class SlotUnavailable(TutoringError):
    code = "SLOT_UNAVAILABLE"
    status_code = 409


class HoldExpired(TutoringError):
    code = "HOLD_EXPIRED"
    status_code = 409


class HoldConflict(TutoringError):
    """Lost the atomic race for a slot. Exactly one concurrent caller wins."""

    code = "HOLD_CONFLICT"
    status_code = 409


class IdempotencyKeyReuse(TutoringError):
    """The same idempotency key was replayed with DIFFERENT parameters."""

    code = "IDEMPOTENCY_KEY_REUSE"
    status_code = 409


# --------------------------- payments -----------------------------------------
class PaymentUnverified(TutoringError):
    """Signature verification failed — nothing is persisted, nothing applied."""

    code = "PAYMENT_UNVERIFIED"
    status_code = 400


class AmountMismatch(TutoringError):
    code = "AMOUNT_MISMATCH"
    status_code = 422


class PaymentAmountMismatch(TutoringError):
    """The caller's OPTIMISTIC amount/currency disagrees with the server price.

    Deliberately DISTINCT from ``AMOUNT_MISMATCH`` (same 422, different seam):
    ``AMOUNT_MISMATCH`` means "the PROVIDER's event disagrees with the order we
    created", which is a reconciliation problem; this one means "the CLIENT
    proposed a price", which is either a stale checkout screen or an attempt to
    under-pay. An operator reading one log line must be able to tell those apart
    without correlating anything, and a screen must be able to re-read the
    published price and retry rather than treating it as a provider outage.

    Raised with ZERO mutation: the comparison happens before any row is written
    and before the payment provider is called at all.
    """

    code = "PAYMENT_AMOUNT_MISMATCH"
    status_code = 422


class SessionPriceInvalid(TutoringError):
    """A pricing seam was offered a price that is not a positive integer paise.

    Zero is NOT free tutoring. A free offering would need its own explicit
    product flag; inferring it from a 0 is exactly how a tampered order becomes
    indistinguishable from a legitimate one, so every seam that could WRITE a
    price refuses 0 and negatives here, and the ``> 0`` CHECK constraints on
    ``tutor_profiles.session_price_paise`` / ``booking_holds.price_paise``
    refuse them again at the database.
    """

    code = "SESSION_PRICE_INVALID"
    status_code = 422


class DuplicateEvent(TutoringError):
    code = "DUPLICATE_EVENT"
    status_code = 409


class RefundDuplicate(TutoringError):
    code = "REFUND_DUPLICATE"
    status_code = 409


class RefundNotAllowed(TutoringError):
    code = "REFUND_NOT_ALLOWED"
    status_code = 409


class AdminExceptionUnauthorised(TutoringError):
    code = "ADMIN_EXCEPTION_UNAUTHORISED"
    status_code = 403


# --------------------------- sessions -----------------------------------------
class SessionStateInvalid(TutoringError):
    code = "SESSION_STATE_INVALID"
    status_code = 409


class SessionNotEnded(TutoringError):
    code = "SESSION_NOT_ENDED"
    status_code = 409


class RescheduleWindowClosed(TutoringError):
    code = "RESCHEDULE_WINDOW_CLOSED"
    status_code = 409


class SessionStaleVersion(TutoringError):
    """Optimistic concurrency on ``tutoring_sessions.version`` failed.

    Distinct from ``ATTENDANCE_STALE_VERSION`` so P3 can tell the caller WHICH
    aggregate moved under them; the caller re-reads and retries.
    """

    code = "SESSION_STALE_VERSION"
    status_code = 409


# --------------------------- attendance ---------------------------------------
class AttendanceTooEarly(TutoringError):
    code = "ATTENDANCE_TOO_EARLY"
    status_code = 409


class AttendanceStaleVersion(TutoringError):
    code = "ATTENDANCE_STALE_VERSION"
    status_code = 409


class AttendanceStateInvalid(TutoringError):
    code = "ATTENDANCE_STATE_INVALID"
    status_code = 409


# --------------------------- reviews ------------------------------------------
class ReviewBlocked(TutoringError):
    code = "REVIEW_BLOCKED"
    status_code = 409


class ReviewDuplicate(TutoringError):
    code = "REVIEW_DUPLICATE"
    status_code = 409


class ReviewEditWindowClosed(TutoringError):
    code = "REVIEW_EDIT_WINDOW_CLOSED"
    status_code = 409


class ReviewNotModeratable(TutoringError):
    """The review is already decided / soft-deleted, so it cannot be moderated."""

    code = "REVIEW_NOT_MODERATABLE"
    status_code = 409


# --------------------------- video / join credentials -------------------------
class VideoUnverified(TutoringError):
    """A video-provider webhook did not verify. Nothing is read or written.

    Deliberately DISTINCT from ``PAYMENT_UNVERIFIED`` (same 400, different
    surface) so an operator reading a log line or an API body can tell which
    provider seam rejected the delivery without correlating anything else.
    """

    code = "VIDEO_UNVERIFIED"
    status_code = 400


class GrantExpired(TutoringError):
    code = "GRANT_EXPIRED"
    status_code = 410


class GrantRevoked(TutoringError):
    code = "GRANT_REVOKED"
    status_code = 410


class VideoCallsDisabled(TutoringError):
    """Product/operations switch has disabled new video room admission."""

    code = "VIDEO_CALLS_DISABLED"
    status_code = 503
    retryable = False


# --------------------------- providers ----------------------------------------
class ProviderUnavailable(TutoringError):
    code = "PROVIDER_UNAVAILABLE"
    status_code = 503
    retryable = True

    def __init__(self, message: str | None = None, *, retryable: bool = True, **extra):
        super().__init__(message, **extra)
        self.retryable = retryable


ALL_CODES = (
    "SLOT_UNAVAILABLE",
    "HOLD_EXPIRED",
    "HOLD_CONFLICT",
    "PAYMENT_UNVERIFIED",
    "AMOUNT_MISMATCH",
    "PAYMENT_AMOUNT_MISMATCH",
    "SESSION_PRICE_INVALID",
    "DUPLICATE_EVENT",
    "REFUND_DUPLICATE",
    "ATTENDANCE_TOO_EARLY",
    "ATTENDANCE_STALE_VERSION",
    "REVIEW_BLOCKED",
    "REVIEW_DUPLICATE",
    "REVIEW_EDIT_WINDOW_CLOSED",
    "GRANT_EXPIRED",
    "GRANT_REVOKED",
    "VIDEO_CALLS_DISABLED",
    "PROVIDER_UNAVAILABLE",
)
