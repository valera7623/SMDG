# app/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Set

class Settings(BaseSettings):
    """
    Конфигурация приложения через переменные окружения.
    Поддерживает .env файл в корне проекта.
    """
    model_config = SettingsConfigDict(
        env_file=".env",           # автоматически загрузит .env, если есть
        env_file_encoding="utf-8",
        case_sensitive=False,      # нечувствительно к регистру
        extra="ignore"             # игнорировать лишние переменные
    )

    # API ключи
    api_keys: str = "test-token-123"          # fallback для dev
    debug: bool = False
    dev_mode: bool = False

    @property
    def api_keys_set(self) -> Set[str]:
        """Возвращает множество API-ключей"""
        return {key.strip() for key in self.api_keys.split(",") if key.strip()}

    @property
    def is_debug(self) -> bool:
        return self.debug

    @property
    def is_dev_mode(self) -> bool:
        return self.dev_mode


# Глобальный экземпляр настроек
settings = Settings()