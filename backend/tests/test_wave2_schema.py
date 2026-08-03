"""Wave 2 tutoring schema/migration proofs (SAATHI-123 / SAATHI-127, P1).

Everything here runs against a REAL migrated database (``alembic upgrade head``
through a subprocess, exactly like ``scripts/db_gate.sh`` does), never against
``metadata.create_all``. Expected values are derived from the ORM
(``app/models/wave2.py``) and from migration 0008, then cross-checked against
the introspected database so a rename, a dropped index or a privacy regression
fails loudly.

Covered:
  1. exactly 17 Wave 2 tables, names pinned explicitly;
  2. every FK column is index-supported;
  3. every named CHECK / UNIQUE declared in the models exists in the DB;
  4. one active hold per slot, one succeeded refund per order;
  5. the marker columns cannot be falsified against the row status — including
     the three-valued-logic case (guarded status + NULL marker), which the
     CHECKs now reject outright
     (``test_guarded_status_with_null_marker_is_rejected``), with the native
     partial unique indexes proven to still work as the second line of defence
     (``test_partial_unique_indexes_are_the_second_line_of_defence``);
  6. no pan / cvv / otp / raw-token column anywhere in Wave 2;
  7. alembic upgrade -> check (no drift) -> downgrade 0007 -> re-upgrade;
  8. ORM vs migrated-DB column/nullability parity.

One migrated SQLite database is built per module; write tests and the
destructive lifecycle test work on cheap file copies of it so alembic is only
invoked a handful of times.
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple

import pytest
from sqlalchemy import Index, Table, create_engine, inspect
from sqlalchemy.exc import IntegrityError

import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.models import wave2
from app.models.registration import User
from app.models.wave2 import (
    BookingHold,
    PaymentOrder,
    PaymentRefund,
    TutorAvailabilitySlot,
    TutorProfile,
)

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION_0008 = (
    BACKEND / "app" / "db" / "migrations" / "versions" / "0008_wave2_tutoring.py"
)

WAVE2_REVISION = "0008_wave2_tutoring"
PARENT_REVISION = "0007_wave3_credentials"
def _expected_alembic_head() -> str:
    versions_dir = BACKEND / "app" / "db" / "migrations" / "versions"
    numbered = [
        p.stem
        for p in versions_dir.glob("*.py")
        if p.name[0].isdigit() and not p.name.startswith("__")
    ]
    assert numbered, f"No alembic version files found in {versions_dir}"
    return max(numbered, key=lambda s: int(s.split("_", 1)[0]))


HEAD_REVISION = _expected_alembic_head()
POST_WAVE2_TABLES = {
    "login_attempts",
    "auth_sessions",
    "internship_reports",
    "internship_report_categories",
    "internship_report_consents",
    "internship_report_evidence",
    "reporter_identity_vault",
    "reporter_identity_access_requests",
    "reporter_identity_access_approvals",
    "moderation_handoffs",
    "internship_reporting_outbox",
    "moderation_cases",
    "moderation_assignments",
    "moderation_actions",
    "duplicate_clusters",
    "duplicate_cluster_members",
    "risk_signals",
    "risk_signal_approvals",
    "moderation_notification_outbox",
    "calendar_event_sources",
    "calendar_events",
    "calendar_view_preferences",
    "calendar_reminder_preferences",
    "calendar_conflicts",
    "calendar_export_subscriptions",
    "calendar_export_tokens",
    "calendar_export_revocations",
}

# Pinned on purpose: renaming a Wave 2 table must break this list, not silently
# pass because the assertion was derived from the same source as the code.
EXPECTED_WAVE2_TABLES = (
    "booking_events",
    "booking_holds",
    "payment_events",
    "payment_orders",
    "payment_refunds",
    "review_moderation",
    "session_attendance",
    "session_cancellations",
    "session_reminder_jobs",
    "session_status_history",
    "tutor_availability_slots",
    "tutor_profiles",
    "tutor_reviews",
    "tutor_subjects",
    "tutoring_outbox",
    "tutoring_sessions",
    "video_session_grants",
)

# Partial unique indexes declared in the models and created by 0008 behind a
# dialect guard (PostgreSQL + SQLite only).
PARTIAL_UNIQUE_INDEXES = {
    "uq_booking_holds_one_active_per_slot": ("booking_holds", ["slot_id"]),
    "uq_payment_refunds_one_succeeded_per_order": ("payment_refunds", ["order_id"]),
}
PARTIAL_INDEX_DIALECTS = ("postgresql", "sqlite")

T0 = datetime(2026, 1, 12, 9, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def alembic(db: str, *args: str) -> subprocess.CompletedProcess:
    """Invoke alembic exactly the way the repo does: subprocess, cwd = backend."""
    env = {**os.environ, "DATABASE_URL": f"sqlite+pysqlite:///{db}"}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(BACKEND),
    )


def wave2_models() -> dict[str, type]:
    """Every mapped class declared in app.models.wave2, keyed by table name."""
    found: dict[str, type] = {}
    for name in dir(wave2):
        obj = getattr(wave2, name)
        table = getattr(obj, "__table__", None)
        if isinstance(table, Table) and getattr(obj, "__module__", "") == wave2.__name__:
            found[table.name] = obj
    return found


def wave2_tables() -> dict[str, Table]:
    return {name: model.__table__ for name, model in wave2_models().items()}


def scalar(db: str, sql: str):
    connection = sqlite3.connect(db)
    try:
        row = connection.execute(sql).fetchone()
    finally:
        connection.close()
    return None if row is None else row[0]


class MigratedDb(NamedTuple):
    path: str
    upgrade: subprocess.CompletedProcess


@pytest.fixture(scope="module")
def migrated_db(alembic_snapshots, alembic_snapshot_run, tmp_path_factory) -> MigratedDb:
    """One real ``alembic upgrade head`` SQLite database for the whole module.

    Served from the session-scoped snapshot (``tests/conftest.py``) that a real
    alembic ``upgrade head`` produced, rather than repeating that same upgrade in
    a second subprocess. ``.upgrade`` is the genuine ``CompletedProcess`` of that
    run, so ``test_alembic_lifecycle_upgrade_check_downgrade_reupgrade`` still
    asserts ``returncode == 0`` against a real invocation, and every other CLI
    step it makes (``check``, ``downgrade``, re-``upgrade``, re-``check``) is
    still executed here by ``python -m alembic``.
    """
    db = str(tmp_path_factory.mktemp("wave2_schema") / "wave2.db")
    shutil.copyfile(alembic_snapshots["head"], db)
    result = alembic_snapshot_run
    assert result.returncode == 0, result.stderr[-2000:]
    assert scalar(db, "SELECT version_num FROM alembic_version") is not None
    return MigratedDb(path=db, upgrade=result)


@pytest.fixture(scope="module")
def inspector(migrated_db: MigratedDb):
    engine = create_engine(f"sqlite+pysqlite:///{migrated_db.path}")
    try:
        yield inspect(engine)
    finally:
        engine.dispose()


@pytest.fixture()
def write_engine(migrated_db: MigratedDb, tmp_path):
    """A throwaway copy of the migrated DB (no extra alembic run)."""
    target = tmp_path / "wave2_write.db"
    shutil.copyfile(migrated_db.path, target)
    engine = create_engine(f"sqlite+pysqlite:///{target}")
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def seeded(write_engine):
    """Real parent rows: user -> tutor profile -> two slots -> hold -> order."""
    ids = {
        "user": uuid.uuid4(),
        "tutor": uuid.uuid4(),
        "slot": uuid.uuid4(),
        "other_slot": uuid.uuid4(),
        "hold": uuid.uuid4(),
        "order": uuid.uuid4(),
        "other_order": uuid.uuid4(),
    }
    stamps = {"created_at": T0, "updated_at": T0}
    with write_engine.begin() as conn:
        conn.execute(
            User.__table__.insert().values(
                id=ids["user"], role="student", status="active", **stamps
            )
        )
        conn.execute(
            TutorProfile.__table__.insert().values(
                id=ids["tutor"],
                user_id=ids["user"],
                display_name="Adv. Meera Iyer",
                status="active",
                **stamps,
            )
        )
        for key, offset in (("slot", 0), ("other_slot", 24)):
            conn.execute(
                TutorAvailabilitySlot.__table__.insert().values(
                    id=ids[key],
                    tutor_id=ids["tutor"],
                    start_utc=T0 + timedelta(hours=offset + 48),
                    end_utc=T0 + timedelta(hours=offset + 49),
                    status="available",
                    **stamps,
                )
            )
        conn.execute(
            BookingHold.__table__.insert().values(
                id=ids["hold"],
                slot_id=ids["other_slot"],
                student_user_id=ids["user"],
                status="consumed",
                expires_at=T0 + timedelta(minutes=15),
                idempotency_key="seed-hold",
                active_slot_id=None,
                **stamps,
            )
        )
        for key, suffix in (("order", "a"), ("other_order", "b")):
            conn.execute(
                PaymentOrder.__table__.insert().values(
                    id=ids[key],
                    hold_id=ids["hold"],
                    student_user_id=ids["user"],
                    provider="deterministic",
                    amount_paise=150000,
                    currency="INR",
                    status="paid",
                    idempotency_key=f"seed-order-{suffix}",
                    **stamps,
                )
            )
    return write_engine, ids


def insert_hold(engine, *, slot_id, student_user_id, status, active_slot_id, key):
    with engine.begin() as conn:
        conn.execute(
            BookingHold.__table__.insert().values(
                id=uuid.uuid4(),
                slot_id=slot_id,
                student_user_id=student_user_id,
                status=status,
                expires_at=T0 + timedelta(minutes=15),
                idempotency_key=key,
                active_slot_id=active_slot_id,
                created_at=T0,
                updated_at=T0,
            )
        )


def insert_refund(engine, *, order_id, status, succeeded_order_id, ref):
    with engine.begin() as conn:
        conn.execute(
            PaymentRefund.__table__.insert().values(
                id=uuid.uuid4(),
                order_id=order_id,
                amount_paise=150000,
                reason="cancel_ge_24h",
                status=status,
                provider_refund_ref=ref,
                succeeded_order_id=succeeded_order_id,
                created_at=T0,
                updated_at=T0,
            )
        )


# --------------------------------------------------------------------------- #
# 1. table inventory
# --------------------------------------------------------------------------- #
def test_exactly_seventeen_wave2_tables_match_the_models(inspector):
    models = wave2_models()
    assert len(EXPECTED_WAVE2_TABLES) == 17
    assert sorted(models) == list(EXPECTED_WAVE2_TABLES), (
        "app/models/wave2.py table set drifted from the pinned Wave 2 inventory"
    )

    live = set(inspector.get_table_names())
    missing = sorted(set(EXPECTED_WAVE2_TABLES) - live)
    assert missing == [], f"migration 0008 did not create: {missing}"
    assert len(live & set(EXPECTED_WAVE2_TABLES)) == 17

    # 0008 must create exactly these 17 tables — no extras smuggled in.
    # (That the downgrade drops all 17 is proven by the lifecycle test.)
    source = MIGRATION_0008.read_text(encoding="utf-8")
    created = re.findall(r'op\.create_table\(\s*\n?\s*"([a-z_]+)"', source)
    assert sorted(created) == list(EXPECTED_WAVE2_TABLES), sorted(created)


# --------------------------------------------------------------------------- #
# 2. every FK column is index-supported
# --------------------------------------------------------------------------- #
def test_every_foreign_key_column_has_a_supporting_index(inspector):
    unsupported: list[str] = []
    checked = 0
    for table in EXPECTED_WAVE2_TABLES:
        leading_sets = []
        for index in inspector.get_indexes(table):
            columns = [c for c in index["column_names"] if c is not None]
            if columns:
                leading_sets.append(columns)
        for unique in inspector.get_unique_constraints(table):
            if unique["column_names"]:
                leading_sets.append(list(unique["column_names"]))
        pk = inspector.get_pk_constraint(table).get("constrained_columns") or []
        if pk:
            leading_sets.append(list(pk))

        for fk in inspector.get_foreign_keys(table):
            fk_columns = list(fk["constrained_columns"])
            checked += 1
            covered = any(
                columns[: len(fk_columns)] == fk_columns for columns in leading_sets
            )
            if not covered:
                unsupported.append(f"{table}.{','.join(fk_columns)}")

    assert checked >= 20, f"expected the Wave 2 FK fan-out, introspected only {checked}"
    assert unsupported == [], (
        "foreign key columns without a supporting (leading-column) index: "
        + ", ".join(unsupported)
    )


# --------------------------------------------------------------------------- #
# 3. named CHECK / UNIQUE constraints survive the migration
# --------------------------------------------------------------------------- #
def test_named_check_and_unique_constraints_are_all_migrated(inspector):
    from sqlalchemy import CheckConstraint, UniqueConstraint

    missing_checks: list[str] = []
    missing_uniques: list[str] = []
    total_checks = 0
    total_uniques = 0

    for name, table in sorted(wave2_tables().items()):
        live_checks = {c["name"] for c in inspector.get_check_constraints(name)}
        live_uniques = {u["name"] for u in inspector.get_unique_constraints(name)}
        # A unique INDEX satisfies a declared UNIQUE just as well.
        live_uniques |= {
            i["name"] for i in inspector.get_indexes(name) if i.get("unique")
        }

        for constraint in table.constraints:
            if isinstance(constraint, CheckConstraint) and constraint.name:
                total_checks += 1
                if str(constraint.name) not in live_checks:
                    missing_checks.append(f"{name}:{constraint.name}")
            elif isinstance(constraint, UniqueConstraint) and constraint.name:
                total_uniques += 1
                if str(constraint.name) not in live_uniques:
                    missing_uniques.append(f"{name}:{constraint.name}")

    assert missing_checks == [], f"CHECK constraints lost in 0008: {missing_checks}"
    assert missing_uniques == [], f"UNIQUE constraints lost in 0008: {missing_uniques}"
    # Sanity floor so an empty introspection cannot make this vacuously green.
    assert total_checks >= 40, total_checks
    assert total_uniques >= 13, total_uniques


def test_declared_partial_unique_indexes_exist_on_this_dialect(inspector):
    dialect = inspector.engine.dialect.name
    if dialect not in PARTIAL_INDEX_DIALECTS:
        pytest.skip(f"{dialect} falls back to the portable marker-column UNIQUEs")

    for index_name, (table, columns) in PARTIAL_UNIQUE_INDEXES.items():
        live = {i["name"]: i for i in inspector.get_indexes(table)}
        assert index_name in live, f"{table}: partial unique {index_name} missing"
        assert live[index_name]["unique"], f"{index_name} is not UNIQUE"
        assert list(live[index_name]["column_names"]) == columns

    # ...and the ORM declares them too, so `alembic check` stays quiet.
    tables = wave2_tables()
    for index_name, (table, columns) in PARTIAL_UNIQUE_INDEXES.items():
        declared = {
            i.name: i for i in tables[table].indexes if isinstance(i, Index)
        }
        assert index_name in declared, f"ORM lost {index_name}"
        assert declared[index_name].unique
        assert [c.name for c in declared[index_name].columns] == columns


# --------------------------------------------------------------------------- #
# 4. one-per-aggregate uniqueness
# --------------------------------------------------------------------------- #
def test_only_one_active_hold_can_exist_per_slot(seeded):
    engine, ids = seeded
    insert_hold(
        engine,
        slot_id=ids["slot"],
        student_user_id=ids["user"],
        status="active",
        active_slot_id=ids["slot"],
        key="hold-active-1",
    )

    with pytest.raises(IntegrityError) as excinfo:
        insert_hold(
            engine,
            slot_id=ids["slot"],
            student_user_id=ids["user"],
            status="active",
            active_slot_id=ids["slot"],
            key="hold-active-2",
        )
    assert "unique" in str(excinfo.value).lower()

    # Non-active holds on the same slot stay legal (markers are NULL).
    for index, status in enumerate(("consumed", "expired", "released")):
        insert_hold(
            engine,
            slot_id=ids["slot"],
            student_user_id=ids["user"],
            status=status,
            active_slot_id=None,
            key=f"hold-inactive-{index}",
        )
    with engine.connect() as conn:
        rows = conn.exec_driver_sql(
            "SELECT status, COUNT(*) FROM booking_holds GROUP BY status ORDER BY status"
        ).fetchall()
    assert dict(rows)["active"] == 1
    assert sum(count for _status, count in rows) == 5  # 1 active + 3 + seed hold


def test_only_one_succeeded_refund_can_exist_per_payment_order(seeded):
    engine, ids = seeded
    insert_refund(
        engine,
        order_id=ids["order"],
        status="succeeded",
        succeeded_order_id=ids["order"],
        ref="rfnd-1",
    )

    with pytest.raises(IntegrityError) as excinfo:
        insert_refund(
            engine,
            order_id=ids["order"],
            status="succeeded",
            succeeded_order_id=ids["order"],
            ref="rfnd-2",
        )
    assert "unique" in str(excinfo.value).lower()

    # Non-succeeded refunds on the same order, and a succeeded refund on a
    # DIFFERENT order, are both still allowed.
    for index, status in enumerate(("pending", "processing", "failed")):
        insert_refund(
            engine,
            order_id=ids["order"],
            status=status,
            succeeded_order_id=None,
            ref=f"rfnd-other-{index}",
        )
    insert_refund(
        engine,
        order_id=ids["other_order"],
        status="succeeded",
        succeeded_order_id=ids["other_order"],
        ref="rfnd-3",
    )
    with engine.connect() as conn:
        succeeded = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM payment_refunds WHERE status = 'succeeded'"
        ).scalar()
        per_order = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM payment_refunds"
            " WHERE status = 'succeeded' GROUP BY order_id"
        ).fetchall()
    assert succeeded == 2
    assert [row[0] for row in per_order] == [1, 1]


# --------------------------------------------------------------------------- #
# 5. marker columns cannot be falsified
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("status", "marker"),
    [
        ("active", "other_slot"),  # active pointing at a different slot
        ("active", None),          # active with NO marker (three-valued logic)
        ("expired", "slot"),       # stale marker on a dead hold
        ("consumed", "other_slot"),
        ("released", "slot"),
    ],
)
def test_booking_hold_active_marker_cannot_be_falsified(seeded, status, marker):
    engine, ids = seeded
    with pytest.raises(IntegrityError) as excinfo:
        insert_hold(
            engine,
            slot_id=ids["slot"],
            student_user_id=ids["user"],
            status=status,
            active_slot_id=None if marker is None else ids[marker],
            key=f"falsified-{status}-{marker}",
        )
    assert "ck_booking_holds_active_marker" in str(excinfo.value)


@pytest.mark.parametrize(
    ("status", "marker"),
    [
        ("active", "slot"),
        ("consumed", None),
        ("expired", None),
        ("released", None),
    ],
)
def test_booking_hold_honest_marker_combinations_are_accepted(seeded, status, marker):
    engine, ids = seeded
    insert_hold(
        engine,
        slot_id=ids["slot"],
        student_user_id=ids["user"],
        status=status,
        active_slot_id=None if marker is None else ids[marker],
        key=f"honest-{status}",
    )
    with engine.connect() as conn:
        assert conn.exec_driver_sql(
            "SELECT COUNT(*) FROM booking_holds WHERE idempotency_key ="
            f" 'honest-{status}'"
        ).scalar() == 1


@pytest.mark.parametrize(
    ("status", "marker"),
    [
        ("succeeded", "other_order"),
        ("succeeded", None),  # succeeded with NO marker (three-valued logic)
        ("pending", "order"),
        ("processing", "order"),
        ("failed", "order"),
    ],
)
def test_payment_refund_succeeded_marker_cannot_be_falsified(seeded, status, marker):
    engine, ids = seeded
    with pytest.raises(IntegrityError) as excinfo:
        insert_refund(
            engine,
            order_id=ids["order"],
            status=status,
            succeeded_order_id=None if marker is None else ids[marker],
            ref=f"falsified-{status}-{marker}",
        )
    assert "ck_payment_refunds_succeeded_marker" in str(excinfo.value)


@pytest.mark.parametrize(
    ("status", "marker"),
    [
        ("succeeded", "order"),
        ("pending", None),
        ("processing", None),
        ("failed", None),
    ],
)
def test_payment_refund_honest_marker_combinations_are_accepted(
    seeded, status, marker
):
    engine, ids = seeded
    insert_refund(
        engine,
        order_id=ids["order"],
        status=status,
        succeeded_order_id=None if marker is None else ids[marker],
        ref=f"honest-{status}",
    )
    with engine.connect() as conn:
        assert conn.exec_driver_sql(
            "SELECT COUNT(*) FROM payment_refunds WHERE provider_refund_ref ="
            f" 'honest-{status}'"
        ).scalar() == 1


def test_guarded_status_with_null_marker_is_rejected(seeded):
    """The three-valued-logic falsification must be REJECTED by the CHECK.

    A CHECK constraint only rejects a row when its predicate evaluates to
    FALSE; a NULL result is ACCEPTED. The naive form
    ``(status = 'active' AND active_slot_id = slot_id) OR (status <> 'active'
    AND active_slot_id IS NULL)`` evaluates to NULL for
    ``(status='active', active_slot_id=NULL)`` — branch 1 is NULL because
    ``NULL = slot_id`` is NULL, branch 2 is FALSE — so such a row used to INSERT
    cleanly and escape ``uq_booking_holds_active_slot_id`` altogether (NULLs are
    distinct). Both CHECKs now spell out ``marker IS NOT NULL`` inside the
    guarded branch, making the predicate two-valued for every input, so the
    portable marker fallback really does hold on every dialect.
    """
    engine, ids = seeded

    with pytest.raises(IntegrityError) as hold_error:
        insert_hold(
            engine,
            slot_id=ids["slot"],
            student_user_id=ids["user"],
            status="active",
            active_slot_id=None,
            key="null-marker-1",
        )
    assert "ck_booking_holds_active_marker" in str(hold_error.value)
    assert "check" in str(hold_error.value).lower()

    with pytest.raises(IntegrityError) as refund_error:
        insert_refund(
            engine,
            order_id=ids["order"],
            status="succeeded",
            succeeded_order_id=None,
            ref="null-marker-1",
        )
    assert "ck_payment_refunds_succeeded_marker" in str(refund_error.value)
    assert "check" in str(refund_error.value).lower()

    # Nothing was persisted: no 'active' hold, no 'succeeded' refund exists.
    with engine.connect() as conn:
        assert conn.exec_driver_sql(
            "SELECT COUNT(*) FROM booking_holds WHERE status = 'active'"
        ).scalar() == 0
        assert conn.exec_driver_sql(
            "SELECT COUNT(*) FROM payment_refunds WHERE status = 'succeeded'"
        ).scalar() == 0


def test_partial_unique_indexes_are_the_second_line_of_defence(seeded):
    """The native partial unique indexes still reject a second guarded row.

    The CHECKs above make the marker UNIQUEs sufficient on their own, so this
    test disables CHECK enforcement (``PRAGMA ignore_check_constraints``) to
    isolate layer 2: with NULL markers the marker UNIQUEs cannot fire, and the
    duplicate is caught purely by ``uq_booking_holds_one_active_per_slot`` /
    ``uq_payment_refunds_one_succeeded_per_order``.
    """
    engine, ids = seeded
    dialect = engine.dialect.name
    if dialect != "sqlite":  # pragma: no cover - sqlite in CI
        pytest.skip(f"{dialect}: CHECK enforcement cannot be toggled per session")

    def hold_row(key):
        return BookingHold.__table__.insert().values(
            id=uuid.uuid4(),
            slot_id=ids["slot"],
            student_user_id=ids["user"],
            status="active",
            expires_at=T0 + timedelta(minutes=15),
            idempotency_key=key,
            active_slot_id=None,  # marker UNIQUE cannot see NULLs
            created_at=T0,
            updated_at=T0,
        )

    def refund_row(ref):
        return PaymentRefund.__table__.insert().values(
            id=uuid.uuid4(),
            order_id=ids["order"],
            amount_paise=150000,
            reason="cancel_ge_24h",
            status="succeeded",
            provider_refund_ref=ref,
            succeeded_order_id=None,
            created_at=T0,
            updated_at=T0,
        )

    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA ignore_check_constraints = ON")

        conn.execute(hold_row("partial-index-1"))
        conn.execute(refund_row("partial-index-1"))
        conn.commit()

        with pytest.raises(IntegrityError) as hold_error:
            conn.execute(hold_row("partial-index-2"))
        assert "unique" in str(hold_error.value).lower()
        assert "booking_holds.slot_id" in str(hold_error.value)
        conn.rollback()

        with pytest.raises(IntegrityError) as refund_error:
            conn.execute(refund_row("partial-index-2"))
        assert "unique" in str(refund_error.value).lower()
        assert "payment_refunds.order_id" in str(refund_error.value)
        conn.rollback()

    with engine.connect() as conn:
        assert conn.exec_driver_sql(
            "SELECT COUNT(*) FROM booking_holds WHERE status = 'active'"
            f" AND slot_id = '{ids['slot'].hex}'"
        ).scalar() == 1
        assert conn.exec_driver_sql(
            "SELECT COUNT(*) FROM payment_refunds WHERE status = 'succeeded'"
            f" AND order_id = '{ids['order'].hex}'"
        ).scalar() == 1


# --------------------------------------------------------------------------- #
# 6. privacy: no cardholder / OTP / raw-credential column exists
# --------------------------------------------------------------------------- #
# Matched against the '_'-split segments of a real column name, so legitimate
# names such as `participant_ref` (which *contains* "pan") are not false hits.
FORBIDDEN_SEGMENTS = frozenset(
    {
        "pan", "pans", "cardnumber", "cardno", "card", "cvv", "cvv2", "cvc",
        "cvc2", "otp", "otps", "pin", "password", "passwd", "passcode",
        "secret", "secrets", "cleartext", "plaintext", "aadhaar", "aadhar",
        "vpa", "upi", "iban", "track1", "track2", "magstripe",
    }
)
# Unambiguous substrings that can never be innocent inside a column name.
FORBIDDEN_SUBSTRINGS = (
    "cvv", "cvc2", "_otp", "otp_", "card_number", "cardnumber", "card_num",
    "raw_token", "token_raw", "plain_token", "join_token", "access_token",
    "refresh_token", "bearer", "plaintext", "plain_text", "cleartext",
    "clear_text", "password", "passphrase", "_secret", "secret_",
)
# Exact names that must never exist.
FORBIDDEN_EXACT = frozenset(
    {
        "pan", "pan_number", "card", "card_number", "cvv", "cvv2", "cvc",
        "otp", "otp_code", "otp_hash", "token", "raw_token", "join_token",
        "join_url", "credential", "credentials", "secret", "api_key",
        "password",
    }
)
# Anything token/secret/credential-shaped may only be persisted as a digest.
SENSITIVE_STEMS = ("token", "secret", "credential", "password", "passphrase")
# Explicit, reviewed exemptions: booleans/flags that carry no secret material.
SENSITIVE_STEM_EXEMPTIONS = frozenset({"verified_credentials"})


def test_no_wave2_column_can_hold_card_otp_or_raw_credential_data(inspector):
    offenders: list[str] = []
    scanned = 0

    for table in EXPECTED_WAVE2_TABLES:
        for column in inspector.get_columns(table):
            name = column["name"].lower()
            scanned += 1
            where = f"{table}.{column['name']}"
            segments = set(name.split("_"))

            if segments & FORBIDDEN_SEGMENTS:
                offenders.append(f"{where} (segment {sorted(segments & FORBIDDEN_SEGMENTS)})")
            if name in FORBIDDEN_EXACT:
                offenders.append(f"{where} (forbidden name)")
            for needle in FORBIDDEN_SUBSTRINGS:
                if needle in name:
                    offenders.append(f"{where} (substring {needle!r})")
            if name not in SENSITIVE_STEM_EXEMPTIONS:
                for stem in SENSITIVE_STEMS:
                    if stem in name and not (
                        name.endswith("_hash") or name.endswith("_digest")
                    ):
                        offenders.append(
                            f"{where} (sensitive {stem!r} not hashed/digested)"
                        )

    assert scanned >= 100, f"introspected only {scanned} Wave 2 columns"
    assert offenders == [], "privacy-forbidden Wave 2 columns: " + "; ".join(offenders)

    # Keep the exemption honest: it must stay a boolean flag, not a value store.
    flag = next(
        c
        for c in inspector.get_columns("tutor_profiles")
        if c["name"] == "verified_credentials"
    )
    assert flag["type"].__class__.__name__.upper().startswith("BOOL"), flag["type"]


def test_video_session_grants_expose_only_a_token_hash(inspector):
    columns = {c["name"] for c in inspector.get_columns("video_session_grants")}
    assert "token_hash" in columns
    token_like = {c for c in columns if "token" in c or "secret" in c or "jwt" in c}
    assert token_like == {"token_hash"}, f"raw join credential columns: {token_like}"

    hashed = next(
        c for c in inspector.get_columns("video_session_grants") if c["name"] == "token_hash"
    )
    assert getattr(hashed["type"], "length", None) == 64, "token_hash is not digest-sized"


def test_payment_tables_store_only_issuer_display_crumbs_and_digests(inspector):
    order_columns = {c["name"] for c in inspector.get_columns("payment_orders")}
    assert {"brand", "masked_last4", "expiry_month", "expiry_year"} <= order_columns
    assert not order_columns & {"pan", "card_number", "cvv", "cvv2", "otp", "otp_code"}
    masked = next(
        c for c in inspector.get_columns("payment_orders") if c["name"] == "masked_last4"
    )
    assert getattr(masked["type"], "length", None) == 4

    event_columns = {c["name"] for c in inspector.get_columns("payment_events")}
    assert "payload_digest" in event_columns
    assert not any(c in event_columns for c in ("payload", "payload_raw", "raw_body"))


# --------------------------------------------------------------------------- #
# 7. alembic lifecycle: upgrade -> no drift -> downgrade -> re-upgrade
# --------------------------------------------------------------------------- #
def _live_tables(db: str) -> set[str]:
    engine = create_engine(f"sqlite+pysqlite:///{db}")
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_alembic_lifecycle_upgrade_check_downgrade_reupgrade(migrated_db, tmp_path):
    # (a) upgrade head already ran in the module fixture, with rc 0.
    assert migrated_db.upgrade.returncode == 0, migrated_db.upgrade.stderr[-2000:]

    db = str(tmp_path / "lifecycle.db")
    shutil.copyfile(migrated_db.path, db)
    assert scalar(db, "SELECT version_num FROM alembic_version") == HEAD_REVISION
    at_head = _live_tables(db)
    assert set(EXPECTED_WAVE2_TABLES) <= at_head

    # (b) no autogenerate drift between models and migrations (db_gate.sh step).
    check = alembic(db, "check")
    assert check.returncode == 0, (
        "alembic check reported model/migration drift:\n"
        f"{check.stdout[-2000:]}\n{check.stderr[-2000:]}"
    )
    assert "No new upgrade operations detected." in check.stdout

    # (c) downgrade to 0008's parent: all 17 Wave 2 tables gone, rest intact.
    down = alembic(db, "downgrade", PARENT_REVISION)
    assert down.returncode == 0, down.stderr[-2000:]
    assert scalar(db, "SELECT version_num FROM alembic_version") == PARENT_REVISION
    after_down = _live_tables(db)
    leftovers = sorted(after_down & set(EXPECTED_WAVE2_TABLES))
    assert leftovers == [], f"downgrade left Wave 2 tables behind: {leftovers}"
    # Everything 0008/0009/0010/0011 did not own must survive, and nothing appears.
    assert after_down == at_head - set(EXPECTED_WAVE2_TABLES) - POST_WAVE2_TABLES
    assert "users" in after_down

    # (d) clean re-upgrade restores exactly the same table set, drift-free.
    up = alembic(db, "upgrade", "head")
    assert up.returncode == 0, up.stderr[-2000:]
    assert scalar(db, "SELECT version_num FROM alembic_version") == HEAD_REVISION
    assert _live_tables(db) == at_head
    recheck = alembic(db, "check")
    assert recheck.returncode == 0, recheck.stdout[-2000:] + recheck.stderr[-2000:]


# --------------------------------------------------------------------------- #
# 8. ORM <-> migrated DB parity
# --------------------------------------------------------------------------- #
def test_orm_and_migrated_db_columns_and_nullability_match(inspector):
    mismatches: list[str] = []
    for name, table in sorted(wave2_tables().items()):
        orm = {column.name: bool(column.nullable) for column in table.columns}
        live = {
            column["name"]: bool(column["nullable"])
            for column in inspector.get_columns(name)
        }
        for column in sorted(set(orm) | set(live)):
            if column not in live:
                mismatches.append(f"{name}.{column}: in ORM, missing from DB")
            elif column not in orm:
                mismatches.append(f"{name}.{column}: in DB, missing from ORM")
            elif orm[column] != live[column]:
                mismatches.append(
                    f"{name}.{column}: nullable ORM={orm[column]} DB={live[column]}"
                )
    assert mismatches == [], "ORM/migration parity broken: " + "; ".join(mismatches)


def test_every_wave2_table_carries_the_shared_base_columns(inspector):
    base_columns = {"id", "created_at", "updated_at", "deleted_at", "metadata_json"}
    for table in EXPECTED_WAVE2_TABLES:
        columns = {c["name"] for c in inspector.get_columns(table)}
        assert base_columns <= columns, f"{table} is missing {base_columns - columns}"
        assert inspector.get_pk_constraint(table)["constrained_columns"] == ["id"]
