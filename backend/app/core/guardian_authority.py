"""Guardian authorization policy while no proof ceremony is implemented."""
from __future__ import annotations

from typing import Protocol


class GuardianState(Protocol):
    status: str
    verified: bool


def has_authoritative_guardian_proof(_row: GuardianState | None) -> bool:
    """Return false until an approved server-verifiable ceremony exists.

    The legacy ``status='verified', verified=true`` pair is only mutable row
    state. It carries no provider receipt, consumed proof, reviewer authority,
    or other provenance and therefore cannot grant a capability.
    """

    return False
