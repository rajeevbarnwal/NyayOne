"""Event-driven provider readiness: bounded failure, never a sleep-based success."""
from concurrent.futures import ThreadPoolExecutor
import threading

from tests.test_otp_capture_server import _load_capture_server


def test_delivery_observer_waits_for_real_provider_acceptance_without_polling():
    capture = _load_capture_server()
    assert hasattr(capture, "await_delivery"), "NYAY37_CAPTURE_OBSERVER_MISSING"
    armed = threading.Event()
    def observe():
        armed.set()
        return capture.await_delivery(timeout=1)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(observe)
        assert armed.wait(1)
        assert not pending.done()
        token = "a" * 64
        capture.accept_delivery({"to": "9000000000", "message": "Your NyayOne verification code is 123456", "idempotency_key": token}, token)
        assert pending.result(timeout=1) == {"to": "9000000000", "code": "123456"}


def test_absent_delivery_deadline_is_denial_and_late_observer_sees_existing_delivery():
    capture = _load_capture_server()
    assert hasattr(capture, "await_delivery"), "NYAY37_CAPTURE_OBSERVER_MISSING"
    assert capture.await_delivery(timeout=0) is None
    token = "b" * 64
    capture.accept_delivery({"to": "9000000000", "message": "Your NyayOne verification code is 123456", "idempotency_key": token}, token)
    assert capture.await_delivery(timeout=0) == {"to": "9000000000", "code": "123456"}
