"""Local-only OTP provider double for browser E2E.

Accepts the same HTTP contract as HttpOtpSender and exposes only the latest
delivery to the local QA runner. It binds to loopback and never logs payloads.
Do not deploy this process.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LATEST: dict[str, str] = {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def _write(self, status: int, body: dict) -> None:
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/reset":
            LATEST.clear()
            self._write(200, {"status": "reset"})
            return
        if self.path != "/send":
            self._write(404, {"error": "not_found"})
            return
        size = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(size) or b"{}")
        message = str(payload.get("message", ""))
        code = message.rsplit(" ", 1)[-1]
        if not code.isdigit() or len(code) != 6:
            self._write(422, {"error": "invalid_contract"})
            return
        LATEST.clear()
        LATEST.update({"to": str(payload.get("to", "")), "code": code})
        self._write(202, {"status": "accepted"})

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/latest":
            self._write(200, LATEST)
            return
        if self.path == "/health":
            self._write(200, {"status": "ok"})
            return
        self._write(404, {"error": "not_found"})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 1099), Handler).serve_forever()
