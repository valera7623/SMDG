import os
import pytest
import asyncio
import time
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from app.core.cleanup import FileCleanupManager


@pytest.fixture
def temp_dir(tmp_path):
    """Создает временную директорию для тестов"""
    return tmp_path


@pytest.fixture
def cleanup_manager(temp_dir):
    """Создает FileCleanupManager для тестов"""
    return FileCleanupManager(temp_dir, ttl_days=30)


def test_cleanup_manager_initialization(cleanup_manager, temp_dir):
    """Тест инициализации FileCleanupManager"""
    assert cleanup_manager.encrypted_dir == temp_dir
    assert cleanup_manager.ttl_days == 30
    assert cleanup_manager.logger is not None

    assert cleanup_manager.retention_policies == {
        '.txt': 30,
        '.pdf': 90,
        '.dcm': 365,
        '.jpg': 180,
        '.age': 30
    }


def test_get_ttl_for_file():
    """Тест получения TTL для разных типов файлов"""
    manager = FileCleanupManager(Path("/test"), ttl_days=30)

    test_cases = [
        ("file.txt", 30),
        ("document.pdf", 90),
        ("image.jpg", 180),
        ("scan.dcm", 365),
        ("encrypted.age", 30),
        ("unknown.xyz", 30),
    ]

    for filename, expected_ttl in test_cases:
        file_path = Path(filename)
        ttl = manager._get_ttl_for_file(file_path)
        assert ttl == expected_ttl, f"Для {filename} ожидалось {expected_ttl}, получено {ttl}"


@pytest.mark.asyncio
async def test_cleanup_old_files_empty_directory(cleanup_manager, temp_dir):
    """Тест очистки пустой директории"""
    result = await cleanup_manager._cleanup_old_files()
    # FIX: функция возвращает dict, не None
    assert result is not None
    assert result["deleted"] == 0
    assert result["errors"] == []


@pytest.mark.asyncio
async def test_cleanup_old_files_with_new_files(cleanup_manager, temp_dir):
    """Тест очистки с новыми файлами (не должны быть удалены)"""
    new_file = temp_dir / "new_file.txt"
    new_file.write_text("new content")

    current_time = time.time()
    os.utime(new_file, (current_time, current_time))

    await cleanup_manager._cleanup_old_files()

    assert new_file.exists()


@pytest.mark.asyncio
async def test_cleanup_old_files_with_old_files(cleanup_manager, temp_dir):
    """Тест очистки со старыми файлами (должны быть удалены)"""
    old_file = temp_dir / "old_file.txt"
    old_file.write_text("old content")

    old_time = time.time() - (40 * 24 * 3600)
    os.utime(old_file, (old_time, old_time))

    with patch.object(cleanup_manager.logger, 'info') as mock_info:
        with patch.object(cleanup_manager.logger, 'error') as mock_error:
            await cleanup_manager._cleanup_old_files()

            assert not old_file.exists()
            assert mock_info.called


@pytest.mark.asyncio
async def test_cleanup_old_files_error_on_delete(cleanup_manager, temp_dir):
    """Тест ошибки при удалении файла"""
    old_file = temp_dir / "old_file.txt"
    old_file.write_text("old content")

    old_time = time.time() - (40 * 24 * 3600)
    os.utime(old_file, (old_time, old_time))

    # FIX: cleanup.py использует file_path.unlink(), а не os.remove()
    # Патчим unlink на уровне Path
    with patch.object(Path, "unlink", side_effect=PermissionError("Permission denied")):
        with patch.object(cleanup_manager.logger, 'error') as mock_error:
            await cleanup_manager._cleanup_old_files()

            # unlink замокан — файл физически не удалён
            assert old_file.exists()
            mock_error.assert_called()


