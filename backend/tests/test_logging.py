import json
import logging

from app.core.logging import configure_logging, request_id_ctx


def test_configure_logging_writes_jsonl_file_with_request_id(tmp_path) -> None:
    log_path = tmp_path / "backend.jsonl"

    configure_logging("INFO", str(log_path))
    token = request_id_ctx.set("req-test-123")
    try:
        logging.getLogger("legalsaathi.test").info("logstash_probe")
    finally:
        request_id_ctx.reset(token)

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1

    event = json.loads(lines[0])
    assert event["level"] == "INFO"
    assert event["logger"] == "legalsaathi.test"
    assert event["message"] == "logstash_probe"
    assert event["request_id"] == "req-test-123"


def test_configure_logging_disables_raw_uvicorn_access_targets(tmp_path) -> None:
    configure_logging("INFO", str(tmp_path / "backend.jsonl"))

    assert logging.getLogger("uvicorn.access").disabled is True
