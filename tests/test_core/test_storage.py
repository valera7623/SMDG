import pytest
import shutil
import os
import asyncio
import time
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
from app.core.storage import FileStorageManager


@pytest.fixture
def temp_dir(tmp_path):
    """Создает временную директорию для тестов"""
    return tmp_path


@pytest.fixture
def storage_manager(temp_dir):
    """Создает FileStorageManager для тестов"""
    return FileStorageManager(temp_dir, ttl_seconds=5)  # 5 секунд для быстрых тестов


def test_storage_manager_initialization(storage_manager, temp_dir):
    """Тест инициализации FileStorageManager"""
    assert storage_manager.storage_dir == temp_dir
    assert storage_manager.ttl == 5
    assert storage_manager.files == {}
    assert temp_dir.exists()


def test_save_file_existing(storage_manager, temp_dir):
    """Тест сохранения существующего файла"""
    test_file = temp_dir / "test.txt"
    test_file.write_text("test content")
    
    # Мокаем asyncio.create_task чтобы избежать фоновых задач в тестах
    with patch('asyncio.create_task') as mock_create_task:
        storage_manager.save_file(test_file)
        
        assert test_file in storage_manager.files
        assert isinstance(storage_manager.files[test_file], float)
        mock_create_task.assert_called_once()


def test_save_file_nonexistent(storage_manager):
    """Тест сохранения несуществующего файла"""
    test_file = Path("nonexistent.txt")
    
    with pytest.raises(FileNotFoundError):
        storage_manager.save_file(test_file)


@pytest.mark.asyncio
async def test_schedule_file_deletion(storage_manager, temp_dir):
    """Тест планирования удаления файла"""
    test_file = temp_dir / "test.txt"
    test_file.write_text("test content")
    
    # Добавляем файл в словарь
    storage_manager.files[test_file] = time.time()
    
    # Мокаем time.sleep чтобы ускорить тест
    with patch('asyncio.sleep') as mock_sleep:
        # Заменяем реальный sleep на мгновенный
        async def instant_sleep(seconds):
            pass
        mock_sleep.side_effect = instant_sleep
        
        # Запускаем задачу удаления
        await storage_manager._schedule_file_deletion(test_file)
        
        # Проверяем что файл удален из словаря
        assert test_file not in storage_manager.files
        mock_sleep.assert_called_once_with(5)  # Должен ждать TTL


@pytest.mark.asyncio
async def test_cleanup_old_files_async(storage_manager, temp_dir):
    """Тест асинхронной очистки старых файлов"""
    # Создаем "старый" файл
    old_file = temp_dir / "old.txt"
    old_file.write_text("old content")
    
    # Добавляем в словарь с временем 10 секунд назад
    storage_manager.files[old_file] = time.time() - 10
    
    # Создаем "новый" файл
    new_file = temp_dir / "new.txt"
    new_file.write_text("new content")
    storage_manager.files[new_file] = time.time() - 2  # 2 секунды назад
    
    # Запускаем очистку
    await storage_manager._cleanup_old_files_async()
    
    # Старый файл должен быть удален из словаря
    assert old_file not in storage_manager.files
    # Новый файл должен остаться
    assert new_file in storage_manager.files


def test_cleanup_old_files_sync(storage_manager, temp_dir):
    """Тест синхронной очистки старых файлов"""
    # Создаем старый файл
    old_file = temp_dir / "old.txt"
    old_file.write_text("old content")
    
    # Устанавливаем время модификации 10 секунд назад
    old_time = time.time() - 10
    os.utime(old_file, (old_time, old_time))
    
    # Запускаем синхронную очистку
    storage_manager._cleanup_old_files_sync()
    
    # Файл должен быть удален
    assert not old_file.exists()


def test_get_stats_empty(storage_manager):
    """Тест получения статистики когда нет файлов"""
    stats = storage_manager.get_stats()
    
    assert stats["total_files"] == 0
    assert stats["ttl_seconds"] == 5
    assert stats["files"] == []


