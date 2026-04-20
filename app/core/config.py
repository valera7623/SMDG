# app/core/config.py
import os
from pathlib import Path
from typing import Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.feature_flags import DeploymentType, Feature, is_enabled


def read_secret(secret_name: str, env_var: str = None, default: str = None) -> str:
    """
    Читает секрет из Docker secret или переменной окружения.
    Приоритет: Docker secret > переменная окружения > default
    """
    # Пути к Docker secrets
    secret_paths = [
        Path(f"/run/secrets/{secret_name}"),
        Path(f"/run/secrets/smdg_{secret_name}"),  # на случай если есть префикс
    ]
    
    for secret_path in secret_paths:
        if secret_path.exists():
            with open(secret_path, 'r') as f:
                return f.read().strip()
    
    # Если secret не найден, пробуем переменную окружения
    if env_var:
        value = os.getenv(env_var)
        if value:
            return value
    
    # Возвращаем default если ничего не найдено
    if default is not None:
        return default
    
    # Если default нет - возвращаем пустую строку
    return ""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Приватные поля для хранения значений из secrets
    _database_url: str = ""
    _redis_url: str = ""
    _jwt_secret_key: str = ""
    _admin_password: str = ""
    
    @property
    def database_url(self) -> str:
        """Читает DATABASE_URL из secrets или переменной окружения"""
        if not self._database_url:
            # Пробуем прочитать из файла secret
            secret_value = read_secret('database_url', 'DATABASE_URL')
            if secret_value:
                self._database_url = secret_value
            else:
                # Если нет - собираем из отдельных компонентов
                postgres_password = read_secret('postgres_password', 'POSTGRES_PASSWORD', 'password')
                postgres_user = os.getenv('POSTGRES_USER', 'smdg_user')
                postgres_db = os.getenv('POSTGRES_DB', 'smdg')
                postgres_host = os.getenv('POSTGRES_HOST', 'db')
                postgres_port = os.getenv('POSTGRES_PORT', '5432')
                
                self._database_url = f"postgresql+asyncpg://{postgres_user}:{postgres_password}@{postgres_host}:{postgres_port}/{postgres_db}"
        
        return self._database_url
    
    @property
    def redis_url(self) -> str:
        """Читает REDIS_URL из secrets или переменной окружения"""
        if not self._redis_url:
            self._redis_url = read_secret('redis_url', 'REDIS_URL', 'redis://redis:6379/0')
        return self._redis_url
    
    @property
    def jwt_secret_key(self) -> str:
        """Читает JWT_SECRET_KEY из secrets или переменной окружения"""
        if not self._jwt_secret_key:
            self._jwt_secret_key = read_secret('jwt_secret_key', 'JWT_SECRET_KEY')
            if not self._jwt_secret_key:
                # В dev режиме можно использовать дефолтный ключ
                if self.dev_mode:
                    self._jwt_secret_key = "dev-secret-key-change-in-production-min-32-chars"
                else:
                    raise ValueError("JWT_SECRET_KEY is required in production mode")
        return self._jwt_secret_key
    
    @property
    def admin_password(self) -> str:
        """Читает ADMIN_PASSWORD из secrets или переменной окружения"""
        if not self._admin_password:
            self._admin_password = read_secret('admin_password', 'ADMIN_PASSWORD')
            if not self._admin_password:
                if self.dev_mode:
                    self._admin_password = "admin123"
                else:
                    raise ValueError("ADMIN_PASSWORD is required in production mode")
        return self._admin_password
    
    # Опциональные с разумными дефолтами (не секретные)
    jwt_access_expires_minutes: int = 60
    jwt_algorithm: str = "HS256"
    debug: bool = False
    dev_mode: bool = False

    # Профиль развёртывания (см. docs/DEPLOYMENT.md, app/core/feature_flags.py)
    deployment_type: DeploymentType = Field(
        default=DeploymentType.SINGLE_TENANT,
        description="Тип развёртывания: russia | intl | single | saas",
    )

    # Multi-tenant: поддомен резервного tenant при Host без поддомена (см. resolve_tenant_by_host)
    tenant_default_subdomain: str = "default"
    # Если true — для Host localhost / 127.0.0.1 / ::1 без поддомена подставляется tenant_default_subdomain (удобно для https://localhost)
    tenant_resolve_localhost_as_default: bool = True

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
        "application/dicom",
        "application/octet-stream",
        "application/json", "application/xml"
    ]

    # DICOM Viewer
    dicom_viewer_enabled: bool = True
    dicom_view_token_ttl_seconds: int = 900          # 15 минут

    # S3 Lifecycle Policies
    s3_lifecycle_enabled: bool = True                 # Включить S3 Lifecycle Policies
    s3_lifecycle_default_ttl_days: int = 30           # TTL по умолчанию (дни)
    s3_lifecycle_custom_policies: str = ""            # JSON с кастомными политиками: '{"ext":days}'
    dicom_max_stream_size_mb: int = 500              # Макс. размер для streaming

    # DICOM-сигнатуры
    DICOM_MAGIC: bytes = b'\x00\x00\x00\x00DICM'

    # S3 / MinIO Configuration
    s3_endpoint_url: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_bucket_encrypted: str = "smdg-encrypted"
    s3_bucket_uploads: str = "smdg-uploads"
    s3_bucket_decrypted: str = "smdg-decrypted"
    s3_region: str = "us-east-1"
    s3_use_ssl: bool = False
    s3_enabled: bool = False

    @model_validator(mode="after")
    def validate_deployment_consistency(self) -> "Settings":
        """
        Согласованность DEPLOYMENT_TYPE с критичными флагами.
        Не ломает существующие .env: жёстко проверяем только obviously неверные пары.
        """
        if self.deployment_type == DeploymentType.RUSSIA and self.s3_enabled:
            raise ValueError(
                "Для deployment_type=RUSSIA требуется локальное хранилище: "
                "установите S3_ENABLED=false"
            )
        if self.deployment_type == DeploymentType.SAAS and not self.s3_enabled:
            # SaaS-профиль предполагает объектное хранилище; допускаем только явную конфигурацию S3.
            if not self.dev_mode:
                raise ValueError(
                    "Для deployment_type=SAAS включите S3 (S3_ENABLED=true и учётные данные endpoint/key)."
                )
        return self

    @property
    def is_s3_enabled(self) -> bool:
        """Проверяет, включён ли S3 режим."""
        return self.s3_enabled and bool(self.s3_endpoint_url) and bool(self.s3_access_key)

    # Журналы аудита (JSON по дням: audit_YYYY-MM-DD.log)
    audit_logs_dir: Path = Field(default=Path("audit_logs"))

    # Экспорт аудита (PDF): абсолютный путь к DejaVuSans.ttf (обязательно в slim-контейнере без fonts-dejavu)
    audit_export_pdf_font_path: Optional[str] = Field(
        default=None,
        description=(
            "Путь к файлу шрифта DejaVuSans.ttf для отчётов PDF. Если не задан, ищется в стандартных "
            "каталогах Linux (например /usr/share/fonts/truetype/dejavu/). В Docker без пакета шрифтов "
            "скопируйте TTF в образ и укажите этот путь через переменную AUDIT_EXPORT_PDF_FONT_PATH."
        ),
    )
    # Префикс имени скачиваемого файла (без расширения)
    audit_export_download_prefix: str = "smdg_audit"

    @property
    def audit_retention_days(self) -> int:
        """Срок хранения записей аудита (календарные дни) по профилю развёртывания."""
        return 1095 if is_enabled(Feature.AUDIT_3_YEARS) else 365

    @property
    def billing_enabled(self) -> bool:
        return is_enabled(Feature.BILLING)

    @property
    def white_label_enabled(self) -> bool:
        return is_enabled(Feature.WHITE_LABEL)


settings = Settings()