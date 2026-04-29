# app/core/config.py
import os
import socket
import uuid
from pathlib import Path
from typing import List, Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.feature_flags import DeploymentType, Feature, is_enabled


def read_secret(secret_name: str, env_var: str = None, default: str = None) -> str:
    """
    Читает секрет из Docker secret или переменной окружения.
    Приоритет: Docker secret > переменная окружения > default
    """
    # Сначала пробуем переменную окружения (entrypoint уже экспортирует секреты).
    # Это защищает от кейсов, когда /run/secrets/* доступен только root, а
    # приложение работает под non-root пользователем.
    if env_var:
        value = os.getenv(env_var)
        if value:
            return value

    # Пути к Docker secrets
    secret_paths = [
        Path(f"/run/secrets/{secret_name}"),
        Path(f"/run/secrets/smdg_{secret_name}"),  # на случай если есть префикс
    ]
    
    for secret_path in secret_paths:
        if secret_path.exists():
            try:
                with open(secret_path, 'r') as f:
                    return f.read().strip()
            except PermissionError:
                # Не прерываемся: можем взять значение из default ниже.
                continue
    
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

    # === HTTP таймауты ===
    HTTP_REQUEST_TIMEOUT_SECONDS: int = 30
    HTTP_CONNECT_TIMEOUT_SECONDS: int = 5
    HTTP_READ_TIMEOUT_SECONDS: int = 25

    # === HTTP сжатие ответов ===
    COMPRESSION_ENABLED: bool = True
    COMPRESSION_MIN_SIZE_BYTES: int = 500
    COMPRESSION_GZIP_LEVEL: int = 6
    COMPRESSION_BROTLI_QUALITY: int = 6
    COMPRESSION_BROTLI_ENABLED: bool = True
    COMPRESSION_GZIP_ENABLED: bool = True
    COMPRESSIBLE_CONTENT_TYPES: List[str] = [
        "text/plain",
        "text/html",
        "text/css",
        "text/xml",
        "text/javascript",
        "application/json",
        "application/javascript",
        "application/xml",
        "application/xhtml+xml",
        "application/rss+xml",
        "application/atom+xml",
        "application/ld+json",
        "application/manifest+json",
        "application/vnd.api+json",
        "application/dicom+json",
        "image/svg+xml",
    ]

    # === Horizontal scaling / stateless runtime ===
    HORIZONTAL_SCALING_ENABLED: bool = True
    INSTANCE_ID: str = Field(default_factory=lambda: os.getenv("INSTANCE_ID", str(uuid.uuid4())))
    INSTANCE_NAME: str = Field(default_factory=lambda: os.getenv("INSTANCE_NAME", socket.gethostname()))

    # Session storage
    SESSION_TYPE: str = "redis"  # redis | memory | database
    SESSION_REDIS_URL: str = "redis://redis:6379/0"
    SESSION_TTL_SECONDS: int = 3600

    # Distributed cache
    CACHE_TYPE: str = "redis"
    CACHE_REDIS_URL: str = "redis://redis:6379/1"
    CACHE_TTL_SECONDS: int = 300

    # Rate limiting storage (shared across replicas)
    RATE_LIMIT_STORAGE: str = "redis://redis:6379/2"

    # Distributed job queue
    JOB_QUEUE_TYPE: str = "redis"  # redis | rabbitmq | celery
    JOB_QUEUE_REDIS_URL: str = "redis://redis:6379/3"

    # Shared file storage
    FILE_STORAGE: str = "s3"  # s3 | shared_nfs | local
    FILE_STORAGE_S3_BUCKET: str = "smdg-files"

    # Health probes for orchestrators
    HEALTH_CHECK_ENABLED: bool = True
    READINESS_CHECK_ENABLED: bool = True

    # === База данных ===
    DB_QUERY_TIMEOUT_SECONDS: int = 10
    DB_CONNECTION_TIMEOUT_SECONDS: int = 5
    DB_TRANSACTION_TIMEOUT_SECONDS: int = 30
    READ_REPLICAS_ENABLED: bool = False
    DB_REPLICA_URLS: str = ""
    READ_REPLICA_LOAD_BALANCING: str = "round_robin"
    READ_REPLICA_MAX_LAG_BYTES: int = 104857600
    READ_REPLICA_HEALTH_TTL_SECONDS: float = 5.0

    # === Архивация ===
    ARCHIVE_ENABLED: bool = True
    COLD_STORAGE_TYPE: str = "filesystem"  # s3_glacier | minio_cold | filesystem
    COLD_STORAGE_ENDPOINT: str = "http://minio-cold:9000"
    COLD_STORAGE_BUCKET: str = "smdg-archive"
    COLD_STORAGE_ACCESS_KEY: str = ""
    COLD_STORAGE_SECRET_KEY: str = ""

    ARCHIVE_FILE_AGE_DAYS: int = 30
    ARCHIVE_AUDIT_AGE_DAYS: int = 365
    ARCHIVE_DICOM_AGE_DAYS: int = 365
    ARCHIVE_DELETED_USER_AGE_DAYS: int = 30

    ARCHIVE_RETENTION_DAYS: int = 2555
    ARCHIVE_DEEP_RETENTION_DAYS: int = 3650

    ARCHIVE_BATCH_SIZE: int = 100
    ARCHIVE_VERIFY_CHECKSUM: bool = True
    ARCHIVE_ENCRYPT: bool = True
    ARCHIVE_COMPRESS: bool = True

    # === Redis ===
    REDIS_OPERATION_TIMEOUT_SECONDS: int = 3
    REDIS_CONNECTION_TIMEOUT_SECONDS: int = 2

    # === S3/MinIO ===
    S3_UPLOAD_TIMEOUT_SECONDS: int = 60
    S3_DOWNLOAD_TIMEOUT_SECONDS: int = 60
    S3_CONNECTION_TIMEOUT_SECONDS: int = 10

    # === DICOM ===
    DICOM_RENDER_TIMEOUT_SECONDS: int = 60
    DICOM_DOWNLOAD_TIMEOUT_SECONDS: int = 120

    # === Фоновые задачи ===
    BACKGROUND_TASK_TIMEOUT_SECONDS: int = 300

    # === Webhook ===
    WEBHOOK_CALL_TIMEOUT_SECONDS: int = 10

    # === Bulkhead настройки ===
    BULKHEAD_ENABLED: bool = True

    # API Bulkhead
    API_BULKHEAD_MAX_CONCURRENT: int = 100
    API_BULKHEAD_QUEUE_SIZE: int = 200
    API_BULKHEAD_TIMEOUT: int = 30

    # DICOM Bulkhead
    DICOM_BULKHEAD_MAX_CONCURRENT: int = 5
    DICOM_BULKHEAD_QUEUE_SIZE: int = 20
    DICOM_BULKHEAD_TIMEOUT: int = 60

    # Upload Bulkhead
    UPLOAD_BULKHEAD_MAX_CONCURRENT: int = 10
    UPLOAD_BULKHEAD_QUEUE_SIZE: int = 50
    UPLOAD_BULKHEAD_TIMEOUT: int = 120

    # Download Bulkhead
    DOWNLOAD_BULKHEAD_MAX_CONCURRENT: int = 20
    DOWNLOAD_BULKHEAD_QUEUE_SIZE: int = 100
    DOWNLOAD_BULKHEAD_TIMEOUT: int = 60

    # S3 Bulkhead
    S3_BULKHEAD_MAX_CONCURRENT: int = 10
    S3_BULKHEAD_QUEUE_SIZE: int = 50
    S3_BULKHEAD_TIMEOUT: int = 60

    # Audit Export Bulkhead
    AUDIT_EXPORT_BULKHEAD_MAX_CONCURRENT: int = 2
    AUDIT_EXPORT_BULKHEAD_QUEUE_SIZE: int = 5
    AUDIT_EXPORT_BULKHEAD_TIMEOUT: int = 120

    # Webhook Bulkhead
    WEBHOOK_BULKHEAD_MAX_CONCURRENT: int = 5
    WEBHOOK_BULKHEAD_QUEUE_SIZE: int = 100
    WEBHOOK_BULKHEAD_TIMEOUT: int = 10

    # Cleanup Bulkhead
    CLEANUP_BULKHEAD_MAX_CONCURRENT: int = 1
    CLEANUP_BULKHEAD_TIMEOUT: int = 300

    # === Dead Letter Queue ===
    DLQ_ENABLED: bool = True
    DLQ_MAX_RETRIES: int = 5
    DLQ_RETRY_DELAY_SECONDS: int = 60
    DLQ_RETRY_BACKOFF_MULTIPLIER: float = 2.0
    DLQ_CLEANUP_DAYS: int = 30
    DLQ_MAX_MESSAGE_SIZE_BYTES: int = 1024 * 1024

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

    # ──────────────────────────────────────────────────────────────
    # Readiness / Liveness probes
    # ──────────────────────────────────────────────────────────────
    # Максимальное количество параллельных in-flight HTTP-запросов.
    # При превышении readiness probe возвращает 503 (overloaded),
    # и оркестратор (k8s/Docker Swarm) временно перестаёт слать трафик.
    max_concurrent_requests: int = Field(
        default=100,
        alias="MAX_CONCURRENT_REQUESTS",
        description="Порог перегрузки для readiness probe (in-flight запросы).",
    )
    # Таймаут на одну проверку зависимости (БД / Redis / storage) внутри
    # readiness probe. Общая длительность probe < таймаута Docker HEALTHCHECK.
    readiness_check_timeout: float = Field(
        default=2.0,
        alias="READINESS_CHECK_TIMEOUT",
        description="Таймаут одной проверки зависимости в readiness probe (сек).",
    )
    # TTL кэша результатов readiness checks. При частых probe (каждые ~2с)
    # избавляет БД/Redis от постоянной нагрузки `SELECT 1` / `PING`.
    readiness_cache_ttl: float = Field(
        default=1.5,
        alias="READINESS_CACHE_TTL",
        description="Время жизни кэша результатов readiness checks (сек).",
    )

    # ──────────────────────────────────────────────────────────────
    # Circuit Breaker (см. app/core/circuit_breaker.py)
    # ──────────────────────────────────────────────────────────────
    # Порог последовательных ошибок, при достижении которого брейкер
    # переходит CLOSED → OPEN и начинает мгновенно отклонять вызовы.
    circuit_breaker_failure_threshold: int = Field(
        default=5,
        alias="CIRCUIT_BREAKER_FAILURE_THRESHOLD",
        description="Количество подряд идущих ошибок для открытия брейкера.",
    )
    # Сколько секунд держим OPEN перед пробным HALF_OPEN.
    circuit_breaker_recovery_timeout: float = Field(
        default=60.0,
        alias="CIRCUIT_BREAKER_RECOVERY_TIMEOUT",
        description="Секунд в состоянии OPEN перед переходом в HALF_OPEN.",
    )
    # Верхняя граница времени в HALF_OPEN без активности (страховка
    # от «подвисшего» downstream): по истечении вернёмся в OPEN.
    circuit_breaker_half_open_timeout: float = Field(
        default=30.0,
        alias="CIRCUIT_BREAKER_HALF_OPEN_TIMEOUT",
        description="Секунд в HALF_OPEN без активности до возврата в OPEN.",
    )
    # Сколько одновременных пробных вызовов разрешено в HALF_OPEN.
    # Столько же подряд успехов нужно, чтобы вернуться в CLOSED.
    circuit_breaker_half_open_max_calls: int = Field(
        default=3,
        alias="CIRCUIT_BREAKER_HALF_OPEN_MAX_CALLS",
        description="Лимит параллельных проб в HALF_OPEN / число успехов для CLOSED.",
    )

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

    # === CDN (статика через CloudFront / Cloudflare и т.д.) ===
    CDN_ENABLED: bool = False
    CDN_URL: str = ""  # e.g. "https://cdn.smdg.com" (без завершающего слэша)
    CDN_PROVIDER: str = "cloudfront"  # cloudfront | cloudflare | akamai | custom
    # Инвалидация кэша на edge (нужны учётные данные соответствующего провайдера)
    CDN_INVALIDATION_ENABLED: bool = False

    CLOUDFRONT_DISTRIBUTION_ID: str = ""
    CLOUDFRONT_DOMAIN: str = ""
    CLOUDFLARE_ZONE_ID: str = ""
    CLOUDFLARE_API_TOKEN: str = ""
    CLOUDFLARE_DOMAIN: str = ""

    STATIC_URL: str = "/static/"
    STATIC_DIR: Path = Field(default=Path("static"))
    # Публичный base URL API для window.SMDG_CONFIG (пусто = тот же origin)
    API_PUBLIC_URL: str = ""
    STATIC_CACHE_VERSION: str = "v1"
    STATIC_CACHE_TTL: int = 31_536_000  # 1 year (сек) — ориентир для заголовков на origin/CDN
    ASSET_FINGERPRINTING: bool = True
    # Если true и manifest.json нет — при старте сгенерировать копии с хэшем (dev/CI);
    # в проде обычно false и манифест кладут артефактом сборки.
    ASSET_MANIFEST_AUTO_GENERATE: bool = False

    @property
    def static_dir_resolved(self) -> Path:
        """Абсолютный путь к каталогу статики (рабочий каталог процесса)."""
        p = self.STATIC_DIR
        return p.resolve() if p.is_absolute() else (Path.cwd() / p).resolve()


settings = Settings()