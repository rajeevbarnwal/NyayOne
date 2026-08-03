"""Config-driven, hash-only rate limiting applied at the HTTP boundary.

This generalises the mechanism already shipped for the public credential
verification endpoint (``app.api.v1.credentials.public_verification``): the
caller identity is NEVER stored, only a keyed hash of it
(:func:`app.core.crypto.keyed_hash`) is used as the bucket key, and the
threshold itself is read from :mod:`app.core.config` at CALL time so an
operator can retune a limit without a redeploy and tests can retune it without
touching this module.

Differences from that prior art, and why:

* the credential endpoint counts rows in ``verification_access_log`` because it
  already had to write an access-log row per request for audit reasons. The
  Wave 2 tutoring surfaces have no such per-request table (and inventing one
  would need a migration), so the counters live in this process instead;
* the window is FIXED (not sliding). A fixed window is the honest thing to
  implement here: it is deterministic, cheap, and its worst case (2x the limit
  across a window boundary) is documented rather than hidden.

Deployment note, stated plainly: these counters are per PROCESS. With N API
workers the effective limit is N x ``limit``. Binding ``settings.valkey_url``
as the shared store is the production upgrade path and needs no change at any
call site — only :func:`_hit` changes.

Privacy: nothing in here holds a user id, an IP, a token or a request body. The
only thing retained per bucket is ``(window_start, count)`` under a keyed hash.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.config import settings
from app.core.crypto import keyed_hash


@dataclass(frozen=True)
class RateLimit:
    """One named limit: which setting carries the threshold, and the window."""

    name: str
    setting: str
    window_seconds: int

    def limit(self) -> int:
        """Read the threshold from settings NOW (never cached at import time)."""
        value = getattr(settings, self.setting)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            # Settings.validate_wave2_configuration already refuses to build a
            # Settings with a non-positive limit; this is defence in depth for a
            # monkeypatched/live-mutated object.
            raise ValueError(f"{self.setting} must be a strictly positive integer")
        return value


#: The three Wave 2 limits, frozen by the SAATHI-123/127 matrix.
TUTOR_SEARCH = RateLimit("tutoring.tutor_search", "rate_limit_tutor_search_per_min", 60)
BOOKING = RateLimit("tutoring.booking", "rate_limit_booking_per_min", 60)
REVIEW = RateLimit("tutoring.review", "rate_limit_review_per_hour", 3600)
WAVE4_RESPONSE_TOKEN = RateLimit(
    "wave4.organisation_response_token",
    "internship_response_token_rate_per_minute",
    60,
)
WAVE4_RESPONSE_IP = RateLimit(
    "wave4.organisation_response_ip",
    "internship_response_ip_rate_per_minute",
    60,
)


class RateLimitExceeded(Exception):
    """Raised by :func:`check`. The HTTP layer maps this to a typed 429."""

    def __init__(self, limit: RateLimit, *, retry_after: int) -> None:
        super().__init__(f"rate limit exceeded for {limit.name}")
        self.limit_name = limit.name
        self.limit = limit.limit()
        self.window_seconds = limit.window_seconds
        self.retry_after = max(1, int(retry_after))


_lock = threading.Lock()
#: bucket_hash -> (window_start_epoch, count). Bounded by pruning on write.
_buckets: dict[str, tuple[int, int]] = {}


def bucket_hash(limit: RateLimit, identity: str) -> str:
    """Keyed hash of ``<limit>:<identity>``. The identity never leaves here."""
    return keyed_hash(f"rate-limit:{limit.name}:{identity}")


def reset() -> None:
    """Drop every counter. For tests and for a process-level kill switch."""
    with _lock:
        _buckets.clear()


def _prune(now_epoch: int) -> None:
    """Forget windows that can no longer deny anything (called under the lock)."""
    stale = [
        key
        for key, (start, _count) in _buckets.items()
        if now_epoch - start > 2 * 3600  # longest configured window is 1h
    ]
    for key in stale:
        del _buckets[key]


def check(limit: RateLimit, identity: str, *, now: datetime | None = None) -> int:
    """Count one request against ``identity``'s bucket for ``limit``.

    Returns the number of requests remaining in the window. Raises
    :class:`RateLimitExceeded` (without consuming further budget) once the
    configured threshold has already been reached, so the Nth request succeeds
    and the (N+1)th is the first to be refused.
    """
    threshold = limit.limit()
    moment = now or datetime.now(timezone.utc)
    epoch = int(moment.timestamp())
    window_start = epoch - (epoch % limit.window_seconds)
    key = bucket_hash(limit, identity)
    with _lock:
        start, count = _buckets.get(key, (window_start, 0))
        if start != window_start:  # a new window: the old count is irrelevant
            start, count = window_start, 0
        if count >= threshold:
            _buckets[key] = (start, count)
            raise RateLimitExceeded(
                limit, retry_after=(start + limit.window_seconds) - epoch
            )
        _buckets[key] = (start, count + 1)
        if len(_buckets) > 4096:
            _prune(epoch)
        return threshold - (count + 1)
