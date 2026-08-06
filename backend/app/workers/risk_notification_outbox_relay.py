"""One-shot relay for governed organisation-response invitations.

Run from a scheduler or the target-runtime gate with::

    python -m app.workers.risk_notification_outbox_relay

The command emits counts only.  Secret invitation tokens, representative
delivery references, URLs and provider exception text are never printed.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

from app.db.session import get_sessionmaker
from app.services.risk_notification_relay import (
    NotificationRelayError,
    RelayResult,
    ResponseInvitationProvider,
    build_response_invitation_provider,
    relay_response_invitations,
)


@dataclass(frozen=True)
class WorkerResult:
    claimed: int
    sent: int
    failed: int
    dead_lettered: int
    skipped: int


def relay_once(
    *,
    session_factory: Callable[[], Session] | None = None,
    provider: ResponseInvitationProvider | None = None,
    limit: int = 50,
) -> WorkerResult:
    """Relay one bounded batch, failing closed when no adapter is configured."""
    resolved = provider if provider is not None else build_response_invitation_provider()
    if resolved is None:
        raise NotificationRelayError(
            "notification_provider_unconfigured", retryable=False
        )
    factory = session_factory or get_sessionmaker()
    with factory() as session:
        result: RelayResult = relay_response_invitations(
            session,
            resolved,
            limit=max(1, min(limit, 1000)),
        )
    return WorkerResult(
        claimed=result.claimed,
        sent=result.sent,
        failed=result.failed,
        dead_lettered=result.dead_lettered,
        skipped=result.skipped,
    )


def main() -> int:
    try:
        result = relay_once()
    except NotificationRelayError:
        # EX_CONFIG: deployment has intentionally not configured a real
        # notification adapter.  No row was claimed or mutated.
        print("risk_notification_relay unavailable=1", file=sys.stderr)
        return 78
    print(
        "risk_notification_relay "
        f"claimed={result.claimed} sent={result.sent} failed={result.failed} "
        f"dead_lettered={result.dead_lettered} skipped={result.skipped}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