def test_get_stats_with_files(storage_manager, temp_dir):
    """Тест получения статистики с файлами"""
    # Создаем файл
    test_file = temp_dir / "test.txt"
    test_file.write_text("test content")
    
    # Добавляем в словарь
    creation_time = time.time() - 1
    storage_manager.files[test_file] = creation_time
    
    # Получаем статистику
    stats = storage_manager.get_stats()
    
    assert stats["total_files"] == 1
    assert stats["ttl_seconds"] == 5
    assert len(stats["files"]) == 1
    
    file_info = stats["files"][0]
    assert file_info["name"] == "test.txt"
    assert file_info["size"] == len("test content")
    assert file_info["age_seconds"] > 0
    assert file_info["time_left_seconds"] > 0
    assert "created" in file_info


def test_force_cleanup(storage_manager, temp_dir):
    """Тест принудительной очистки"""
    # Создаем несколько файлов
    for i in range(3):
        test_file = temp_dir / f"test{i}.txt"
        test_file.write_text(f"content {i}")
        storage_manager.files[test_file] = time.time()
    
    # Проверяем что файлы существуют
    assert len(list(temp_dir.iterdir())) == 3
    assert len(storage_manager.files) == 3
    
    # Запускаем принудительную очистку
    result = storage_manager.force_cleanup()
    
    # Проверяем результат
    assert result["deleted"] == 3
    assert len(list(temp_dir.iterdir())) == 0
    assert len(storage_manager.files) == 0


def test_force_cleanup_with_errors(storage_manager, temp_dir):
    """Тест принудительной очистки с ошибками"""
    # Мокаем unlink чтобы вызвать ошибку
    with patch.object(Path, 'unlink') as mock_unlink:
        mock_unlink.side_effect = PermissionError("Permission denied")
        
        # Создаем файл
        test_file = temp_dir / "test.txt"
        test_file.write_text("content")
        storage_manager.files[test_file] = time.time()
        
        # Запускаем очистку
        result = storage_manager.force_cleanup()
        
        # Проверяем результат с ошибкой
        assert result["deleted"] == 0
        assert "errors" in result
        assert len(result["errors"]) == 1


@pytest.mark.asyncio
async def test_cleanup_task(storage_manager):
    """Тест фоновой задачи очистки"""
    # Мокаем методы чтобы избежать реального ожидания
    with patch.object(storage_manager, '_cleanup_old_files_async') as mock_cleanup:
        with patch('asyncio.sleep') as mock_sleep:
            # Заставляем sleep вызывать исключение после первого вызова чтобы выйти из цикла
            mock_sleep.side_effect = [None, Exception("Test exit")]
            
            # Запускаем задачу
            with pytest.raises(Exception, match="Test exit"):
                await storage_manager.cleanup_task()
            
            # Проверяем что cleanup был вызван
            mock_cleanup.assert_called()
            mock_sleep.assert_called()


def test_storage_dir_not_exists_on_cleanup(tmp_path):
    """Тест когда директория хранилища не существует при очистке"""
    non_existent_dir = tmp_path / "nonexistent"
    storage = FileStorageManager(non_existent_dir, ttl_seconds=5)
    
    # Удаляем директорию (если была создана)
    if non_existent_dir.exists():
        shutil.rmtree(non_existent_dir)
    
    # Синхронная очистка не должна падать
    storage._cleanup_old_files_sync()
    
    # Асинхронная очистка не должна падать
    asyncio.run(storage._cleanup_old_files_async())
    
    # Получение статистики не должно падать
    stats = storage.get_stats()
    assert stats["total_files"] == 0


def test_file_removed_between_checks(storage_manager, temp_dir):
    """Тест когда файл удален между проверками"""
    test_file = temp_dir / "test.txt"
    test_file.write_text("content")
    
    # Добавляем в словарь
    storage_manager.files[test_file] = time.time()
    
    # Удаляем файл вручную
    test_file.unlink()
    
    # Получаем статистику - не должно быть ошибок
    stats = storage_manager.get_stats()
    assert stats["total_files"] == 1  # Все еще в словаре
    assert len(stats["files"]) == 0  # Но не в списке файлов


if __name__ == "__main__":
    pytest.main([__file__])
