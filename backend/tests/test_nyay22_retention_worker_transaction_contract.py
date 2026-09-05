"""Transaction-boundary contracts for the scheduled NYAY-22 retention worker."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.workers import retention as retention_worker


_NOW = datetime(2026, 9, 5, 1, 2, 3, tzinfo=timezone.utc)


class _Clock:
    calls = 0

    @classmethod
    def now(cls, zone):
        assert zone is timezone.utc
        cls.calls += 1
        return _NOW


class _TransactionProbe:
    def __init__(self) -> None:
        self.pending: list[str] = []
        self.durable: list[str] = []
        self.commit_batches: list[tuple[str, ...]] = []
        self.rollback_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        return None

    def stage(self, value: str) -> None:
        self.pending.append(value)

    def commit(self) -> None:
        self.commit_batches.append(tuple(self.pending))
        self.durable.extend(self.pending)
        self.pending.clear()

    def rollback(self) -> None:
        self.rollback_calls += 1
        self.pending.clear()


def _install_session(monkeypatch: pytest.MonkeyPatch, session: _TransactionProbe) -> None:
    monkeypatch.setattr(retention_worker, "get_sessionmaker", lambda: lambda: session)
    monkeypatch.setattr(retention_worker, "datetime", _Clock)
    _Clock.calls = 0


def test_worker_samples_one_instant_and_commits_both_phases_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy and mentor retention share one clock value and terminal commit."""

    session = _TransactionProbe()
    observed: list[tuple[str, datetime]] = []
    _install_session(monkeypatch, session)

    def purge(probe: _TransactionProbe, *, now: datetime):
        observed.append(("legacy", now))
        probe.stage("legacy")
        return {"registrations": 1}

    def mentor(probe: _TransactionProbe, *, now: datetime):
        observed.append(("mentor", now))
        probe.stage("mentor")
        # The production mentor-retention boundary owns the terminal commit.
        probe.commit()
        return {"severed_graphs": 1}

    monkeypatch.setattr(retention_worker, "purge_expired", purge)
    monkeypatch.setattr(retention_worker, "run_mentor_retention", mentor)

    assert retention_worker.run_retention_once() == {
        "registrations": 1,
        "mentor_severed_graphs": 1,
    }
    assert _Clock.calls == 1
    assert observed == [("legacy", _NOW), ("mentor", _NOW)]
    assert session.commit_batches == [("legacy", "mentor")]
    assert session.durable == ["legacy", "mentor"]


def test_mentor_phase_failure_rolls_back_staged_legacy_retention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A phase-two failure cannot leave phase-one retention committed."""

    session = _TransactionProbe()
    _install_session(monkeypatch, session)

    def purge(probe: _TransactionProbe, *, now: datetime):
        assert now == _NOW
        probe.stage("legacy")
        return {"registrations": 1}

    def failing_mentor(probe: _TransactionProbe, *, now: datetime):
        assert now == _NOW
        probe.stage("mentor")
        # Mirror run_mentor_retention's fail-closed exception path.
        probe.rollback()
        raise RuntimeError("privacy-safe injected mentor retention failure")

    monkeypatch.setattr(retention_worker, "purge_expired", purge)
    monkeypatch.setattr(retention_worker, "run_mentor_retention", failing_mentor)

    with pytest.raises(RuntimeError, match="privacy-safe injected"):
        retention_worker.run_retention_once()

    assert _Clock.calls == 1
    assert session.commit_batches == []
    assert session.durable == []
    assert session.pending == []
    assert session.rollback_calls == 1
