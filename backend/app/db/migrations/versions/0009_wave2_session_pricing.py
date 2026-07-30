"""Server-authoritative session price + immutable hold price snapshot.

SAATHI-123 / SAATHI-127 remediation. Forward-only on top of
``0008_wave2_tutoring``; 0008 and every earlier revision are untouched.

Why this migration exists
-------------------------
Wave 2 shipped with the session price CLIENT-AUTHORITATIVE: ``payment_orders``
had an ``amount_paise`` column but nothing in the schema said what that amount
was SUPPOSED to be, so ``POST /payments/orders`` took the number from the
request body. A malicious client could open a zero-priced or under-priced order,
and a correctly signed provider callback would then only ever prove payment of
the attacker-chosen amount. The signature was never the weak link — the price
was. This revision gives the price a home in the database so the service can
DERIVE it instead of being told it.

Where the columns went, and why
-------------------------------
``tutor_profiles.session_price_paise`` / ``session_currency``
    The published price of one session with this tutor, in INTEGER PAISE. It
    belongs on the PROFILE, not on the slot: a price is a property of the
    tutor's offering, whereas ``tutor_availability_slots`` rows are generated in
    bulk from a calendar (``seed.slot_starts``, and the availability writer that
    will follow) and carry no commercial data at all — putting the price there
    would mean re-stamping every future slot on every re-price and would leave
    "what does this tutor cost" with no single answer. Currency is stored beside
    it rather than assumed, because "INR" being the only member of
    ``PAYMENT_CURRENCIES`` today is a product decision, not a law.

``booking_holds.price_paise`` / ``price_currency``
    The IMMUTABLE SNAPSHOT of that price, taken by ``booking.create_hold`` at
    the instant the slot is reserved. ``payments.create_order`` derives
    ``payment_orders.amount_paise``/``currency`` from this snapshot and from
    nothing else. Two properties fall out of putting it here:
      * a re-price while a student is in checkout cannot move the amount of a
        hold that is already in flight (the money the student was quoted is the
        money they are charged), and
      * ``payment_orders`` already RESTRICTs deletion of its hold, so the price
        actually charged stays auditable for as long as the order does.
    A replay of the same idempotency key returns the SAME hold row, so the
    snapshot survives a retry unchanged; no service code path UPDATEs these
    columns after the INSERT that writes them.

Strictly positive, by CHECK
---------------------------
Both price columns carry a ``> 0`` CHECK (``ck_tutor_profiles_session_price_positive``,
``ck_booking_holds_price_positive``). Zero is NOT "free tutoring": a free
offering would need its own explicit product flag, and inferring it from a zero
amount is precisely how a tampered order becomes indistinguishable from a
legitimate one. ``payment_orders.amount_paise`` keeps its historical ``>= 0``
CHECK from 0008 (0008 is not rewritten); its positivity now comes from the
``> 0`` snapshot it is copied from.

Dialect portability (same discipline as 0008)
---------------------------------------------
UPGRADE uses one ``ALTER TABLE ... ADD COLUMN <name> <type> DEFAULT <const>
NOT NULL CONSTRAINT <name> CHECK (...)`` per column. That single form is valid
on PostgreSQL and on SQLite alike (SQLite permits a CHECK in an ADD COLUMN
definition and permits NOT NULL when a CONSTANT default is supplied — which is
why the defaults are literals and ``priced_at``-style ``now()`` columns are
deliberately absent), and SQLAlchemy's inspector reports the named CHECK on both
so ``test_named_check_and_unique_constraints_are_all_migrated`` sees it.

The constant server defaults exist ONLY so the ADD COLUMN is legal against a
non-empty table; the services always write both values explicitly. Existing
rows are then reconciled: profiles are stamped with the deployment default and
every pre-existing hold is backfilled from ITS OWN tutor's price, so a hold
created before this revision is priced by the same rule as one created after it.

DOWNGRADE cannot be a bare ``DROP COLUMN`` on SQLite: SQLite refuses to drop a
column named in a CHECK constraint, and CHECKs cannot be ALTERed away. So the
downgrade runs inside ``op.batch_alter_table``, dropping the CHECK and then the
column. On SQLite that recreates the table (preserving the marker UNIQUEs and
the partial unique index ``uq_booking_holds_one_active_per_slot``); on
PostgreSQL, which supports ALTER, alembic emits plain ``DROP CONSTRAINT`` /
``DROP COLUMN`` and recreates nothing.
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_wave2_session_pricing"
down_revision: Union[str, None] = "0008_wave2_tutoring"
branch_labels = None
depends_on = None

#: Deployment-wide fallback price, in INTEGER PAISE (Rs 2,500.00). Mirrors
#: ``settings.tutoring_default_session_price_paise`` and the ORM's column
#: default; a migration must not import runtime settings, so the literal is
#: repeated here and pinned by ``test_wave2_pricing_authority.py``.
DEFAULT_SESSION_PRICE_PAISE = 250_000
DEFAULT_CURRENCY = "INR"

#: (table, column, type, default literal, CHECK suffix, CHECK predicate).
#: The suffix is what ``app/models/wave2.py`` passes as ``name=`` on the
#: CheckConstraint; the metadata naming convention
#: (``ck_%(table_name)s_%(constraint_name)s``) turns it into the full name, and
#: ``batch_alter_table`` applies that same convention when dropping — so the
#: SUFFIX, not the rendered name, is what must be stored here.
_PRICE_COLUMNS = (
    (
        "tutor_profiles",
        "session_price_paise",
        "INTEGER",
        str(DEFAULT_SESSION_PRICE_PAISE),
        "session_price_positive",
        "session_price_paise > 0",
    ),
    (
        "tutor_profiles",
        "session_currency",
        "VARCHAR(3)",
        f"'{DEFAULT_CURRENCY}'",
        "session_currency",
        f"session_currency IN ('{DEFAULT_CURRENCY}')",
    ),
    (
        "booking_holds",
        "price_paise",
        "INTEGER",
        str(DEFAULT_SESSION_PRICE_PAISE),
        "price_positive",
        "price_paise > 0",
    ),
    (
        "booking_holds",
        "price_currency",
        "VARCHAR(3)",
        f"'{DEFAULT_CURRENCY}'",
        "price_currency",
        f"price_currency IN ('{DEFAULT_CURRENCY}')",
    ),
)


def _check_name(table: str, suffix: str) -> str:
    """Render the naming convention by hand for the raw ADD COLUMN DDL."""
    return f"ck_{table}_{suffix}"


def upgrade() -> None:
    for table, column, type_, default, suffix, predicate in _PRICE_COLUMNS:
        op.execute(
            sa.text(
                f"ALTER TABLE {table} ADD COLUMN {column} {type_} "
                f"DEFAULT {default} NOT NULL "
                f"CONSTRAINT {_check_name(table, suffix)} CHECK ({predicate})"
            )
        )

    # Reconcile the rows that already existed. Profiles take the deployment
    # default; every pre-existing hold is re-derived from ITS OWN tutor's price
    # through its slot, so a hold written before this revision is priced by
    # exactly the rule ``booking.create_hold`` applies after it. Correlated
    # sub-selects only — portable to both dialects, no UPDATE ... FROM.
    op.execute(
        sa.text(
            "UPDATE tutor_profiles SET "
            f"session_price_paise = {DEFAULT_SESSION_PRICE_PAISE}, "
            f"session_currency = '{DEFAULT_CURRENCY}'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE booking_holds SET price_paise = COALESCE(("
            "  SELECT p.session_price_paise"
            "  FROM tutor_availability_slots s"
            "  JOIN tutor_profiles p ON p.id = s.tutor_id"
            "  WHERE s.id = booking_holds.slot_id"
            f"), {DEFAULT_SESSION_PRICE_PAISE}), "
            "price_currency = COALESCE(("
            "  SELECT p.session_currency"
            "  FROM tutor_availability_slots s"
            "  JOIN tutor_profiles p ON p.id = s.tutor_id"
            "  WHERE s.id = booking_holds.slot_id"
            f"), '{DEFAULT_CURRENCY}')"
        )
    )


def downgrade() -> None:
    # Grouped per table so each table is recreated at most ONCE on SQLite.
    for table in ("booking_holds", "tutor_profiles"):
        columns = [row for row in _PRICE_COLUMNS if row[0] == table]
        with op.batch_alter_table(table) as batch:
            for _table, _column, _type, _default, suffix, _predicate in columns:
                # The convention expands this to ck_<table>_<suffix>.
                batch.drop_constraint(suffix, type_="check")
            for _table, column, _type, _default, _suffix, _predicate in columns:
                batch.drop_column(column)
