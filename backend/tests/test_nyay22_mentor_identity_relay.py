"""Production caller contracts for the non-public mentor provider seam."""

from __future__ import annotations

from contextlib import contextmanager
import json
from types import SimpleNamespace
import traceback
import uuid

import pytest

from app.workers import mentor_identity_relay as relay


@pytest.mark.parametrize(
    ("endpoint", "hosts"),
    (
        ("http://idp.example.test/mentor/start", ("idp.example.test",)),
        ("https://idp.example.test:444/mentor/start", ("idp.example.test",)),
        ("https://user@idp.example.test/mentor/start", ("idp.example.test",)),
        ("https://idp.example.test/mentor/start?q=1", ("idp.example.test",)),
        ("https://idp.example.test/mentor/start", ("other.example.test",)),
        ("https://idp.example.test/mentor/start", ("*.example.test",)),
    ),
)
def test_provider_adapter_rejects_noncanonical_or_unallowlisted_endpoint(
    endpoint: str, hosts: tuple[str, ...]
) -> None:
    with pytest.raises(relay.MentorIdentityRelayError) as refused:
        relay.HttpMentorIdentityAdapter(
            endpoint=endpoint,
            allowed_hosts=hosts,
            timeout_s=30,
        )
    assert endpoint not in str(refused.value)


def test_dispatch_one_is_one_claim_one_exchange_one_settlement(monkeypatch) -> None:
    ceremony_id = uuid.uuid4()
    sessions: list[object] = []

    @contextmanager
    def factory():
        session = object()
        sessions.append(session)
        yield session

    calls: list[tuple[str, object]] = []
    transaction = {"nonce": "server-only"}
    payload = {"providerClass": "signed-result"}

    monkeypatch.setattr(
        relay.mentor_ceremony,
        "claim_provider_start",
        lambda session, *, ceremony_id: (
            calls.append(("claim", session)) or transaction
        ),
    )
    monkeypatch.setattr(
        relay.mentor_ceremony,
        "settle_provider_result",
        lambda session, *, ceremony_id, payload, signature_b64: calls.append(
            ("settle", session)
        ),
    )

    class Adapter:
        def exchange(self, candidate):
            assert candidate is transaction
            calls.append(("exchange", candidate))
            return payload, "signature"

    relay.dispatch_one(ceremony_id, Adapter(), session_factory=factory)
    assert [name for name, _ in calls] == ["claim", "exchange", "settle"]
    assert len(sessions) == 2 and sessions[0] is not sessions[1]


def test_dispatch_does_not_retry_or_echo_provider_failure(monkeypatch) -> None:
    ceremony_id = uuid.uuid4()
    attempts = 0

    @contextmanager
    def factory():
        yield object()

    monkeypatch.setattr(
        relay.mentor_ceremony,
        "claim_provider_start",
        lambda _session, *, ceremony_id: {"nonce": "opaque-browser-secret"},
    )

    class FailingAdapter:
        def exchange(self, _transaction):
            nonlocal attempts
            attempts += 1
            raise RuntimeError("opaque-browser-secret")

    with pytest.raises(relay.MentorIdentityRelayError) as refused:
        relay.dispatch_one(ceremony_id, FailingAdapter(), session_factory=factory)
    assert attempts == 1
    assert "opaque-browser-secret" not in str(refused.value)
    rendered = "".join(
        traceback.format_exception(
            type(refused.value), refused.value, refused.value.__traceback__
        )
    )
    assert "opaque-browser-secret" not in rendered


@pytest.mark.parametrize(
    ("headers", "body"),
    (
        ({"content-type": "text/plain"}, b"{}"),
        (
            {
                "content-type": "application/json",
                "content-length": str(relay._MAX_PROVIDER_RESPONSE_BYTES + 1),
            },
            b"{}",
        ),
        (
            {"content-type": "application/json"},
            b"x" * (relay._MAX_PROVIDER_RESPONSE_BYTES + 1),
        ),
    ),
)
def test_http_adapter_rejects_wrong_media_type_and_oversized_results(
    monkeypatch, headers, body
) -> None:
    class Response:
        status_code = 200

        def __init__(self):
            self.headers = headers

        def iter_bytes(self):
            yield body

    @contextmanager
    def stream_fn(*_args, **_kwargs):
        yield Response()

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def stream(self, *_args, **_kwargs):
            return stream_fn()

    monkeypatch.setattr(relay.httpx, "Client", Client)
    adapter = relay.HttpMentorIdentityAdapter(
        endpoint="https://idp.example.test/mentor/start",
        allowed_hosts=("idp.example.test",),
        timeout_s=30,
    )
    with pytest.raises(relay.MentorIdentityRelayError):
        adapter.exchange({"correlation": "server-only"})


def test_http_adapter_accepts_one_bounded_json_document(monkeypatch) -> None:
    document = {"payload": {"providerClass": "verified"}, "signature": "sig"}
    body = json.dumps(document).encode()

    class Response:
        status_code = 200
        headers = {
            "content-type": "application/json; charset=utf-8",
            "content-length": str(len(body)),
        }

        def iter_bytes(self):
            yield body

    @contextmanager
    def stream_fn(*_args, **_kwargs):
        yield Response()

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def stream(self, *_args, **_kwargs):
            return stream_fn()

    monkeypatch.setattr(relay.httpx, "Client", Client)
    adapter = relay.HttpMentorIdentityAdapter(
        endpoint="https://idp.example.test/mentor/start",
        allowed_hosts=("idp.example.test",),
        timeout_s=30,
    )
    assert adapter.exchange({"correlation": "server-only"}) == (
        document["payload"],
        "sig",
    )


def test_builder_fails_before_claim_when_provider_is_unconfigured(monkeypatch) -> None:
    monkeypatch.setattr(
        relay,
        "settings",
        SimpleNamespace(
            mentor_identity_provider_start_url=None,
            mentor_identity_provider_allowed_hosts=[],
            mentor_provider_deadline_seconds=30,
        ),
    )
    with pytest.raises(relay.MentorIdentityRelayError, match="not configured"):
        relay.build_mentor_identity_adapter()
