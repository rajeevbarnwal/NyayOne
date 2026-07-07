"""Worker foundation tests (SAATHI-336/378) — no live broker; fakes only."""
from __future__ import annotations

from app.workers.foundation import (
    InMemoryDeadLetterQueue,
    InMemoryIdempotencyStore,
    Job,
    JobState,
    PermanentError,
    RetryDecision,
    RetryPolicy,
    TransientError,
    WorkerRunner,
    classify_exception,
)


def _runner(**kw) -> WorkerRunner:
    # no real sleeping in tests
    return WorkerRunner(sleep=lambda _s: None, **kw)


def test_retry_classification() -> None:
    assert classify_exception(PermanentError("bad")) is RetryDecision.TERMINAL
    assert classify_exception(TransientError("timeout")) is RetryDecision.RETRYABLE
    assert classify_exception(RuntimeError("unknown")) is RetryDecision.RETRYABLE


def test_idempotency_skips_duplicate() -> None:
    store = InMemoryIdempotencyStore()
    runner = _runner(idempotency=store)
    calls = []
    handler = lambda job: calls.append(job.id)  # noqa: E731
    j1 = runner.run(Job(name="n", payload={}, idempotency_key="k1"), handler)
    j2 = runner.run(Job(name="n", payload={}, idempotency_key="k1"), handler)
    assert j1.state is JobState.SUCCEEDED and j2.state is JobState.SUCCEEDED
    assert len(calls) == 1  # second was deduped


def test_transient_retries_then_succeeds() -> None:
    runner = _runner(policy=RetryPolicy(max_attempts=3, base_delay_s=0))
    attempts = {"n": 0}

    def handler(job: Job) -> None:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise TransientError("temporary")

    job = runner.run(Job(name="n", payload={}), handler)
    assert job.state is JobState.SUCCEEDED
    assert job.attempts == 3


def test_permanent_error_goes_to_dlq_immediately() -> None:
    dlq = InMemoryDeadLetterQueue()
    runner = _runner(dlq=dlq)

    def handler(job: Job) -> None:
        raise PermanentError("bad input")

    job = runner.run(Job(name="n", payload={}), handler)
    assert job.state is JobState.DEAD_LETTER
    assert job.attempts == 1
    assert dlq.items and dlq.items[0].id == job.id


def test_transient_exhausts_attempts_to_dlq() -> None:
    dlq = InMemoryDeadLetterQueue()
    runner = _runner(dlq=dlq, policy=RetryPolicy(max_attempts=2, base_delay_s=0))

    def handler(job: Job) -> None:
        raise TransientError("always failing")

    job = runner.run(Job(name="n", payload={}), handler)
    assert job.state is JobState.DEAD_LETTER
    assert job.attempts == 2
    assert len(dlq.items) == 1
