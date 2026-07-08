import pytest
import sqlalchemy as sa

from claimos.migrate_db import TABLE_PLAN, migrate, raise_on_parity_mismatch, verify_parity
from claimos.models import Base

# Subset of TABLE_PLAN matching the minimal fixtures below (groups/claims/rooms).
_SUBSET_PLAN = [(t, s, r) for t, s, r in TABLE_PLAN if t in {"groups", "claims", "rooms"}]


def _make_legacy_db(url: str) -> None:
    """Minimal CVP-schema (pre-rename) fixture built with raw DDL so it does not
    depend on the removed `matters` ORM classes."""
    eng = sa.create_engine(url)
    with eng.begin() as c:
        c.exec_driver_sql(
            "CREATE TABLE groups (id TEXT PRIMARY KEY, name TEXT, kind TEXT, is_active INTEGER)"
        )
        c.exec_driver_sql(
            "CREATE TABLE matters (id TEXT PRIMARY KEY, policyholder_name TEXT, "
            "owner_group_id TEXT, status TEXT)"
        )
        c.exec_driver_sql(
            "CREATE TABLE rooms (id TEXT PRIMARY KEY, matter_id TEXT, name TEXT, "
            "sort_order INTEGER)"
        )
        c.exec_driver_sql("INSERT INTO groups VALUES ('g1', 'Acme Firm', 'external', 1)")
        c.exec_driver_sql("INSERT INTO matters VALUES ('m1', 'Jane Doe', 'g1', 'draft')")
        c.exec_driver_sql("INSERT INTO rooms VALUES ('r1', 'm1', 'Kitchen', 0)")


def _make_claimos_db(url: str) -> None:
    """Target ClaimOS schema (subset matching the plan under test)."""
    eng = sa.create_engine(url)
    with eng.begin() as c:
        c.exec_driver_sql(
            "CREATE TABLE groups (id TEXT PRIMARY KEY, name TEXT, kind TEXT, is_active INTEGER)"
        )
        c.exec_driver_sql(
            "CREATE TABLE claims (id TEXT PRIMARY KEY, policyholder_name TEXT, "
            "owner_group_id TEXT, status TEXT)"
        )
        c.exec_driver_sql(
            "CREATE TABLE rooms (id TEXT PRIMARY KEY, claim_id TEXT, name TEXT, sort_order INTEGER)"
        )


def test_migrate_copies_and_remaps(tmp_path):
    src = f"sqlite:///{tmp_path / 'legacy.db'}"
    tgt = f"sqlite:///{tmp_path / 'claimos.db'}"
    _make_legacy_db(src)
    _make_claimos_db(tgt)

    counts = migrate(src, tgt, only_tables=["groups", "claims", "rooms"])

    assert counts == {"groups": 1, "claims": 1, "rooms": 1}

    eng = sa.create_engine(tgt)
    with eng.connect() as c:
        claim = c.exec_driver_sql("SELECT id, policyholder_name FROM claims").one()
        room = c.exec_driver_sql("SELECT id, claim_id, name FROM rooms").one()
    assert claim == ("m1", "Jane Doe")
    assert room == ("r1", "m1", "Kitchen")  # matter_id -> claim_id preserved value


def test_table_plan_is_fk_safe_topological_order():
    """TABLE_PLAN must never copy a child table before a parent it has an FK to.

    On Postgres, FKs are enforced (unlike SQLite in these tests), so an
    out-of-order plan silently passes here but hard-fails in production. Guard
    against that by checking TABLE_PLAN's order against the authoritative FK
    graph in the ORM metadata.
    """
    plan_tables = [target for target, _source, _renames in TABLE_PLAN]
    index = {table: pos for pos, table in enumerate(plan_tables)}

    sorted_tables = Base.metadata.sorted_tables
    assert set(plan_tables) == {t.name for t in sorted_tables}, (
        "TABLE_PLAN must cover exactly the tables in the ORM metadata"
    )
    assert len(plan_tables) == 21

    for table in sorted_tables:
        for fk in table.foreign_keys:
            parent = fk.column.table.name
            if parent == table.name:
                continue  # self-referential FK, not relevant to ordering
            assert index[table.name] >= index[parent], (
                f"TABLE_PLAN places child table '{table.name}' (position "
                f"{index[table.name]}) before its FK-parent '{parent}' "
                f"(position {index[parent]})"
            )


def test_verify_parity_matches_after_full_migrate(tmp_path):
    src = f"sqlite:///{tmp_path / 'legacy.db'}"
    tgt = f"sqlite:///{tmp_path / 'claimos.db'}"
    _make_legacy_db(src)
    _make_claimos_db(tgt)

    migrate(src, tgt, only_tables=["groups", "claims", "rooms"])

    parity = verify_parity(src, tgt, table_plan=_SUBSET_PLAN)

    assert parity == {"groups": (1, 1), "claims": (1, 1), "rooms": (1, 1)}
    raise_on_parity_mismatch(parity)  # must not raise: everything matches


def test_verify_parity_reports_and_raises_on_missing_rows(tmp_path):
    src = f"sqlite:///{tmp_path / 'legacy.db'}"
    tgt = f"sqlite:///{tmp_path / 'claimos.db'}"
    _make_legacy_db(src)
    _make_claimos_db(tgt)

    # Only migrate a subset of tables, leaving "rooms" un-migrated in the target.
    migrate(src, tgt, only_tables=["groups", "claims"])

    parity = verify_parity(src, tgt, table_plan=_SUBSET_PLAN)

    # rooms: 1 row in the legacy source, 0 copied into the target -> mismatch reported.
    assert parity["rooms"] == (1, 0)
    assert parity["groups"] == (1, 1)
    assert parity["claims"] == (1, 1)

    with pytest.raises(RuntimeError, match="rooms"):
        raise_on_parity_mismatch(parity)


def test_copy_table_raises_on_source_column_with_no_target_counterpart(tmp_path):
    """A legacy column that survives the matter_id->claim_id remap but has no
    counterpart in the target table must fail loudly and early, naming the
    table and the offending column, instead of an opaque INSERT error."""
    src = f"sqlite:///{tmp_path / 'legacy.db'}"
    tgt = f"sqlite:///{tmp_path / 'claimos.db'}"

    eng = sa.create_engine(src)
    with eng.begin() as c:
        c.exec_driver_sql(
            "CREATE TABLE rooms (id TEXT PRIMARY KEY, matter_id TEXT, name TEXT, "
            "sort_order INTEGER, extra_legacy_col TEXT)"
        )
        c.exec_driver_sql("INSERT INTO rooms VALUES ('r1', 'm1', 'Kitchen', 0, 'unexpected')")

    eng = sa.create_engine(tgt)
    with eng.begin() as c:
        c.exec_driver_sql(
            "CREATE TABLE rooms (id TEXT PRIMARY KEY, claim_id TEXT, name TEXT, sort_order INTEGER)"
        )

    with pytest.raises(RuntimeError) as exc_info:
        migrate(src, tgt, only_tables=["rooms"])

    message = str(exc_info.value)
    assert "rooms" in message
    assert "extra_legacy_col" in message
