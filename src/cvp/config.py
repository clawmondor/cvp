from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    anthropic_api_key: str = ""
    vision_model: str = "claude-opus-4-6"
    vision_model_fallback: str = "claude-sonnet-4-6"
    database_url: str = "sqlite:///./data/cvp.db"
    upload_dir: str = "./data/uploads"
    export_dir: str = "./data/exports"
    company_name: str = "Contents Valuation LLC"
    company_address: str = ""
    company_email: str = ""
    company_phone: str = ""


settings = Settings()
