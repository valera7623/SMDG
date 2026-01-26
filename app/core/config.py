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
    redis_url: str = "redis://localhost:6379/0"
    
    # ClamAV
    CLAMAV_HOST: str = "clamav"  # имя сервиса в docker-compose
    CLAMAV_PORT: int = 3310
    CLAMAV_TIMEOUT: int = 60  # секунд на сканирование

    # Максимальный размер файла
    MAX_UPLOAD_SIZE_MB: int = 50

    # Расширенный список MIME (DICOM + медицинские)
    ALLOWED_MIME_TYPES: list[str] = [
        "application/pdf",
        "image/jpeg", "image/png", "image/tiff", "image/gif",
        "text/plain", "text/csv",
        "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/dicom",  # основной для DICOM
        "application/octet-stream",  # иногда DICOM идёт как octet-stream
        "application/json", "application/xml"
    ]

    # DICOM-сигнатуры (первые байты файла)
    DICOM_MAGIC: bytes = b'\x00\x00\x00\x00DICM'  # offset 128, "DICM"


    
settings = Settings()