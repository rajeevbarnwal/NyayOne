"""Target-runtime delivery capture for the Wave 4 browser gate only.

The production API never returns an invitation token.  This isolated-QA
adapter executes the real one-shot worker, captures the intended deterministic
delivery in memory, writes it to an explicit mode-0600 transient file, and
prints counts only.  The browser gate must unlink the file immediately after
reading it and prove that final evidence contains no token or URL fragment.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.risk_notification_relay import (
    DeterministicResponseInvitationProvider,
)
from app.workers.risk_notification_outbox_relay import relay_once
from scripts.seed_wave4_moderation_e2e import assert_isolated_target


def _write_private(path_value: str, payload: dict[str, str]) -> None:
    runner_temp_value = os.getenv("RUNNER_TEMP", "").strip()
    if not runner_temp_value:
        raise RuntimeError("RUNNER_TEMP is required")
    runner_temp = Path(runner_temp_value).expanduser().resolve()
    candidate = Path(path_value).expanduser()
    if candidate.exists() or candidate.is_symlink():
        raise RuntimeError("delivery capture target must not already exist")
    target = candidate.resolve()
    if target == runner_temp or not target.is_relative_to(runner_temp):
        raise RuntimeError("delivery capture target must be inside RUNNER_TEMP")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    os.replace(temporary, target)
    os.chmod(target, 0o600)


def main() -> int:
    database_url = os.getenv("DATABASE_URL", "")
    output = os.getenv("WAVE4_E2E_DELIVERY_OUTPUT", "")
    target_key = os.getenv("WAVE4_E2E_DELIVERY_IDEMPOTENCY_KEY", "")
    try:
        assert_isolated_target(
            database_url,
            opt_in_env="WAVE4_E2E_ALLOW_DELIVERY_CAPTURE",
        )
        if not output or not target_key:
            raise RuntimeError("private output path and target delivery key are required")
        provider = DeterministicResponseInvitationProvider()
        result = relay_once(provider=provider, limit=100)
        delivery = next(
            item for item in provider.deliveries
            if item["idempotency_key"] == target_key
        )
        _write_private(output, {"invitation_url": str(delivery["invitation_url"])})
    except (RuntimeError, StopIteration):
        # Intentionally generic: never print tokens, URLs, delivery references,
        # database credentials or provider exception text.
        print("ERROR: Wave 4 deterministic delivery was unavailable", file=sys.stderr)
        return 2
    print(
        "wave4_response_invitation_e2e "
        f"claimed={result.claimed} sent={result.sent} failed={result.failed} "
        f"dead_lettered={result.dead_lettered} skipped={result.skipped}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
