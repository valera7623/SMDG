# app/core/storage_backend.py
"""
Абстракция хранилища для поддержки локальной файловой системы и S3/MinIO.

Позволяет переключаться между режимами без изменения бизнес-логики.
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Dict, Any, List
import logging
from dataclasses import dataclass

from app.core.config import settings
from app.core.timeout import run_with_timeout
from app.core.bulkhead import get_bulkhead

logger = logging.getLogger(__name__)


@dataclass
class ObjectMetadata:
    """Метаданные объекта в хранилище."""
    key: str
    size: int
    last_modified: float  # Unix timestamp
    content_type: Optional[str] = None
    etag: Optional[str] = None


class StorageBackend(ABC):
    """
    Абстрактный интерфейс для хранилища.

    Все методы асинхронные для поддержки как локальных, так и S3 операций.
    """

    @abstractmethod
    async def upload(self, key: str, file_path: Path, content_type: Optional[str] = None) -> ObjectMetadata:
        """
        Загрузить файл в хранилище.

        Args:
            key: Уникальный ключ объекта (путь в S3 или относительный путь для FS)
            file_path: Путь к локальному файлу для загрузки
            content_type: MIME тип содержимого

        Returns:
            ObjectMetadata с информацией о загруженном объекте
        """
        pass

    @abstractmethod
    async def download(self, key: str, destination_path: Path) -> Path:
        """
        Скачать объект из хранилища в локальный файл.

        Args:
            key: Ключ объекта
            destination_path: Куда сохранить скачанный файл

        Returns:
            Path к скачанному файлу
        """
        pass

    @abstractmethod
    async def download_bytes(self, key: str) -> bytes:
        """
        Скачать объект из хранилища как байты.

        Args:
            key: Ключ объекта

        Returns:
            Содержимое объекта
        """
        pass

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """
        Удалить объект из хранилища.

        Args:
            key: Ключ объекта

        Returns:
            True если объект был удалён
        """
        pass

    @abstractmethod
    async def delete_many(self, keys: List[str]) -> Dict[str, Any]:
        """
        Удалить несколько объектов (batch операция).

        Args:
            keys: Список ключей для удаления

        Returns:
            Словарь с результатами операции (deleted_count, errors)
        """
        pass

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """
        Проверить существование объекта.

        Args:
            key: Ключ объекта

        Returns:
            True если объект существует
        """
        pass

    @abstractmethod
    async def stat(self, key: str) -> Optional[ObjectMetadata]:
        """
        Получить метаданные объекта.

        Args:
            key: Ключ объекта

        Returns:
            ObjectMetadata или None если объект не найден
        """
        pass

    @abstractmethod
    async def list_objects(self, prefix: str = "") -> List[ObjectMetadata]:
        """
        Список объектов с заданным префиксом.

        Args:
            prefix: Префикс для фильтрации объектов

        Returns:
            Список метаданных объектов
        """
        pass

    @abstractmethod
    async def get_storage_stats(self) -> Dict[str, Any]:
        """
        Получить статистику хранилища.

        Returns:
            Словарь со статистикой (общий размер, количество объектов и т.д.)
        """
        pass


class LocalStorageBackend(StorageBackend):
    """
    Реализация хранилища на основе локальной файловой системы.

    Обёртка над pathlib для обеспечения совместимости с S3 интерфейсом.
    """

    def __init__(self, base_dir: Path):
        """
        Args:
            base_dir: Базовая директория для хранения файлов
        """
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"📁 LocalStorageBackend инициализирован: {self.base_dir}")

    def _resolve_path(self, key: str) -> Path:
        """Преобразовать ключ в путь файловой системы."""
        # Защита от path traversal атак
        resolved = (self.base_dir / key).resolve()
        if not str(resolved).startswith(str(self.base_dir.resolve())):
            raise ValueError(f"Invalid key: {key} - path traversal detected")
        return resolved

    async def upload(self, key: str, file_path: Path, content_type: Optional[str] = None) -> ObjectMetadata:
        """Копировать файл в хранилище (для локального режима это просто копирование)."""
        dest_path = self._resolve_path(key)
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        import aiofiles
        import shutil

        # Для больших файлов используем shutil, для маленьких можно aiofiles
        if file_path.stat().st_size > 10 * 1024 * 1024:  # > 10MB
            shutil.copy2(file_path, dest_path)
        else:
            async with aiofiles.open(file_path, 'rb') as src:
                content = await src.read()
            async with aiofiles.open(dest_path, 'wb') as dst:
                await dst.write(content)

        stat = dest_path.stat()
        logger.debug(f"📤 Upload: {key} ({stat.st_size} bytes)")

        return ObjectMetadata(
            key=key,
            size=stat.st_size,
            last_modified=stat.st_mtime,
            content_type=content_type
        )

    async def download(self, key: str, destination_path: Path) -> Path:
        """Скопировать файл из хранилища."""
        src_path = self._resolve_path(key)
        if not src_path.exists():
            raise FileNotFoundError(f"Object not found: {key}")

        destination_path.parent.mkdir(parents=True, exist_ok=True)

        import aiofiles
        import shutil

        if src_path.stat().st_size > 10 * 1024 * 1024:  # > 10MB
            shutil.copy2(src_path, destination_path)
        else:
            async with aiofiles.open(src_path, 'rb') as src:
                content = await src.read()
            async with aiofiles.open(destination_path, 'wb') as dst:
                await dst.write(content)

        logger.debug(f"📥 Download: {key} -> {destination_path}")
        return destination_path

    async def download_bytes(self, key: str) -> bytes:
        """Прочитать содержимое файла как байты."""
        file_path = self._resolve_path(key)
        if not file_path.exists():
            raise FileNotFoundError(f"Object not found: {key}")

        import aiofiles
        async with aiofiles.open(file_path, 'rb') as f:
            return await f.read()

    async def delete(self, key: str) -> bool:
        """Удалить файл."""
        file_path = self._resolve_path(key)
        if file_path.exists():
            file_path.unlink()
            logger.debug(f"🗑️ Deleted: {key}")
            return True
        return False

    async def delete_many(self, keys: List[str]) -> Dict[str, Any]:
        """Удалить несколько файлов."""
        deleted = 0
        errors = []

        for key in keys:
            try:
                if await self.delete(key):
                    deleted += 1
            except Exception as e:
                errors.append({"key": key, "error": str(e)})

        return {
            "deleted_count": deleted,
            "errors": errors,
            "total_requested": len(keys)
        }

    async def exists(self, key: str) -> bool:
        """Проверить существование файла."""
        return self._resolve_path(key).exists()

    async def stat(self, key: str) -> Optional[ObjectMetadata]:
        """Получить метаданные файла."""
        file_path = self._resolve_path(key)
        if not file_path.exists():
            return None

        stat = file_path.stat()
        return ObjectMetadata(
            key=key,
            size=stat.st_size,
            last_modified=stat.st_mtime,
        )

    async def list_objects(self, prefix: str = "") -> List[ObjectMetadata]:
        """Список файлов с префиксом."""
        search_dir = self._resolve_path(prefix) if prefix else self.base_dir

        if not search_dir.exists():
            return []

        objects = []
        for item in search_dir.rglob('*') if search_dir.is_dir() else [search_dir]:
            if item.is_file():
                try:
                    stat = item.stat()
                    relative_key = str(item.relative_to(self.base_dir))
                    objects.append(ObjectMetadata(
                        key=relative_key,
                        size=stat.st_size,
                        last_modified=stat.st_mtime,
                    ))
                except Exception as e:
                    logger.warning(f"⚠️ Error listing {item}: {e}")

        return objects

    async def get_storage_stats(self) -> Dict[str, Any]:
        """Статистика хранилища."""
        total_size = 0
        file_count = 0

        if self.base_dir.exists():
            for item in self.base_dir.rglob('*'):
                if item.is_file():
                    try:
                        total_size += item.stat().st_size
                        file_count += 1
                    except Exception:
                        pass

        return {
            "type": "local",
            "base_dir": str(self.base_dir),
            "total_size_bytes": total_size,
            "file_count": file_count,
        }


S3_CIRCUIT_BREAKER_NAME = "s3_storage"


def _s3_circuit_breaker():
    """Ленивый импорт, чтобы модуль не зависел от circuit_breaker на уровне
    импорта (часть тестов инстанцируют S3StorageBackend в изоляции).
    """
    from app.core.circuit_breaker import get_circuit_breaker

    return get_circuit_breaker(S3_CIRCUIT_BREAKER_NAME)


def _s3_protected(method):
    """Декоратор: обернуть метод ``S3StorageBackend`` в Circuit Breaker ``s3_storage``.

    При открытом брейкере метод бросит ``CircuitBreakerOpenError`` —
    вызывающий код обязан маппить её в HTTP 503.
    """
    from functools import wraps

    @wraps(method)
    async def wrapper(self, *args, **kwargs):
        cb = _s3_circuit_breaker()
        bulkhead = get_bulkhead("s3")
        timeout_seconds = settings.S3_UPLOAD_TIMEOUT_SECONDS
        method_name = method.__name__
        if method_name in {"download", "download_bytes"}:
            timeout_seconds = settings.S3_DOWNLOAD_TIMEOUT_SECONDS
        elif method_name in {"exists", "stat", "list_objects", "get_storage_stats", "delete", "delete_many"}:
            timeout_seconds = settings.S3_CONNECTION_TIMEOUT_SECONDS

        return await bulkhead.execute(
            run_with_timeout,
            cb.call(method, self, *args, **kwargs),
            timeout_seconds=float(timeout_seconds),
            error_message=f"S3 {method_name} timeout",
            service="s3",
            operation=method_name,
        )

    return wrapper


class S3StorageBackend(StorageBackend):
    """
    Реализация хранилища на основе S3/MinIO.

    Использует aiobotocore для асинхронной работы с S3-совместимыми хранилищами.

    Все публичные методы обёрнуты в Circuit Breaker ``s3_storage``. Если
    брейкер открыт, попытка ``upload`` / ``download`` / ``stat`` и т.п.
    бросает :class:`app.core.circuit_breaker.CircuitBreakerOpenError` —
    вызывающий код (FastAPI-ручки) обязан маппить её в HTTP 503.
    """

    def __init__(
        self,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str = "us-east-1",
        use_ssl: bool = False,
    ):
        """
        Args:
            endpoint_url: URL endpoint S3 (e.g. http://minio:9000)
            access_key: Access key
            secret_key: Secret key
            bucket: Имя бакета
            region: Регион (для S3)
            use_ssl: Использовать ли HTTPS
        """
        self.endpoint_url = endpoint_url
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket = bucket
        self.region = region
        self.use_ssl = use_ssl
        self._client = None

        logger.info(f"🪣 S3StorageBackend инициализирован: {endpoint_url}/{bucket}")

    async def _get_client(self):
        """Ленивая инициализация S3 клиента."""
        if self._client is None:
            from aiobotocore.session import get_session
            from botocore.config import Config as BotoConfig

            session = get_session()
            protocol = "https" if self.use_ssl else "http"
            endpoint = f"{protocol}://{self.endpoint_url}" if not self.endpoint_url.startswith("http") else self.endpoint_url
            
            self._session = session
            self._client_context = session.create_client(
                's3',
                endpoint_url=endpoint,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name=self.region,
                verify=self.use_ssl,
                config=BotoConfig(
                    connect_timeout=float(settings.S3_CONNECTION_TIMEOUT_SECONDS),
                    read_timeout=float(settings.S3_DOWNLOAD_TIMEOUT_SECONDS),
                ),
            )
            self._client = await self._client_context.__aenter__()
        return self._client

    async def _ensure_bucket_exists(self):
        """Создать бакет если он не существует."""
        client = await self._get_client()
        try:
            await client.head_bucket(Bucket=self.bucket)
        except Exception:
            logger.info(f"🪣 Создание бакета {self.bucket}")
            try:
                await client.create_bucket(Bucket=self.bucket)
                logger.info(f"✅ Бакет {self.bucket} создан")
            except Exception as e:
                logger.error(f"❌ Ошибка создания бакета {self.bucket}: {e}")
                raise

    @_s3_protected
    async def upload(self, key: str, file_path: Path, content_type: Optional[str] = None) -> ObjectMetadata:
        """Загрузить файл в S3."""
        client = await self._get_client()
        await self._ensure_bucket_exists()

        import aiofiles
        async with aiofiles.open(file_path, 'rb') as f:
            content = await f.read()

        put_kwargs = {
            'Bucket': self.bucket,
            'Key': key,
            'Body': content,
        }
        if content_type:
            put_kwargs['ContentType'] = content_type

        response = await client.put_object(**put_kwargs)

        logger.debug(f"📤 S3 Upload: {key} ({len(content)} bytes)")

        return ObjectMetadata(
            key=key,
            size=len(content),
            last_modified=None,  # S3 не возвращает timestamp в put_object
            content_type=content_type,
            etag=response.get('ETag', '').strip('"')
        )

    @_s3_protected
    async def download(self, key: str, destination_path: Path) -> Path:
        """Скачать объект из S3 в локальный файл."""
        client = await self._get_client()

        response = await client.get_object(Bucket=self.bucket, Key=key)
        content = await response['Body'].read()

        destination_path.parent.mkdir(parents=True, exist_ok=True)

        import aiofiles
        async with aiofiles.open(destination_path, 'wb') as f:
            await f.write(content)

        logger.debug(f"📥 S3 Download: {key} -> {destination_path}")
        return destination_path

    @_s3_protected
    async def download_bytes(self, key: str) -> bytes:
        """Скачать объект из S3 как байты."""
        client = await self._get_client()

        response = await client.get_object(Bucket=self.bucket, Key=key)
        return await response['Body'].read()

    @_s3_protected
    async def delete(self, key: str) -> bool:
        """Удалить объект из S3."""
        client = await self._get_client()
        try:
            await client.delete_object(Bucket=self.bucket, Key=key)
            logger.debug(f"🗑️ S3 Deleted: {key}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка удаления {key}: {e}")
            return False

    @_s3_protected
    async def delete_many(self, keys: List[str]) -> Dict[str, Any]:
        """Удалить несколько объектов из S3 (batch операция)."""
        client = await self._get_client()

        # S3 поддерживает максимум 1000 объектов в одном запросе
        deleted = 0
        errors = []

        # Разбиваем на чанки по 1000
        for i in range(0, len(keys), 1000):
            chunk = keys[i:i + 1000]
            delete_keys = [{'Key': k} for k in chunk]

            response = await client.delete_objects(
                Bucket=self.bucket,
                Delete={'Objects': delete_keys, 'Quiet': True}
            )

            # response.get('Deleted') содержит список успешно удалённых
            deleted += len(response.get('Deleted', []))

            # response.get('Errors') содержит ошибки
            for error in response.get('Errors', []):
                errors.append({
                    "key": error.get('Key'),
                    "error": error.get('Message', error.get('Code'))
                })

        logger.debug(f"🗑️ S3 Batch Delete: {deleted} deleted, {len(errors)} errors")

        return {
            "deleted_count": deleted,
            "errors": errors,
            "total_requested": len(keys)
        }

    @_s3_protected
    async def exists(self, key: str) -> bool:
        """Проверить существование объекта в S3."""
        client = await self._get_client()
        try:
            await client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            # Возвращаем False для штатной ситуации "нет такого объекта".
            # Брейкер при этом всё равно получит успех — потому что мы
            # не пробрасываем исключение. Это корректно: "ключа нет" —
            # это не ошибка S3, а штатный ответ.
            return False

    @_s3_protected
    async def stat(self, key: str) -> Optional[ObjectMetadata]:
        """Получить метаданные объекта из S3."""
        client = await self._get_client()
        try:
            response = await client.head_object(Bucket=self.bucket, Key=key)
            return ObjectMetadata(
                key=key,
                size=response.get('ContentLength', 0),
                last_modified=response.get('LastModified', None).timestamp() if response.get('LastModified') else None,
                content_type=response.get('ContentType'),
                etag=response.get('ETag', '').strip('"')
            )
        except Exception:
            return None

    @_s3_protected
    async def list_objects(self, prefix: str = "") -> List[ObjectMetadata]:
        """Список объектов в S3 с префиксом."""
        client = await self._get_client()

        objects = []
        paginator = client.get_paginator('list_objects_v2')

        async for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for item in page.get('Contents', []):
                objects.append(ObjectMetadata(
                    key=item['Key'],
                    size=item['Size'],
                    last_modified=item['LastModified'].timestamp() if item.get('LastModified') else None,
                    etag=item.get('ETag', '').strip('"')
                ))

        return objects

    @_s3_protected
    async def get_storage_stats(self) -> Dict[str, Any]:
        """Статистика S3 хранилища."""
        client = await self._get_client()
        total_size = 0
        file_count = 0

        paginator = client.get_paginator('list_objects_v2')
        async for page in paginator.paginate(Bucket=self.bucket):
            for item in page.get('Contents', []):
                total_size += item.get('Size', 0)
                file_count += 1

        return {
            "type": "s3",
            "endpoint": self.endpoint_url,
            "bucket": self.bucket,
            "total_size_bytes": total_size,
            "file_count": file_count,
        }

    async def close(self):
        """Закрыть S3 клиент."""
        if self._client and self._client_context:
            await self._client_context.__aexit__(None, None, None)
            self._client = None
            self._client_context = None


def get_storage_backend(
    *,
    local_base_dir: Path,
    s3_bucket: str | None = None,
) -> StorageBackend:
    """
    Выбор бэкенда хранилища по feature flags и настройкам.

    Для профиля ``russia`` всегда локальное хранилище (ФЗ-152).
    Обратная совместимость: если в окружении включён S3 с валидными учётными данными,
    используется S3 даже при профиле ``single`` (типичные существующие установки).
    """
    from app.core.config import settings
    from app.core.feature_flags import DeploymentType, Feature, is_enabled

    bucket = s3_bucket or settings.s3_bucket_encrypted

    if settings.deployment_type == DeploymentType.RUSSIA:
        return LocalStorageBackend(base_dir=local_base_dir)

    prefer_s3 = is_enabled(Feature.S3_STORAGE) and settings.is_s3_enabled
    if not prefer_s3 and settings.s3_enabled and settings.is_s3_enabled:
        prefer_s3 = True

    if prefer_s3 and settings.s3_endpoint_url and settings.s3_access_key and settings.s3_secret_key:
        return S3StorageBackend(
            endpoint_url=settings.s3_endpoint_url,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            bucket=bucket,
            region=settings.s3_region,
            use_ssl=settings.s3_use_ssl,
        )

    return LocalStorageBackend(base_dir=local_base_dir)


class StorageFactory:
    """
    Фабрика для создания и выбора бэкенда хранилища.

    Автоматически выбирает бэкенд на основе конфигурации.
    """

    @staticmethod
    def create_backend(
        s3_enabled: bool = False,
        s3_endpoint_url: Optional[str] = None,
        s3_access_key: Optional[str] = None,
        s3_secret_key: Optional[str] = None,
        s3_bucket: str = "smdg-encrypted",
        s3_region: str = "us-east-1",
        s3_use_ssl: bool = False,
        local_base_dir: Optional[Path] = None,
    ) -> StorageBackend:
        """
        Создать подходящий бэкенд хранилища.

        Args:
            s3_enabled: Флаг включения S3 режима
            s3_endpoint_url: URL S3 endpoint
            s3_access_key: Access key
            s3_secret_key: Secret key
            s3_bucket: Имя бакета
            s3_region: Регион
            s3_use_ssl: Использовать HTTPS
            local_base_dir: Базовая директория для локального режима

        Returns:
            StorageBackend экземпляр
        """
        if s3_enabled and s3_endpoint_url and s3_access_key and s3_secret_key:
            logger.info(f"🪣 Инициализация S3StorageBackend: {s3_endpoint_url}/{s3_bucket}")
            return S3StorageBackend(
                endpoint_url=s3_endpoint_url,
                access_key=s3_access_key,
                secret_key=s3_secret_key,
                bucket=s3_bucket,
                region=s3_region,
                use_ssl=s3_use_ssl,
            )
        else:
            if local_base_dir is None:
                raise ValueError("local_base_dir требуется для локального режима")
            logger.info(f"📁 Инициализация LocalStorageBackend: {local_base_dir}")
            return LocalStorageBackend(base_dir=local_base_dir)
