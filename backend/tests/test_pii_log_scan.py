"""SAATHI-448 A4 — no raw OTP / mobile in logs, responses, URLs or audit rows."""
from __future__ import annotations

import logging
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.v1 import auth_student as ep
from app.core.config import settings
from app.db.base import Base
from app.db.models.audit import AuditEvent
from app.db.session import get_session
from app.models.registration import OtpChallenge, OtpOutbox

# Schema builder: a create_all-equivalent template copy (see tests/dbtemplate.py).
from tests import dbtemplate


class Capturing:
    def __init__(self):
        self.sent = []
        self._receipts = {}

    def send_idempotent(self, destination, code, *, idempotency_token):
        existing = self._receipts.get(idempotency_token)
        if existing is not None:
            assert existing[:2] == (destination, code)
            return existing[2]
        receipt = f"test-{len(self._receipts) + 1}"
        self._receipts[idempotency_token] = (destination, code, receipt)
        self.sent.append((destination, code))
        return receipt


def _app_ctx():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    dbtemplate.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

    def prod_session():
        s = SessionLocal()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    sender = Capturing()
    app = FastAPI()
    app.include_router(ep.router, prefix="/api/v1")
    app.dependency_overrides[get_session] = prod_session
    app.dependency_overrides[ep.get_otp_sender] = lambda: sender
    app.dependency_overrides[ep.get_outbox_session_factory] = lambda: SessionLocal
    return (
        TestClient(app, headers={"Origin": settings.cors_origins[0]}),
        engine,
        SessionLocal,
        sender,
    )


def test_no_raw_otp_or_mobile_in_logs_responses_or_audit(caplog):
    caplog.set_level(logging.DEBUG)
    client, engine, SessionLocal, sender = _app_ctx()
    mobile = "9812345678"
    r = client.post("/api/v1/auth/student/register", json={
        "first_name": "Aditi", "last_name": "Nair", "mobile": mobile,
        "dob": "2004-03-14", "consent": {"accepted": True}})
    assert r.status_code == 201
    code = sender.sent[-1][1]  # the raw code only ever left via the sender

    # (1) Response bodies never contain the raw code or mobile.
    assert code not in r.text and mobile not in r.text
    resend = client.post("/api/v1/auth/student/otp/resend", json={})
    assert code not in resend.text and mobile not in resend.text

    # (2) Captured logs never contain the raw code or mobile.
    blob = "\n".join(rec.getMessage() for rec in caplog.records)
    assert code not in blob and mobile not in blob

    # (3) Persisted rows: no raw code/mobile in challenge, outbox or audit.
    with SessionLocal() as s:
        for ch in s.scalars(select(OtpChallenge)):
            assert code not in f"{ch.verifier_hash}{ch.metadata_json}"
        for ob in s.scalars(select(OtpOutbox)):
            assert code not in f"{ob.destination_ct}{ob.last_error}" and ob.destination_ct != mobile
        for ev in s.scalars(select(AuditEvent)):
            assert mobile not in str(ev.after_state) and (ev.after_state is None or code not in str(ev.after_state))
    Base.metadata.drop_all(engine)
