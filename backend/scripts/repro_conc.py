"""Diagnostic repro of the transient 404/405 on the concurrent follow/saved
HTTP tests. Mirrors tests/test_wave1_law_schools.py::
test_http_concurrent_put_all_200_one_row_one_audit exactly, in a loop.
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401
from app.api.v1.router import api_router
from app.core.crypto import KeyRing, override_keyring
from app.db.base import Base
from app.db.session import get_session
from app.models.registration import User
from app.models.wave1 import LawSchool, LawSchoolFollow, SavedLawSchool
from app.services.law_school_service import seed_law_schools

override_keyring(KeyRing(active_version="v1", secrets={"v1": b"unit-test-registration-key-v1"}))


def _serialized_file_engine(tmp: Path, name: str):
    engine = create_engine(f"sqlite+pysqlite:///{tmp}/{name}.db", poolclass=NullPool,
                           connect_args={"timeout": 15})

    @event.listens_for(engine, "connect")
    def _autocommit(dbapi_conn, _record):
        dbapi_conn.isolation_level = None

    @event.listens_for(engine, "begin")
    def _begin_immediate(conn):
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


def one_round(surface: str, i: int) -> tuple[list[int], str]:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        engine = _serialized_file_engine(tmp, f"conc_{surface}_http")
        Base.metadata.create_all(engine)
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

        app_ = FastAPI()
        app_.include_router(api_router, prefix="/api/v1")
        app_.dependency_overrides[get_session] = prod_session
        client = TestClient(app_)
        with SessionLocal() as s:
            seed_law_schools(s)
            user = User(role="student", status="active")
            s.add(user)
            s.commit()
            uid = user.id
            sid = str(s.scalars(select(LawSchool.id).order_by(LawSchool.name)).first())
        h = {"X-Actor-Claims": json.dumps({"sub": str(uid), "roles": ["student"]})}
        with ThreadPoolExecutor(max_workers=8) as pool:
            rs = list(pool.map(
                lambda _i: client.put(f"/api/v1/student/law-schools/{sid}/{surface}", headers=h),
                range(8)))
        codes = [r.status_code for r in rs]
        bodies = " | ".join(r.text[:180] for r in rs if r.status_code != 200)
        model = LawSchoolFollow if surface == "follow" else SavedLawSchool
        with SessionLocal() as s:
            rows = s.scalar(select(func.count()).select_from(model))
        if rows != 1:
            bodies += f" ROWS={rows}"
        Base.metadata.drop_all(engine)
        return codes, bodies


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    tally: Counter[int] = Counter()
    failures = 0
    for i in range(n):
        for surface in ("follow", "saved"):
            codes, bodies = one_round(surface, i)
            tally.update(codes)
            if codes != [200] * 8:
                failures += 1
                print(f"FAIL iter={i} surface={surface} codes={codes}\n  {bodies}", flush=True)
    print(f"iterations={n} rounds={n*2} failing_rounds={failures} codes={dict(tally)}", flush=True)
    print("threads_alive_at_exit=", threading.active_count(), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
