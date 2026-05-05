import functools

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str = ""
    vision_model: str = "claude-opus-4-6"
    vision_model_fallback: str = "claude-sonnet-4-6"
    port: int = 8000
    database_url: str = "sqlite:///./data/cvp.db"
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


settings = Settings()


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
