"""Structured JSON logging with request/correlation ID propagation."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from contextvars import ContextVar

# Correlation ID for the current request; populated by RequestIDMiddleware.
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def _json_handler(handler: logging.Handler) -> logging.Handler:
    handler.setFormatter(JsonLogFormatter())
    handler.addFilter(RequestIdFilter())
    return handler


def configure_logging(level: str = "INFO", log_file_path: str | None = None) -> None:
    """Configure root logging once with JSON stdout and optional JSONL file sink."""
    handlers: list[logging.Handler] = [_json_handler(logging.StreamHandler())]

    if log_file_path:
        path = Path(log_file_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(_json_handler(logging.FileHandler(path, encoding="utf-8")))

    root = logging.getLogger()
    root.handlers.clear()
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(level.upper())


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
