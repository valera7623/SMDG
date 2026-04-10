# app/core/config.py
import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8" if os.getenv("DEV_MODE", "false").lower() == "true" else None,
        case_sensitive=False,
        extra="ignore",
    )

    # Обязательные поля — без дефолтов!
    database_url: str
    redis_url: str
    jwt_secret_key: str
    admin_password: str
    
    # Опциональные с разумными дефолтами (не секретные)
    jwt_access_expires_minutes: int = 60
    jwt_algorithm: str = "HS256"
    debug: bool = False
    dev_mode: bool = False 
    
    # ClamAV
    CLAMAV_HOST: str = "clamav"  
    CLAMAV_PORT: int = 3310
    CLAMAV_TIMEOUT: int = 60  

    # Максимальный размер файла
    MAX_UPLOAD_SIZE_MB: int = 600

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

    # S3 / MinIO Configuration (опционально)
    s3_endpoint_url: str | None = None  # e.g. "http://minio:9000" или AWS S3 URL
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_bucket_encrypted: str = "smdg-encrypted"
    s3_bucket_uploads: str = "smdg-uploads"
    s3_bucket_decrypted: str = "smdg-decrypted"
    s3_region: str = "us-east-1"
    s3_use_ssl: bool = False
    s3_enabled: bool = False

    @property
    def is_s3_enabled(self) -> bool:
        """Проверяет, включён ли S3 режим."""
        return self.s3_enabled and bool(self.s3_endpoint_url) and bool(self.s3_access_key)


settings = Settings()