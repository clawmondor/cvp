from claimos.config import get_settings


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


def test_settings_has_openrouter_fields(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    monkeypatch.setenv("OPENROUTER_REFERER", "https://claimos.example")
    monkeypatch.setenv("OPENROUTER_APP_TITLE", "CVP-test")
    from claimos.config import Settings

    s = Settings()
    assert s.openrouter_api_key == "sk-or-v1-test"
    assert s.openrouter_referer == "https://claimos.example"
    assert s.openrouter_app_title == "CVP-test"


def test_settings_openrouter_defaults():
    from claimos.config import Settings

    s = Settings(_env_file=None)
    assert s.openrouter_api_key == ""
    assert s.openrouter_referer == ""
    assert s.openrouter_app_title == "CVP"
