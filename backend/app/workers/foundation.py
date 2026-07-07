"""Worker foundation (SAATHI-336).

Broker-agnostic job primitives: idempotency-key dedupe, retry classification with
metadata, and a dead-letter (DLQ) handoff abstraction. Designed for a
**Valkey-compatible** broker (Valkey preferred over Redis; no Redis-specific
product assumptions). Unit-testable with in-memory fakes — no live broker needed.

Config-ready placeholders only; no live queue is wired in this foundation ticket.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Protocol


class JobState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    RETRY = "retry"
    DEAD_LETTER = "dead_letter"


class RetryDecision(str, Enum):
    RETRYABLE = "retryable"
    TERMINAL = "terminal"


# Exceptions considered transient/retryable by default (broker-agnostic names).
class TransientError(Exception):
    """Raise for retryable failures (timeouts, temporary broker/network issues)."""


class PermanentError(Exception):
    """Raise for terminal failures that must not be retried (bad input, etc.)."""


def classify_exception(exc: BaseException) -> RetryDecision:
    if isinstance(exc, PermanentError):
        return RetryDecision.TERMINAL
    if isinstance(exc, TransientError):
        return RetryDecision.RETRYABLE
    # Unknown errors: retry a bounded number of times, then DLQ (handled by runner).
    return RetryDecision.RETRYABLE


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    base_delay_s: float = 0.5
    backoff_factor: float = 2.0

    def delay_for(self, attempt: int) -> float:
        return self.base_delay_s * (self.backoff_factor ** max(0, attempt - 1))


@dataclass
class Job:
    name: str
    payload: dict
    idempotency_key: str | None = None
    attempts: int = 0
    state: JobState = JobState.PENDING
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    last_error: str | None = None


class IdempotencyStore(Protocol):
    def seen(self, key: str) -> bool: ...
    def mark(self, key: str) -> None: ...


class InMemoryIdempotencyStore:
    """Default in-memory store; a Valkey-backed store implements the same Protocol."""

    def __init__(self) -> None:
        self._keys: set[str] = set()

    def seen(self, key: str) -> bool:
        return key in self._keys

    def mark(self, key: str) -> None:
        self._keys.add(key)


class DeadLetterQueue(Protocol):
    def put(self, job: Job) -> None: ...


class InMemoryDeadLetterQueue:
    def __init__(self) -> None:
        self.items: list[Job] = []

    def put(self, job: Job) -> None:
        self.items.append(job)


class WorkerRunner:
    """Executes a handler for a job with idempotency, retry classification, and
    DLQ handoff. Broker delivery is out of scope here; a Valkey consumer feeds
    Jobs into `run`."""

    def __init__(
        self,
        *,
        idempotency: IdempotencyStore | None = None,
        dlq: DeadLetterQueue | None = None,
        policy: RetryPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.idempotency = idempotency or InMemoryIdempotencyStore()
        self.dlq = dlq or InMemoryDeadLetterQueue()
        self.policy = policy or RetryPolicy()
        self._sleep = sleep

    def run(self, job: Job, handler: Callable[[Job], None]) -> Job:
        # Idempotency: skip duplicates.
        if job.idempotency_key and self.idempotency.seen(job.idempotency_key):
            job.state = JobState.SUCCEEDED
            return job

        while True:
            job.attempts += 1
            job.state = JobState.RUNNING
            try:
                handler(job)
                job.state = JobState.SUCCEEDED
                if job.idempotency_key:
                    self.idempotency.mark(job.idempotency_key)
                return job
            except BaseException as exc:  # noqa: BLE001 - classify then decide
                job.last_error = f"{type(exc).__name__}: {exc}"[:300]
                decision = classify_exception(exc)
                if decision is RetryDecision.TERMINAL or job.attempts >= self.policy.max_attempts:
                    job.state = JobState.DEAD_LETTER
                    self.dlq.put(job)
                    return job
                job.state = JobState.RETRY
                self._sleep(self.policy.delay_for(job.attempts))
