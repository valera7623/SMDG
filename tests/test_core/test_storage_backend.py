# tests/test_core/test_storage_backend.py
"""
Тесты для абстракции StorageBackend (LocalStorageBackend, StorageFactory).

Тесты S3StorageBackend требуют мока aiobotocore и вынесены в отдельный файл.
"""

import pytest
import time
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock
import asyncio

from app.core.storage_backend import (
    StorageBackend,
    LocalStorageBackend,
    StorageFactory,
    ObjectMetadata,
)


# ==================== LocalStorageBackend Tests ====================

@pytest.fixture
def local_backend(tmp_path):
    """Создать LocalStorageBackend с временной директорией."""
    return LocalStorageBackend(base_dir=tmp_path / "storage")


@pytest.fixture
def sample_file(tmp_path):
    """Создать временный файл с содержимым."""
    file_path = tmp_path / "sample.txt"
    file_path.write_text("Hello, World!")
    return file_path


@pytest.fixture
def binary_file(tmp_path):
    """Создать временный бинарный файл."""
    file_path = tmp_path / "binary.bin"
    file_path.write_bytes(b'\x00\x01\x02\x03\x04')
    return file_path


@pytest.mark.asyncio
async def test_upload_creates_file(local_backend, sample_file):
    """upload копирует файл в хранилище."""
    key = "test/sample.txt"
    metadata = await local_backend.upload(key, sample_file)

    assert metadata.key == key
    assert metadata.size == 13  # len("Hello, World!")

    # Файл должен появиться в хранилище
    stored_path = local_backend.base_dir / key
    assert stored_path.exists()
    assert stored_path.read_text() == "Hello, World!"


@pytest.mark.asyncio
async def test_upload_creates_nested_dirs(local_backend, sample_file):
    """upload создаёт вложенные директории."""
    key = "nested/deep/path/file.txt"
    await local_backend.upload(key, sample_file)

    stored_path = local_backend.base_dir / key
    assert stored_path.exists()


@pytest.mark.asyncio
async def test_download_retrieves_file(local_backend, sample_file):
    """download извлекает файл из хранилища."""
    key = "test/sample.txt"
    await local_backend.upload(key, sample_file)

    dest_path = sample_file.parent / "downloaded.txt"
    result = await local_backend.download(key, dest_path)

    assert result == dest_path
    assert dest_path.exists()
    assert dest_path.read_text() == "Hello, World!"


@pytest.mark.asyncio
async def test_download_raises_on_nonexistent(local_backend, tmp_path):
    """download кидает исключение для несуществующего ключа."""
    dest_path = tmp_path / "out.txt"
    with pytest.raises(FileNotFoundError):
        await local_backend.download("nonexistent.txt", dest_path)


@pytest.mark.asyncio
async def test_download_bytes(local_backend, sample_file):
    """download_bytes возвращает содержимое как байты."""
    key = "test/sample.txt"
    await local_backend.upload(key, sample_file)

    content = await local_backend.download_bytes(key)
    assert content == b"Hello, World!"


@pytest.mark.asyncio
async def test_delete_removes_file(local_backend, sample_file):
    """delete удаляет файл."""
    key = "test/sample.txt"
    await local_backend.upload(key, sample_file)

    result = await local_backend.delete(key)
    assert result is True
    assert not (local_backend.base_dir / key).exists()


@pytest.mark.asyncio
async def test_delete_nonexistent_returns_false(local_backend):
    """delete для несуществующего файла возвращает False."""
    result = await local_backend.delete("nonexistent.txt")
    assert result is False


@pytest.mark.asyncio
async def test_delete_many(local_backend, sample_file, tmp_path):
    """delete_many удаляет несколько файлов."""
    keys = []
    for i in range(3):
        key = f"file{i}.txt"
        await local_backend.upload(key, sample_file)
        keys.append(key)

    result = await local_backend.delete_many(keys)

    assert result["deleted_count"] == 3
    assert result["total_requested"] == 3
    assert result["errors"] == []

    for key in keys:
        assert not (local_backend.base_dir / key).exists()


@pytest.mark.asyncio
async def test_exists(local_backend, sample_file):
    """exists проверяет существование файла."""
    key = "test/sample.txt"
    await local_backend.upload(key, sample_file)

    assert await local_backend.exists(key) is True
    assert await local_backend.exists("nonexistent.txt") is False


@pytest.mark.asyncio
async def test_stat(local_backend, sample_file):
    """stat возвращает метаданные."""
    key = "test/sample.txt"
    await local_backend.upload(key, sample_file)

    metadata = await local_backend.stat(key)

    assert metadata is not None
    assert metadata.key == key
    assert metadata.size == 13
    assert isinstance(metadata.last_modified, float)


