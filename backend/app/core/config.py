from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Customs Document Intelligence Platform"
    database_url: str = "sqlite:///./customs.db"
    secret_key: str = "development-only-change-me"
    access_token_expire_minutes: int = 60
    auto_create_tables: bool = True
    local_storage_path: str = "./private_storage"
    max_upload_size_bytes: int = 25 * 1024 * 1024
    max_processing_attempts: int = 3
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    ai_provider: str = "gemini"
    ai_api_key: str | None = None
    ai_model: str | None = None
    ai_base_url: str | None = None
    ai_timeout_seconds: float = 60.0
    ai_anthropic_version: str = "2023-06-01"
    ocr_provider: str = "paddleocr"
    ocr_dpi: int = 200
    ocr_language: str = "en"
    # Legacy names remain supported so existing Gemini deployments do not break.
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.0-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_timeout_seconds: float = 60.0

    model_config = SettingsConfigDict(env_file=".env", env_prefix="CUSTOMS_", extra="ignore")


settings = Settings()


def get_cors_origins() -> list[str]:
    return [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
