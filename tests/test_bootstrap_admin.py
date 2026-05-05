import pytest

from cvp.config import get_settings


def test_skips_when_admin_already_exists(monkeypatch, tmp_path, capsys):
    import cvp.config as config_module

    db_url = f"sqlite:///{tmp_path}/bootstrap.db"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr(config_module.settings, "database_url", db_url)
    monkeypatch.setenv("INITIAL_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "correct-horse-battery-staple")
    get_settings.cache_clear()

    from alembic import command
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(cfg, "head")

    from cvp.bootstrap_admin import main as bootstrap_admin

    bootstrap_admin()  # first run: creates admin
    bootstrap_admin()  # second run: skips

    out = capsys.readouterr().out
    assert "skipped" in out.lower()
    get_settings.cache_clear()


def test_raises_when_env_vars_missing(monkeypatch, tmp_path):
    import cvp.config as config_module

    db_url = f"sqlite:///{tmp_path}/bootstrap2.db"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr(config_module.settings, "database_url", db_url)
    monkeypatch.delenv("INITIAL_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("INITIAL_ADMIN_PASSWORD", raising=False)
    get_settings.cache_clear()

    from alembic import command
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(cfg, "head")

    from cvp.bootstrap_admin import main as bootstrap_admin

    with pytest.raises(SystemExit):
        bootstrap_admin()
    get_settings.cache_clear()