@pytest.mark.asyncio
async def test_stat_nonexistent(local_backend):
    """stat для несуществующего файла возвращает None."""
    metadata = await local_backend.stat("nonexistent.txt")
    assert metadata is None


@pytest.mark.asyncio
async def test_list_objects(local_backend, sample_file):
    """list_objects возвращает список файлов."""
    keys = ["file1.txt", "file2.txt", "subdir/file3.txt"]
    for key in keys:
        await local_backend.upload(key, sample_file)

    objects = await local_backend.list_objects()

    assert len(objects) == 3
    object_keys = [obj.key for obj in objects]
    for key in keys:
        assert key in object_keys


@pytest.mark.asyncio
async def test_list_objects_with_prefix(local_backend, sample_file):
    """list_objects с префиксом фильтрует файлы."""
    await local_backend.upload("docs/report.pdf", sample_file)
    await local_backend.upload("docs/invoice.pdf", sample_file)
    await local_backend.upload("images/photo.jpg", sample_file)

    objects = await local_backend.list_objects(prefix="docs/")

    assert len(objects) == 2
    for obj in objects:
        assert obj.key.startswith("docs/")


@pytest.mark.asyncio
async def test_list_objects_empty_prefix(local_backend, sample_file):
    """list_objects с пустым префиксом возвращает все файлы."""
    await local_backend.upload("a.txt", sample_file)
    await local_backend.upload("b.txt", sample_file)

    objects = await local_backend.list_objects("")
    assert len(objects) == 2


@pytest.mark.asyncio
async def test_get_storage_stats(local_backend, sample_file):
    """get_storage_stats возвращает корректную статистику."""
    await local_backend.upload("file1.txt", sample_file)
    await local_backend.upload("file2.txt", sample_file)

    stats = await local_backend.get_storage_stats()

    assert stats["type"] == "local"
    assert stats["file_count"] == 2
    assert stats["total_size_bytes"] == 26  # 13 * 2
    assert "base_dir" in stats


@pytest.mark.asyncio
async def test_prevent_path_traversal(local_backend, sample_file):
    """upload предотвращает path traversal атаки."""
    with pytest.raises(ValueError, match="path traversal"):
        await local_backend.upload("../../../etc/passwd", sample_file)


# ==================== StorageFactory Tests ====================

def test_factory_creates_local_backend(tmp_path):
    """Фабрика создаёт LocalStorageBackend когда S3 выключен."""
    backend = StorageFactory.create_backend(
        s3_enabled=False,
        local_base_dir=tmp_path / "storage"
    )

    assert isinstance(backend, LocalStorageBackend)


def test_factory_raises_without_local_dir():
    """Фабрика кидает ошибку без local_base_dir."""
    with pytest.raises(ValueError, match="local_base_dir требуется"):
        StorageFactory.create_backend(
            s3_enabled=False,
            local_base_dir=None
        )


def test_factory_creates_s3_backend():
    """Фабрика создаёт S3StorageBackend когда S3 включён."""
    from app.core.storage_backend import S3StorageBackend

    backend = StorageFactory.create_backend(
        s3_enabled=True,
        s3_endpoint_url="http://minio:9000",
        s3_access_key="test_access_key",
        s3_secret_key="test_secret_key",
        s3_bucket="test-bucket",
        local_base_dir=Path("/tmp/fallback"),
    )

    assert isinstance(backend, S3StorageBackend)
    assert backend.endpoint_url == "http://minio:9000"
    assert backend.bucket == "test-bucket"


def test_factory_fallback_to_local_when_s3_incomplete():
    """Фабрика использует LocalStorageBackend когда S3 настройки неполные."""
    from pathlib import Path
    tmp_path = Path("/tmp/test_storage_factory")
    tmp_path.mkdir(exist_ok=True)

    backend = StorageFactory.create_backend(
        s3_enabled=True,
        s3_endpoint_url=None,  # Отсутствует endpoint
        s3_access_key="test_key",
        s3_secret_key="test_secret",
        local_base_dir=tmp_path,
    )

    assert isinstance(backend, LocalStorageBackend)


# ==================== ObjectMetadata Tests ====================

def test_object_metadata_creation():
    """Создание метаданных."""
    metadata = ObjectMetadata(
        key="test/file.txt",
        size=100,
        last_modified=1234567890.0,
        content_type="text/plain",
        etag="abc123"
    )

    assert metadata.key == "test/file.txt"
    assert metadata.size == 100
    assert metadata.content_type == "text/plain"
    assert metadata.etag == "abc123"


def test_object_metadata_optional_fields():
    """Метаданные с опциональными полями."""
    metadata = ObjectMetadata(
        key="test/file.txt",
        size=100,
        last_modified=1234567890.0
    )

    assert metadata.content_type is None
    assert metadata.etag is None


if __name__ == "__main__":
    pytest.main([__file__])
