"""Native, test-harness-only adaptation of NYAY-26/37 response settlement.

No elapsed time grants authority. Callers bind observations to completed HTTP
responses and fresh committed database reads; no private values are retained.
"""
from itertools import permutations
from urllib.parse import urlsplit


class CanonicalReadinessError(RuntimeError):
    def __init__(self, code, *, stage="settle", kind="unknown", status=None):
        super().__init__(code)
        self.diagnostic = dict(stage=stage, kind=kind, status=status, errorClass=code)


class CookieReadiness:
    @classmethod
    def arm(cls, *, origin, flow_class, client_scope):
        try:
            parsed = urlsplit(origin)
            valid = (parsed.scheme == "https" and parsed.netloc and not parsed.username
                     and not parsed.password and origin == f"https://{parsed.netloc}")
        except (TypeError, ValueError):
            valid = False
        if not valid or flow_class not in {"known", "decoy"} or not client_scope:
            raise CanonicalReadinessError("CANONICAL_ARM_INVALID", stage="arm")
        obj = cls()
        obj.origin, obj.client_scope = origin, client_scope
        obj._events, obj._expired = set(), False
        return obj

    def _live(self):
        if self._expired:
            raise CanonicalReadinessError("CANONICAL_READINESS_EXPIRED")

    def _reject(self, code, kind="unknown"):
        self._expired = True
        raise CanonicalReadinessError(code, kind=kind)

    def observe_response(self, kind, response):
        self._live()
        descriptor = {"start": ("POST", "/api/v1/auth/student/login/otp/start", 202),
                      "state": ("GET", "/api/v1/auth/student/otp/state", 200)}.get(kind)
        if descriptor is None or not isinstance(response, dict):
            self._reject("CANONICAL_RESPONSE_INVALID")
        method, path, status = descriptor
        if (response.get("url") != self.origin + path
                or response.get("method") != method
                or type(response.get("status_code")) is not int
                or response["status_code"] != status
                or response.get("body_settled") is not True
                or response.get("redirected") is not False):
            self._reject("CANONICAL_RESPONSE_INVALID", kind)
        body = response.get("body")
        if (not isinstance(body, dict) or body.get("status") != "pending"
                or body.get("purpose") != "login"
                or type(body.get("expires_in_seconds")) is not int
                or body["expires_in_seconds"] <= 0):
            self._reject("CANONICAL_PENDING_AUTHORITY_INVALID", kind)
        self._events.add(kind)

    def observe_authority(self, kind, *, proven, client_scope):
        self._live()
        if (kind not in {"commit", "delivery", "cookie"} or proven is not True
                or client_scope != self.client_scope):
            self._reject("CANONICAL_AUTHORITY_INVALID")
        self._events.add(kind)

    def require_ready(self):
        self._live()
        if self._events != {"start", "state", "commit", "delivery", "cookie"}:
            raise CanonicalReadinessError("CANONICAL_READINESS_INCOMPLETE")
        return {"ready": True, "attempts": 1}

    def expire(self):
        self._expired = True


def run_seeded_cookie_readiness_variance(*, attempts):
    """Execute all deterministic schedules once; never measure synthetic p95."""
    if type(attempts) is not int or attempts != 1:
        raise CanonicalReadinessError("CANONICAL_ATTEMPTS_INVALID")
    completed = 0
    for order in permutations(("start", "state", "commit", "delivery", "cookie")):
        observer = CookieReadiness.arm(origin="https://testserver", flow_class="known",
                                      client_scope="seeded")
        for index, kind in enumerate(order):
            if kind in {"start", "state"}:
                observer.observe_response(kind, dict(
                    url="https://testserver/api/v1/auth/student/" +
                        ("login/otp/start" if kind == "start" else "otp/state"),
                    method="POST" if kind == "start" else "GET",
                    status_code=202 if kind == "start" else 200,
                    body_settled=True, redirected=False,
                    body=dict(status="pending", purpose="login", expires_in_seconds=120)))
            else:
                observer.observe_authority(kind, proven=True, client_scope="seeded")
            if index < 4:
                try:
                    observer.require_ready()
                except CanonicalReadinessError as error:
                    if str(error) != "CANONICAL_READINESS_INCOMPLETE":
                        raise
                else:
                    raise CanonicalReadinessError("CANONICAL_EARLY_SAMPLE")
        observer.require_ready()
        completed += 1
    return {"schedules": completed, "attempts": 1}
