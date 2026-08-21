from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_capture_server():
    path = Path(__file__).parents[1] / "scripts" / "otp_capture_server.py"
    spec = importlib.util.spec_from_file_location("otp_capture_server_tested", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_capture_provider_deduplicates_the_exact_token_and_payload() -> None:
    token = "a" * 64
    payload = {
        "to": "9000000000",
        "message": "Your NyayOne verification code is 123456",
        "idempotency_key": token,
    }
    module = _load_capture_server()
    first = module.accept_delivery(payload, token)
    replay = module.accept_delivery(payload, token)

    assert first[0] == replay[0] == 202
    assert first[1] == replay[1] == {"status": "accepted"}
    assert first[2] == replay[2]
    assert len(module.DELIVERIES) == 1
    assert module.LATEST == {"to": "9000000000", "code": "123456"}


def test_capture_provider_rejects_token_payload_conflicts_without_mutation() -> None:
    token = "b" * 64
    first = {
        "to": "9000000000",
        "message": "Your NyayOne verification code is 123456",
        "idempotency_key": token,
    }
    conflict = {**first, "message": "Your NyayOne verification code is 654321"}
    module = _load_capture_server()
    assert module.accept_delivery(first, token)[0] == 202
    status, body, receipt = module.accept_delivery(conflict, token)

    assert status == 409
    assert body == {"error": "idempotency_conflict"}
    assert receipt is None
    assert len(module.DELIVERIES) == 1
    assert module.LATEST == {"to": "9000000000", "code": "123456"}


def test_capture_provider_rejects_missing_mismatched_or_malformed_tokens() -> None:
    token = "c" * 64
    payload = {
        "to": "9000000000",
        "message": "Your NyayOne verification code is 123456",
        "idempotency_key": token,
    }
    module = _load_capture_server()
    cases = (
        (payload, ""),
        (payload, "d" * 64),
        ({**payload, "idempotency_key": "short"}, "short"),
        ({**payload, "extra": True}, token),
    )
    for candidate, header in cases:
        status, body, receipt = module.accept_delivery(candidate, header)
        assert status == 422
        assert body == {"error": "invalid_contract"}
        assert receipt is None
    assert module.DELIVERIES == {}
    assert module.LATEST == {}
