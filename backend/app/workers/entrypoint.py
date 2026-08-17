"""Local/dev worker entrypoint (SAATHI-336).

Builds a WorkerRunner from settings. In dev it does NOT connect to a live broker
(none is provisioned in the foundation stage); it validates config and exposes a
runner that a Valkey consumer will feed once the broker is wired. Run:

    python -m app.workers.entrypoint
"""
from __future__ import annotations

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.workers.foundation import RetryPolicy, WorkerRunner


def build_runner() -> WorkerRunner:
    return WorkerRunner(
        policy=RetryPolicy(
            max_attempts=settings.worker_max_attempts,
            base_delay_s=settings.worker_base_delay_s,
            backoff_factor=settings.worker_backoff_factor,
        )
    )


def main() -> None:
    configure_logging(settings.log_level)
    log = get_logger("nyayone.worker")
    build_runner()
    scheme = settings.worker_broker_url.split("://", 1)[0]
    log.info(
        "worker_boot",
        extra={
            "broker_scheme": scheme,  # 'valkey' by default
            "max_attempts": settings.worker_max_attempts,
            "note": "dev entrypoint — no live broker connection in the foundation stage",
        },
    )


if __name__ == "__main__":  # pragma: no cover
    main()
