"""Upgrading across the nickname migration backfills existing claims to a
non-null 'Claim <id[:8]>' value and creates the unique index."""

import pathlib

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine

PREV_REVISION = "515c6c0e7711"  # retail_value_shipping (head before nickname)


def _cfg(db_url: str) -> AlembicConfig:
    cfg = AlembicConfig("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def test_backfill_and_index(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    db_url = f"sqlite:///{tmp_path}/nick.db"
    import claimos.config as config_module

    monkeypatch.setattr(config_module.settings, "database_url", db_url)
    cfg = _cfg(db_url)

    # Migrate up to the revision *before* nickname, then seed a claim with no nickname.
    command.upgrade(cfg, PREV_REVISION)
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    with engine.begin() as c:
        c.exec_driver_sql(
            """
            INSERT INTO claims (
                id, owner_group_id, firm_name, attorney_name, attorney_email,
                policyholder_name, loss_location, loss_type, loss_event, carrier,
                policy_number, claim_number, coverage_c_limit, firm_file_number,
                status, internal_notes
            ) VALUES (
                'abcdef1234567890', 'g1', '', '', '',
                '', '', '', '', '',
                '', '', 0, '',
                '', ''
            )
            """
        )

    # Now run the nickname migration.
    command.upgrade(cfg, "head")

    with engine.connect() as c:
        nickname = c.exec_driver_sql(
            "SELECT nickname FROM claims WHERE id = 'abcdef1234567890'"
        ).scalar_one()
    assert nickname == "Claim abcdef12"

    # SQLAlchemy's SQLite reflection cannot introspect expression-based indexes
    # (it emits a SAWarning and silently skips them), so check sqlite_master directly.
    with engine.connect() as c:
        index_names = {
            row[0]
            for row in c.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'claims'"
            )
        }
    assert "uq_claims_group_nickname_ci" in index_names
