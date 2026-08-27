from __future__ import annotations

from itertools import count
from typing import Any


_CANONICAL_PROFILE_MUTATIONS = frozenset(
    {
        "/api/v1/auth/student/profile",
        "/api/v1/student/profile/personal",
        "/api/v1/student/profile/academic",
        "/api/v1/student/profile/interests",
    }
)


def install_profile_mutation_idempotency(client: Any, *, prefix: str) -> None:
    """Give inherited happy-path fixtures one fresh, opaque key per mutation.

    The NYAY-9 contract suite deliberately does not install this helper so its
    missing-header and malformed-header fail-closed oracles remain independent.
    """

    original_patch = client.patch
    sequence = count(1)

    def patch(url: str, *args: Any, **kwargs: Any):
        if url in _CANONICAL_PROFILE_MUTATIONS:
            supplied = kwargs.get("headers")
            if supplied is None or hasattr(supplied, "items"):
                headers: Any = dict(supplied or {})
                names = headers
            else:
                # Preserve duplicate Origin/Idempotency-Key probes exactly;
                # converting tuple sequences to a dict would hide the oracle.
                headers = list(supplied)
                names = [name for name, _ in headers]
            if not any(name.casefold() == "idempotency-key" for name in names):
                key = f"{prefix}-{next(sequence):08d}"
                if isinstance(headers, list):
                    headers.append(("Idempotency-Key", key))
                else:
                    headers["Idempotency-Key"] = key
            kwargs["headers"] = headers
        return original_patch(url, *args, **kwargs)

    client.patch = patch
