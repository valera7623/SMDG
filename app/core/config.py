# app/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # API ключи (оставляем для совместимости, но не используем)
    api_keys: str = "test-token-123"

    # JWT настройки
    jwt_secret_key: str = "change-me-to-very-strong-secret-256-bits-minimum!!!"
    jwt_access_expires_minutes: int = 60
    jwt_algorithm: str = "HS256"

    # Другие настройки (debug, dev_mode)
    debug: bool = False
    dev_mode: bool = False

    @property
    def api_keys_set(self) -> set[str]:
        return {k.strip() for k in self.api_keys.split(",") if k.strip()}

settings = Settings()