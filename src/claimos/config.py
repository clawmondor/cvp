import functools
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str = ""  # deprecated — use OpenRouter instead
    vision_model: str = "claude-opus-4-6"  # deprecated — use VisionModel DB rows
    vision_model_fallback: str = "claude-sonnet-4-6"  # deprecated — remove soon
    openrouter_api_key: str = ""
    openrouter_referer: str = ""
    openrouter_app_title: str = "CVP"
    port: int = 8000
    database_url: str = "sqlite:///./data/claimos.db"
    upload_dir: str = "./data/uploads"
    export_dir: str = "./data/exports"
    crop_dir: str = "./data/crops"
    serp_api_key: str = ""
    public_base_url: str = ""
    company_name: str = "Contents Valuation LLC"
    company_address: str = ""
    company_email: str = ""
    company_phone: str = ""

    # Auth settings
    environment: str = "production"
    jwt_secret: str = ""
    jwt_access_ttl_minutes: int = 60
    jwt_refresh_ttl_days: int = 7
    mfa_encryption_key: str = ""
    auto_login_user_id: str = ""
    cookie_secure: bool = True
    cookie_domain: str = ""
    rate_limit_enabled: bool = True

    # Evidence upload runtime knobs — overridable per claim session via app_setting table
    evidence_upload_concurrency: int = 4
    evidence_upload_max_file_mb: int = 10
    evidence_upload_max_batch_count: int = 500


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
