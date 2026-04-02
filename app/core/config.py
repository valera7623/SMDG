# app/core/config.py

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Обязательные поля — без дефолтов!
    database_url: str
    redis_url: str
    jwt_secret_key: str
    admin_password: str= "default_admin_password"
    
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


    
settings = Settings()