# tests/test_core/test_storage.py
"""
Тесты для FileStorageManager (app/core/storage.py)
"""

import os
import pytest
import time
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock
import asyncio
from datetime import datetime, timezone

from app.core.storage import FileStorageManager


@pytest.fixture
def temp_storage_dir(tmp_path):
    """Временная директория decrypted"""
    dir_path = tmp_path / "decrypted"
    dir_path.mkdir()
    yield dir_path


@pytest.fixture
def storage_manager(temp_storage_dir):
    """Менеджер с TTL=5 сек для быстрых тестов"""
    manager = FileStorageManager(storage_dir=temp_storage_dir, ttl_seconds=5)
    yield manager


@pytest.fixture
def frozen_time():
    """Фиксированное время"""
    with patch("time.time") as mock_time:
        mock_time.return_value = 1000.0
        yield mock_time


def test_initialization_creates_dir_and_cleans_old(temp_storage_dir):
    """Инициализация создаёт директорию и чистит старые файлы"""
    old_file = temp_storage_dir / "old.txt"
    old_file.write_text("old")

    # Делаем mtime старше TTL=5 сек
    old_mtime = time.time() - 10
    os.utime(old_file, times=(old_mtime, old_mtime))

    new_file = temp_storage_dir / "new.txt"
    new_file.write_text("new")

    manager = FileStorageManager(temp_storage_dir, ttl_seconds=5)

    assert manager.storage_dir == temp_storage_dir
    assert manager.ttl == 5
    assert manager.files == {}
    assert not old_file.exists()  # старый удалён
    assert new_file.exists()      # новый остался


def test_save_file_adds_to_dict_and_schedules(storage_manager, temp_storage_dir):
    """save_file добавляет в словарь и планирует удаление"""
    test_file = temp_storage_dir / "test.txt"
    test_file.write_text("content")

    with patch("asyncio.create_task") as mock_create_task:
        storage_manager.save_file(test_file)  # НЕ async!

        assert test_file in storage_manager.files
        assert isinstance(storage_manager.files[test_file], float)

        mock_create_task.assert_called_once()
        task = mock_create_task.call_args[0][0]
        assert "_schedule_file_deletion" in str(task)


def test_save_file_raises_on_nonexistent(storage_manager):
    """save_file кидает исключение, если файла нет"""
    nonexistent = Path("does_not_exist.txt")
    with pytest.raises(FileNotFoundError):
        storage_manager.save_file(nonexistent)


@pytest.mark.asyncio
async def test_schedule_file_deletion_removes_after_ttl(storage_manager, temp_storage_dir):
    """_schedule_file_deletion удаляет файл после TTL"""
    test_file = temp_storage_dir / "ttl.txt"
    test_file.write_text("ttl")
    storage_manager.files[test_file] = time.time() - 1  # почти истёк

    with patch("asyncio.sleep", AsyncMock()) as mock_sleep:
        await storage_manager._schedule_file_deletion(test_file)

        mock_sleep.assert_called_once_with(5)  # TTL=5

        # Симулируем истечение
        assert not test_file.exists()
        assert test_file not in storage_manager.files


@pytest.mark.asyncio
async def test_cleanup_async_removes_expired(storage_manager, temp_storage_dir, frozen_time):
    """_cleanup_old_files_async удаляет просроченные"""
    old_file = temp_storage_dir / "old.txt"
    old_file.write_text("old")
    storage_manager.files[old_file] = 990.0  # старше TTL=5

    new_file = temp_storage_dir / "new.txt"
    new_file.write_text("new")
    storage_manager.files[new_file] = 998.0  # свежий

    frozen_time.return_value = 1005.0  # old истёк, new нет

    await storage_manager._cleanup_old_files_async()

    assert not old_file.exists()
    assert old_file not in storage_manager.files
    assert new_file.exists()
    assert new_file in storage_manager.files


def test_force_cleanup_deletes_all_and_clears_dict(storage_manager, temp_storage_dir):
    """force_cleanup удаляет все файлы"""
    files = []
    for i in range(3):
        f = temp_storage_dir / f"file{i}.txt"
        f.write_text(f"data{i}")
        storage_manager.files[f] = time.time()
        files.append(f)

    result = storage_manager.force_cleanup()

    assert result["deleted"] == 3
    assert not any(f.exists() for f in files)
    assert len(storage_manager.files) == 0
    assert "errors" not in result


def test_force_cleanup_handles_errors(storage_manager, temp_storage_dir):
    """force_cleanup собирает ошибки"""
    test_file = temp_storage_dir / "err.txt"
    test_file.write_text("err")
    storage_manager.files[test_file] = time.time()

    with patch.object(Path, "unlink", side_effect=PermissionError("Access denied")):
        result = storage_manager.force_cleanup()

        assert result["deleted"] == 0
        assert "errors" in result
        assert len(result["errors"]) == 1


def test_get_stats_empty(storage_manager):
    """get_stats пустое хранилище"""
    stats = storage_manager.get_stats()
    assert stats["total_files"] == 0
    assert stats["files"] == []
    assert stats["ttl_seconds"] == 5


def test_get_stats_with_files(storage_manager, temp_storage_dir, frozen_time):
    """get_stats с файлами"""
    test_file = temp_storage_dir / "stats.txt"
    test_file.write_text("data")
    creation_time = 1000.0
    storage_manager.files[test_file] = creation_time

    frozen_time.return_value = 1010.0

    stats = storage_manager.get_stats()

    assert stats["total_files"] == 1
    file_info = stats["files"][0]
    assert file_info["name"] == "stats.txt"
    assert file_info["size"] == 4
    assert file_info["age_seconds"] == pytest.approx(10, abs=0.1)
    assert file_info["time_left_seconds"] == pytest.approx(0, abs=1)
    assert file_info["created"] == datetime.fromtimestamp(1000.0, tz=timezone.utc).isoformat()


@pytest.mark.asyncio
async def test_cleanup_task_runs_periodically(storage_manager):
    """cleanup_task периодически чистит"""
    with patch.object(storage_manager, "_cleanup_old_files_async", AsyncMock()) as mock_cleanup:
        with patch("asyncio.sleep", AsyncMock()) as mock_sleep:
            mock_sleep.side_effect = [None, None, Exception("Stop")]

            with pytest.raises(Exception, match="Stop"):
                await storage_manager.cleanup_task()

            assert mock_cleanup.await_count >= 2
            assert mock_sleep.await_count == 3


def test_storage_dir_not_exists_on_cleanup(tmp_path):
    """Очистка, если директория не существует"""
    non_dir = tmp_path / "nonexistent"
    manager = FileStorageManager(non_dir, ttl_seconds=5)

    # Не падает
    manager._cleanup_old_files_sync()
    asyncio.run(manager._cleanup_old_files_async())
    manager.get_stats()  # не падает

if __name__ == "__main__":
    pytest.main([__file__])
