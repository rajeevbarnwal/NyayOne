"""Local-only OTP provider double for browser E2E.

Accepts the same HTTP contract as HttpOtpSender and exposes only the latest
delivery to the local QA runner. It binds to loopback and never logs payloads.
Do not deploy this process.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LATEST: dict[str, str] = {}
DELIVERIES: dict[str, tuple[str, str, str]] = {}
STATE_LOCK = threading.Lock()
TOKEN = re.compile(r"^[0-9a-f]{64}$")
MESSAGE_PREFIX = "Your NyayOne verification code is "


def _receipt(token: str) -> str:
    return hashlib.sha256(
        f"nyayone:otp-capture-receipt:v1:{token}".encode("ascii")
    ).hexdigest()


def accept_delivery(
    payload: object,
    header_token: str,
) -> tuple[int, dict[str, str], str | None]:
    """Validate and idempotently record one provider request."""

    if not isinstance(payload, dict) or set(payload) != {
        "to",
        "message",
        "idempotency_key",
    }:
        return 422, {"error": "invalid_contract"}, None
    body_token = payload.get("idempotency_key")
    destination = payload.get("to")
    message = payload.get("message")
    if (
        not isinstance(body_token, str)
        or not isinstance(destination, str)
        or not destination
        or len(destination) > 320
        or not isinstance(message, str)
        or not message.startswith(MESSAGE_PREFIX)
        or not TOKEN.fullmatch(header_token)
        or body_token != header_token
    ):
        return 422, {"error": "invalid_contract"}, None
    code = message[len(MESSAGE_PREFIX) :]
    if not code.isascii() or not code.isdigit() or len(code) != 6:
        return 422, {"error": "invalid_contract"}, None
    receipt = _receipt(header_token)
    with STATE_LOCK:
        existing = DELIVERIES.get(header_token)
        if existing is not None and existing[:2] != (destination, code):
            return 409, {"error": "idempotency_conflict"}, None
        if existing is None:
            DELIVERIES[header_token] = (destination, code, receipt)
        LATEST.clear()
        LATEST.update({"to": destination, "code": code})
    return 202, {"status": "accepted"}, receipt


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def _write(
        self,
        status: int,
        body: dict,
        *,
        receipt: str | None = None,
    ) -> None:
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if receipt is not None:
            self.send_header("X-Provider-Receipt", receipt)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/reset":
            with STATE_LOCK:
                LATEST.clear()
                DELIVERIES.clear()
            self._write(200, {"status": "reset"})
            return
        if self.path != "/send":
            self._write(404, {"error": "not_found"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            size = -1
        if size <= 0 or size > 16_384:
            self._write(422, {"error": "invalid_contract"})
            return
        try:
            payload = json.loads(self.rfile.read(size))
        except (json.JSONDecodeError, UnicodeError):
            self._write(422, {"error": "invalid_contract"})
            return
        header_token = self.headers.get("Idempotency-Key", "")
        status, body, receipt = accept_delivery(payload, header_token)
        self._write(status, body, receipt=receipt)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/latest":
            with STATE_LOCK:
                snapshot = dict(LATEST)
            self._write(200, snapshot)
            return
        if self.path == "/health":
            self._write(200, {"status": "ok"})
            return
        self._write(404, {"error": "not_found"})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 1099), Handler).serve_forever()
