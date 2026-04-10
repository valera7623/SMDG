# tests/test_core/test_storage_backend_s3.py
"""
Интеграционные тесты для S3StorageBackend с использованием moto (mock S3).

Тесты проверяют что S3StorageBackend работает корректно с S3 API.
"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

from app.core.storage_backend import S3StorageBackend, StorageFactory, ObjectMetadata


@pytest.fixture
def sample_file(tmp_path):
    """Создать временный файл с содержимым."""
    file_path = tmp_path / "sample.txt"
    file_path.write_text("Hello, S3 World!")
    return file_path


@pytest.fixture
def s3_backend():
    """Создать S3StorageBackend с тестовыми параметрами."""
    return S3StorageBackend(
        endpoint_url="http://localhost:9000",
        access_key="test_access_key",
        secret_key="test_secret_key",
        bucket="test-bucket",
        region="us-east-1",
        use_ssl=False,
    )


# ==================== StorageFactory Tests for S3 ====================

def test_factory_creates_s3_backend_when_enabled(tmp_path):
    """Фабрика создаёт S3StorageBackend когда S3 включён."""
    backend = StorageFactory.create_backend(
        s3_enabled=True,
        s3_endpoint_url="http://minio:9000",
        s3_access_key="test_key",
        s3_secret_key="test_secret",
        s3_bucket="test-bucket",
        local_base_dir=tmp_path,
    )

    assert isinstance(backend, S3StorageBackend)
    assert backend.bucket == "test-bucket"
    assert backend.endpoint_url == "http://minio:9000"


def test_factory_creates_local_backend_when_s3_disabled(tmp_path):
    """Фабрика создаёт LocalStorageBackend когда S3 выключен."""
    from app.core.storage_backend import LocalStorageBackend

    backend = StorageFactory.create_backend(
        s3_enabled=False,
        local_base_dir=tmp_path,
    )

    assert isinstance(backend, LocalStorageBackend)


def test_factory_falls_back_to_local_with_partial_s3_config(tmp_path):
    """Фабрика использует LocalStorageBackend когда S3 конфиг неполный."""
    from app.core.storage_backend import LocalStorageBackend

    # Нет access_key
    backend = StorageFactory.create_backend(
        s3_enabled=True,
        s3_endpoint_url="http://minio:9000",
        s3_access_key=None,  # Отсутствует
        s3_secret_key="test_secret",
        local_base_dir=tmp_path,
    )

    assert isinstance(backend, LocalStorageBackend)


# ==================== S3StorageBackend Unit Tests ====================

class TestS3StorageBackendInit:
    """Тесты инициализации S3StorageBackend."""

    def test_init_sets_properties(self):
        """Инициализация устанавливает свойства."""
        backend = S3StorageBackend(
            endpoint_url="http://minio:9000",
            access_key="ak",
            secret_key="sk",
            bucket="my-bucket",
            region="eu-west-1",
            use_ssl=True,
        )

        assert backend.endpoint_url == "http://minio:9000"
        assert backend.access_key == "ak"
        assert backend.secret_key == "sk"
        assert backend.bucket == "my-bucket"
        assert backend.region == "eu-west-1"
        assert backend.use_ssl is True
        assert backend._client is None


class TestS3StorageBackendAsync:
    """Асинхронные тесты S3StorageBackend с моками."""

    @pytest.mark.asyncio
    async def test_upload_calls_put_object(self, s3_backend, sample_file, tmp_path):
        """upload вызывает put_object."""
        mock_client = AsyncMock()
        mock_client.put_object.return_value = {"ETag": '"abc123"'}

        with patch.object(s3_backend, '_get_client', return_value=mock_client):
            with patch.object(s3_backend, '_ensure_bucket_exists', return_value=None):
                metadata = await s3_backend.upload("test.txt", sample_file)

        mock_client.put_object.assert_called_once()
        call_kwargs = mock_client.put_object.call_args[1]
        assert call_kwargs['Bucket'] == 'test-bucket'
        assert call_kwargs['Key'] == 'test.txt'
        assert call_kwargs['Body'] == b"Hello, S3 World!"

        assert metadata.key == "test.txt"
        assert metadata.size == 16  # len("Hello, S3 World!")

    @pytest.mark.asyncio
    async def test_download_calls_get_object(self, s3_backend, tmp_path):
        """download вызывает get_object."""
        mock_body = AsyncMock()
        mock_body.read.return_value = b"downloaded content"

        mock_response = {'Body': mock_body}
        mock_client = AsyncMock()
        mock_client.get_object.return_value = mock_response

        dest_path = tmp_path / "downloaded.txt"

        with patch.object(s3_backend, '_get_client', return_value=mock_client):
            result = await s3_backend.download("test.txt", dest_path)

        mock_client.get_object.assert_called_once_with(
            Bucket='test-bucket', Key='test.txt'
        )

        assert result == dest_path
        assert dest_path.read_bytes() == b"downloaded content"

    @pytest.mark.asyncio
    async def test_download_bytes_returns_content(self, s3_backend):
        """download_bytes возвращает содержимое."""
        mock_body = AsyncMock()
        mock_body.read.return_value = b"binary content"

        mock_response = {'Body': mock_body}
        mock_client = AsyncMock()
        mock_client.get_object.return_value = mock_response

        with patch.object(s3_backend, '_get_client', return_value=mock_client):
            content = await s3_backend.download_bytes("test.bin")

        assert content == b"binary content"

    @pytest.mark.asyncio
    async def test_delete_calls_delete_object(self, s3_backend):
        """delete вызывает delete_object."""
        mock_client = AsyncMock()
        mock_client.delete_object.return_value = {}

        with patch.object(s3_backend, '_get_client', return_value=mock_client):
            result = await s3_backend.delete("test.txt")

        mock_client.delete_object.assert_called_once_with(
            Bucket='test-bucket', Key='test.txt'
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_many_splits_into_chunks(self, s3_backend):
        """delete_many разбивает на чанки по 1000."""
        mock_client = AsyncMock()
        mock_client.delete_objects.return_value = {
            'Deleted': [{'Key': 'dummy'}],
            'Errors': []
        }

        keys = [f"file{i}.txt" for i in range(1500)]

        with patch.object(s3_backend, '_get_client', return_value=mock_client):
            result = await s3_backend.delete_many(keys)

        # Должно быть 2 вызова (1500 / 1000 = 2 чанка)
        assert mock_client.delete_objects.call_count == 2
        # Каждый вызов возвращает 1 deleted (mock)
        assert result["deleted_count"] == 2
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_exists_returns_true_on_head_object(self, s3_backend):
        """exists возвращает True если head_object успешен."""
        mock_client = AsyncMock()
        mock_client.head_object.return_value = {}

        with patch.object(s3_backend, '_get_client', return_value=mock_client):
            result = await s3_backend.exists("test.txt")

        assert result is True
        mock_client.head_object.assert_called_once_with(
            Bucket='test-bucket', Key='test.txt'
        )

    @pytest.mark.asyncio
    async def test_exists_returns_false_on_error(self, s3_backend):
        """exists возвращает False если head_object падает."""
        mock_client = AsyncMock()
        mock_client.head_object.side_effect = Exception("Not Found")

        with patch.object(s3_backend, '_get_client', return_value=mock_client):
            result = await s3_backend.exists("test.txt")

        assert result is False

    @pytest.mark.asyncio
    async def test_stat_returns_metadata(self, s3_backend):
        """stat возвращает метаданные."""
        from datetime import datetime, timezone

        mock_client = AsyncMock()
        mock_client.head_object.return_value = {
            'ContentLength': 1024,
            'LastModified': datetime(2024, 1, 1, tzinfo=timezone.utc),
            'ContentType': 'text/plain',
            'ETag': '"abc123"',
        }

        with patch.object(s3_backend, '_get_client', return_value=mock_client):
            metadata = await s3_backend.stat("test.txt")

        assert metadata is not None
        assert metadata.key == "test.txt"
        assert metadata.size == 1024
        assert metadata.content_type == "text/plain"
        assert metadata.etag == "abc123"

    @pytest.mark.asyncio
    async def test_stat_returns_none_on_error(self, s3_backend):
        """stat возвращает None если объект не найден."""
        mock_client = AsyncMock()
        mock_client.head_object.side_effect = Exception("Not Found")

        with patch.object(s3_backend, '_get_client', return_value=mock_client):
            metadata = await s3_backend.stat("test.txt")

        assert metadata is None

    @pytest.mark.asyncio
    async def test_list_objects_returns_list(self, s3_backend):
        """list_objects возвращает список объектов."""
        from datetime import datetime, timezone

        # Создаём async generator для paginator
        async def mock_paginate(*args, **kwargs):
            yield {
                'Contents': [
                    {
                        'Key': 'file1.txt',
                        'Size': 100,
                        'LastModified': datetime(2024, 1, 1, tzinfo=timezone.utc),
                        'ETag': '"etag1"',
                    },
                    {
                        'Key': 'file2.txt',
                        'Size': 200,
                        'LastModified': datetime(2024, 1, 2, tzinfo=timezone.utc),
                        'ETag': '"etag2"',
                    },
                ]
            }

        mock_paginator = type('MockPaginator', (), {'paginate': mock_paginate})()

        mock_client = AsyncMock()
        mock_client.get_paginator = MagicMock(return_value=mock_paginator)

        with patch.object(s3_backend, '_get_client', return_value=mock_client):
            objects = await s3_backend.list_objects(prefix="test/")

        assert len(objects) == 2
        assert objects[0].key == "file1.txt"
        assert objects[0].size == 100
        assert objects[1].key == "file2.txt"
        assert objects[1].size == 200

    @pytest.mark.asyncio
    async def test_get_storage_stats_returns_dict(self, s3_backend):
        """get_storage_stats возвращает словарь со статистикой."""
        # Создаём async generator для paginator
        async def mock_paginate(*args, **kwargs):
            yield {
                'Contents': [
                    {'Key': 'f1.txt', 'Size': 100},
                    {'Key': 'f2.txt', 'Size': 200},
                ]
            }

        mock_paginator = type('MockPaginator', (), {'paginate': mock_paginate})()

        mock_client = AsyncMock()
        mock_client.get_paginator = MagicMock(return_value=mock_paginator)

        with patch.object(s3_backend, '_get_client', return_value=mock_client):
            stats = await s3_backend.get_storage_stats()

        assert stats["type"] == "s3"
        assert stats["bucket"] == "test-bucket"
        assert stats["total_size_bytes"] == 300
        assert stats["file_count"] == 2


# ==================== ObjectMetadata Tests ====================

class TestObjectMetadata:
    """Тесты ObjectMetadata."""

    def test_create_metadata_with_all_fields(self):
        """Создание метаданных со всеми полями."""
        metadata = ObjectMetadata(
            key="test/file.txt",
            size=1024,
            last_modified=1704067200.0,
            content_type="text/plain",
            etag="abc123"
        )

        assert metadata.key == "test/file.txt"
        assert metadata.size == 1024
        assert metadata.last_modified == 1704067200.0
        assert metadata.content_type == "text/plain"
        assert metadata.etag == "abc123"

    def test_create_metadata_minimal_fields(self):
        """Создание метаданных с минимальными полями."""
        metadata = ObjectMetadata(
            key="test.txt",
            size=0,
            last_modified=0.0
        )

        assert metadata.key == "test.txt"
        assert metadata.size == 0
        assert metadata.content_type is None
        assert metadata.etag is None


if __name__ == "__main__":
    pytest.main([__file__])
