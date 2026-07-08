import sqlalchemy as sa

from claimos.migrate_db import migrate


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
