import pytest
from cvp.config import get_settings


def test_default_database_url_is_sqlite(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.database_url.startswith("sqlite:///")
    get_settings.cache_clear()


def test_database_url_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/db")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.database_url == "postgresql+psycopg://u:p@h:5432/db"
    get_settings.cache_clear()
