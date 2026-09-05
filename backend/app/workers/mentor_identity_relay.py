"""Non-public mentor identity-provider relay for NYAY-22.

The browser API intentionally contains exactly the nine design-sealed mentor
operations and no provider callback.  This worker is the production caller for
the server-owned pushed-start/backchannel seam: it claims one persisted
transaction, performs one TLS request to an explicitly allowlisted host, and
hands the signed result to the service verifier.  One invocation attempts each
row at most once; it has no recursive retry and prints aggregate counts only.

Run once from a scheduler/worker::

    python -m app.workers.mentor_identity_relay
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
import json
from typing import Callable, Protocol
from urllib.parse import urlsplit
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_sessionmaker
from app.models.mentor_auth import MentorProviderResult
from app.services import mentor_ceremony


_HOST = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_MAX_PROVIDER_RESPONSE_BYTES = 65_536


class MentorIdentityRelayError(RuntimeError):
    """Privacy-safe fail-closed relay error."""


class MentorIdentityAdapter(Protocol):
    def exchange(self, transaction: dict[str, str]) -> tuple[dict[str, object], str]:
        """Return one signed, provider-owned human-approval result.

        The transaction contains only server nonce/correlation and closed
        provider policy—never purpose, invitation, subject, or profile data.
        The provider performs human binding on its own trusted surface and
        signs both ``providerSubject`` and ``userPresenceApproved``.
        """


@dataclass(frozen=True)
class RelayResult:
    examined: int
    settled: int
    failed: int


class HttpMentorIdentityAdapter:
    """Single-attempt HTTPS adapter with redirects and ambient auth disabled."""

    def __init__(self, *, endpoint: str, allowed_hosts: tuple[str, ...], timeout_s: float):
        try:
            parsed = urlsplit(endpoint)
            port = parsed.port
        except (TypeError, ValueError):
            raise MentorIdentityRelayError(
                "mentor provider configuration invalid"
            ) from None
        canonical_hosts = tuple(host.casefold() for host in allowed_hosts)
        host = (parsed.hostname or "").casefold()
        if (
            parsed.scheme != "https"
            or not host
            or _HOST.fullmatch(host) is None
            or host not in canonical_hosts
            or len(set(canonical_hosts)) != len(canonical_hosts)
            or any(_HOST.fullmatch(item) is None for item in canonical_hosts)
            or port not in {None, 443}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not parsed.path.startswith("/")
            or parsed.path in {"", "/"}
            or not isinstance(timeout_s, (int, float))
            or isinstance(timeout_s, bool)
            or timeout_s <= 0
            or timeout_s > 120
        ):
            raise MentorIdentityRelayError("mentor provider configuration invalid")
        self._endpoint = endpoint
        self._timeout_s = float(timeout_s)

    def exchange(self, transaction: dict[str, str]) -> tuple[dict[str, object], str]:
        """Perform exactly one non-redirecting, trust-store-verified request."""

        try:
            with httpx.Client(
                timeout=self._timeout_s,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                with client.stream(
                    "POST", self._endpoint, json=transaction
                ) as response:
                    if response.status_code != 200:
                        raise MentorIdentityRelayError(
                            "mentor provider exchange failed"
                        )
                    media_type = response.headers.get("content-type", "").split(
                        ";", 1
                    )[0].strip().casefold()
                    if media_type != "application/json":
                        raise MentorIdentityRelayError(
                            "mentor provider exchange failed"
                        )
                    raw_length = response.headers.get("content-length")
                    if raw_length is not None:
                        try:
                            declared_length = int(raw_length)
                        except ValueError:
                            raise MentorIdentityRelayError(
                                "mentor provider exchange failed"
                            ) from None
                        if not 0 <= declared_length <= _MAX_PROVIDER_RESPONSE_BYTES:
                            raise MentorIdentityRelayError(
                                "mentor provider exchange failed"
                            )
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > _MAX_PROVIDER_RESPONSE_BYTES:
                            raise MentorIdentityRelayError(
                                "mentor provider exchange failed"
                            )
            document = json.loads(body)
        except MentorIdentityRelayError:
            raise
        except Exception:
            raise MentorIdentityRelayError(
                "mentor provider exchange failed"
            ) from None
        if (
            not isinstance(document, dict)
            or set(document) != {"payload", "signature"}
            or not isinstance(document.get("payload"), dict)
            or not isinstance(document.get("signature"), str)
        ):
            raise MentorIdentityRelayError("mentor provider exchange failed")
        return dict(document["payload"]), document["signature"]


def build_mentor_identity_adapter() -> MentorIdentityAdapter:
    """Build the deployment adapter or fail before a transaction is claimed."""

    endpoint = settings.mentor_identity_provider_start_url
    if not endpoint or not settings.mentor_identity_provider_allowed_hosts:
        raise MentorIdentityRelayError("mentor provider is not configured")
    return HttpMentorIdentityAdapter(
        endpoint=endpoint,
        allowed_hosts=tuple(settings.mentor_identity_provider_allowed_hosts),
        timeout_s=settings.mentor_provider_deadline_seconds,
    )


def dispatch_one(
    ceremony_id: uuid.UUID,
    adapter: MentorIdentityAdapter,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> None:
    """Claim, exchange, and settle once without holding a DB lock over I/O."""

    factory = session_factory or get_sessionmaker()
    with factory() as claim_session:
        transaction = mentor_ceremony.claim_provider_start(
            claim_session,
            ceremony_id=ceremony_id,
        )
    try:
        payload, signature = adapter.exchange(transaction)
    except Exception:
        # Never log or wrap the transaction/provider document.  The persisted
        # provider deadline and circuit state keep all later browser reads
        # non-authorizing.
        raise MentorIdentityRelayError("mentor provider exchange failed") from None
    with factory() as settle_session:
        mentor_ceremony.settle_provider_result(
            settle_session,
            ceremony_id=ceremony_id,
            payload=payload,
            signature_b64=signature,
        )


def relay_pending(
    *,
    session_factory: Callable[[], Session] | None = None,
    adapter: MentorIdentityAdapter | None = None,
    limit: int = 100,
) -> RelayResult:
    """Attempt each eligible provider transaction at most once."""

    if type(limit) is not int or limit < 1 or limit > 100:
        raise MentorIdentityRelayError("mentor provider relay limit invalid")
    provider = adapter or build_mentor_identity_adapter()
    factory = session_factory or get_sessionmaker()
    now = datetime.now(timezone.utc)
    with factory() as discovery_session:
        ids = list(
            discovery_session.scalars(
                select(MentorProviderResult.ceremony_id)
                .where(
                    MentorProviderResult.state == "pending",
                    MentorProviderResult.start_dispatched_at.is_(None),
                    MentorProviderResult.deleted_at.is_(None),
                    MentorProviderResult.expires_at > now,
                )
                .order_by(MentorProviderResult.created_at, MentorProviderResult.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )

    settled = 0
    failed = 0
    for ceremony_id in ids:
        try:
            dispatch_one(ceremony_id, provider, session_factory=factory)
        except (MentorIdentityRelayError, mentor_ceremony.MentorCeremonyError):
            failed += 1
        else:
            settled += 1
    return RelayResult(examined=len(ids), settled=settled, failed=failed)


def main() -> None:
    result = relay_pending()
    print(
        "mentor_identity_relay "
        f"examined={result.examined} settled={result.settled} failed={result.failed}"
    )


if __name__ == "__main__":  # pragma: no cover
    main()