@pytest.mark.asyncio
async def test_cleanup_old_files_different_file_types(cleanup_manager, temp_dir):
    """Тест очистки файлов разных типов"""
    files = [
        ("old.txt", 40, True),
        ("new.txt", 20, False),
        ("old.pdf", 100, True),
        ("new.pdf", 50, False),
        ("old.jpg", 200, True),
        ("new.jpg", 100, False),
        ("old.dcm", 400, True),
        ("new.dcm", 200, False),
    ]

    for filename, age_days, should_delete in files:
        file_path = temp_dir / filename
        file_path.write_text("content")

        old_time = time.time() - (age_days * 24 * 3600)
        os.utime(file_path, (old_time, old_time))

    await cleanup_manager._cleanup_old_files()

    for filename, age_days, should_delete in files:
        file_path = temp_dir / filename
        if should_delete:
            assert not file_path.exists(), f"{filename} должен был быть удален"
        else:
            assert file_path.exists(), f"{filename} не должен был быть удален"


@pytest.mark.asyncio
async def test_start_cleanup_task(cleanup_manager):
    """Тест запуска задачи очистки через APScheduler"""
    # FIX: start_cleanup_task использует APScheduler, не while-loop
    # Мокаем scheduler чтобы не запускать реальный
    mock_scheduler = MagicMock()
    mock_scheduler.add_job = MagicMock()
    mock_scheduler.start = MagicMock()
    cleanup_manager.scheduler = mock_scheduler

    await cleanup_manager.start_cleanup_task()

    # Проверяем что job был зарегистрирован
    mock_scheduler.add_job.assert_called_once()
    call_kwargs = mock_scheduler.add_job.call_args

    # Первый позиционный аргумент — функция очистки
    assert call_kwargs[0][0] == cleanup_manager._cleanup_old_files

    # Проверяем что scheduler был запущен
    mock_scheduler.start.assert_called_once()

    # Проверяем флаг
    assert cleanup_manager._started is True


@pytest.mark.asyncio
async def test_start_cleanup_task_idempotent(cleanup_manager):
    """Повторный вызов start_cleanup_task не запускает scheduler дважды"""
    mock_scheduler = MagicMock()
    cleanup_manager.scheduler = mock_scheduler
    cleanup_manager._started = True  # Симулируем уже запущенный

    await cleanup_manager.start_cleanup_task()

    # scheduler.start не должен вызываться повторно
    mock_scheduler.start.assert_not_called()
    mock_scheduler.add_job.assert_not_called()


@pytest.mark.asyncio
async def test_start_cleanup_task_with_error(cleanup_manager):
    """Тест что ошибка в add_job пробрасывается"""
    # FIX: тестируем что ошибка scheduler пробрасывается наружу
    mock_scheduler = MagicMock()
    mock_scheduler.add_job.side_effect = Exception("Scheduler error")
    cleanup_manager.scheduler = mock_scheduler

    with pytest.raises(Exception, match="Scheduler error"):
        await cleanup_manager.start_cleanup_task()


def test_get_cleanup_stats_empty_directory(cleanup_manager, temp_dir):
    """Тест статистики для пустой директории"""
    stats = cleanup_manager.get_cleanup_stats()

    assert stats["total"] == 0
    assert stats["to_delete"] == 0
    assert stats["files"] == []


def test_get_cleanup_stats_with_files(cleanup_manager, temp_dir):
    """Тест статистики с файлами"""
    files = [
        ("new.txt", 10),
        ("old.txt", 40),
        ("new.pdf", 50),
        ("old.pdf", 100),
    ]

    for filename, age_days in files:
        file_path = temp_dir / filename
        file_path.write_text("content")

        old_time = time.time() - (age_days * 24 * 3600)
        os.utime(file_path, (old_time, old_time))

    stats = cleanup_manager.get_cleanup_stats()

    assert stats["total"] == 4
    assert stats["to_delete"] == 2
    assert len(stats["files"]) == 2

    for file_info in stats["files"]:
        assert "name" in file_info
        assert "size" in file_info
        assert "age_days" in file_info
        assert "last_access" in file_info
        assert "ttl_days" in file_info
        assert "scheduled_deletion" in file_info

        assert file_info["age_days"] > file_info["ttl_days"]


def test_get_cleanup_stats_directory_not_exists(cleanup_manager):
    """Тест статистики когда директория не существует"""
    non_existent_dir = Path("/non/existent/dir")
    manager = FileCleanupManager(non_existent_dir)

    stats = manager.get_cleanup_stats()

    assert stats["total"] == 0
    assert stats["to_delete"] == 0
    assert stats["files"] == []


if __name__ == "__main__":
    pytest.main([__file__])
