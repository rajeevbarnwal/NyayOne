"""Scheduled aggregate-only retention entrypoint."""
from __future__ import annotations

from datetime import datetime, timezone

from app.core.retention import purge_expired
from app.db.session import get_sessionmaker


def run_retention_once() -> dict[str, int]:
    """Apply configured retention in one transaction and return only counts."""

    with get_sessionmaker()() as session:
        counts = purge_expired(session, now=datetime.now(timezone.utc))
        session.commit()
        return counts


def main() -> None:
    counts = run_retention_once()
    # Stable aggregate inventory only; never print keys, subjects or ciphertext.
    print(
        "retention "
        + " ".join(f"{name}={counts[name]}" for name in sorted(counts))
    )


if __name__ == "__main__":  # pragma: no cover
    main()
