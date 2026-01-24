# app/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # Существующие поля
    jwt_secret_key: str = "change-me-to-very-strong-secret-256-bits-minimum!!!"
    jwt_access_expires_minutes: int = 60
    jwt_algorithm: str = "HS256"
    debug: bool = False
    dev_mode: bool = False
    jwt_secret_key: str
    admin_password: str | None = None         
    database_url: str

    # ← Добавляем это!
    database_url: str = "postgresql+asyncpg://smdg_user:password@localhost:5432/smdg"

    # Опционально: можно добавить отдельные поля для удобства
    # POSTGRES_USER: str = "postgres"
    # POSTGRES_PASSWORD: str = "postgres"
    # POSTGRES_DB: str = "smdg"
    # POSTGRES_HOST: str = "localhost"
    # POSTGRES_PORT: int = 5432

    # @property
    # def database_url(self) -> str:
    #     return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    redis_url: str = "redis://localhost:6379/0"
    
settings = Settings()