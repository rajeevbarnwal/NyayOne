"""External provider seams for Wave 2 (SAATHI-123 / SAATHI-127).

Every outbound integration lives behind a Protocol in this package. Domain
services depend ONLY on the Protocol and on the package's typed error classes,
so no vendor type (razorpay, livekit, httpx, JWT) ever leaks into the service
layer or the API layer. Each seam ships:

* a typed error carrying a ``retryable`` flag (the outbox relay uses it to
  decide retry vs dead-letter),
* a deterministic in-process adapter for dev/test (no network, no card data),
* a real adapter that is CONFIG-DRIVEN and FAILS CLOSED when its secret is
  missing or still a known development default,
* a ``build_*`` resolver mirroring ``app.services.otp_sender.build_otp_sender``:
  it returns ``None`` when the deployment is not properly configured, and
  callers surface PROVIDER_UNAVAILABLE rather than pretending the call worked.
"""
from app.services.providers.payment_provider import (  # noqa: F401
    DeterministicPaymentAdapter,
    PaymentEventData,
    PaymentOrderResult,
    PaymentProvider,
    PaymentProviderError,
    PaymentRefundResult,
    RazorpayAdapter,
    build_payment_provider,
)
from app.services.providers.video_provider import (  # noqa: F401
    DeterministicVideoAdapter,
    LiveKitCommunityAdapter,
    VideoCredential,
    VideoEventData,
    VideoProviderError,
    VideoSessionProvider,
    build_video_provider,
)

__all__ = [
    "PaymentProviderError",
    "PaymentProvider",
    "PaymentEventData",
    "PaymentOrderResult",
    "PaymentRefundResult",
    "DeterministicPaymentAdapter",
    "RazorpayAdapter",
    "build_payment_provider",
    "VideoProviderError",
    "VideoSessionProvider",
    "VideoCredential",
    "VideoEventData",
    "DeterministicVideoAdapter",
    "LiveKitCommunityAdapter",
    "build_video_provider",
]
