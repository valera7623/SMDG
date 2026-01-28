import pytest
import asyncio
import time
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock
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
    
    # Проверяем политики удаления
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
        ("file.txt", 30),      # .txt файл
        ("document.pdf", 90),   # .pdf файл
        ("image.jpg", 180),     # .jpg файл
        ("scan.dcm", 365),      # .dcm файл
        ("encrypted.age", 30),  # .age файл
        ("unknown.xyz", 30),    # Неизвестное расширение
    ]
    
    for filename, expected_ttl in test_cases:
        file_path = Path(filename)
        ttl = manager._get_ttl_for_file(file_path)
        assert ttl == expected_ttl, f"Для {filename} ожидалось {expected_ttl}, получено {ttl}"


@pytest.mark.asyncio
async def test_cleanup_old_files_empty_directory(cleanup_manager, temp_dir):
    """Тест очистки пустой директории"""
    deleted = await cleanup_manager._cleanup_old_files()
    assert deleted is None  # Функция не возвращает значение


@pytest.mark.asyncio
async def test_cleanup_old_files_with_new_files(cleanup_manager, temp_dir):
    """Тест очистки с новыми файлами (не должны быть удалены)"""
    # Создаем "новый" файл
    new_file = temp_dir / "new_file.txt"
    new_file.write_text("new content")
    
    # Устанавливаем время доступа сегодня
    current_time = time.time()
    os.utime(new_file, (current_time, current_time))
    
    # Запускаем очистку
    await cleanup_manager._cleanup_old_files()
    
    # Файл должен остаться
    assert new_file.exists()


@pytest.mark.asyncio
async def test_cleanup_old_files_with_old_files(cleanup_manager, temp_dir):
    """Тест очистки со старыми файлами (должны быть удалены)"""
    # Создаем "старый" файл
    old_file = temp_dir / "old_file.txt"
    old_file.write_text("old content")
    
    # Устанавливаем время доступа 40 дней назад
    old_time = time.time() - (40 * 24 * 3600)
    os.utime(old_file, (old_time, old_time))
    
    # Мокаем logger чтобы проверить логирование
    with patch.object(cleanup_manager.logger, 'info') as mock_info:
        with patch.object(cleanup_manager.logger, 'error') as mock_error:
            # Запускаем очистку
            await cleanup_manager._cleanup_old_files()
            
            # Файл должен быть удален
            assert not old_file.exists()
            
            # Проверяем что было логирование
            assert mock_info.called


@pytest.mark.asyncio
async def test_cleanup_old_files_error_on_delete(cleanup_manager, temp_dir):
    """Тест ошибки при удалении файла"""
    # Создаем "старый" файл
    old_file = temp_dir / "old_file.txt"
    old_file.write_text("old content")
    
    # Устанавливаем время доступа 40 дней назад
    old_time = time.time() - (40 * 24 * 3600)
    os.utime(old_file, (old_time, old_time))
    
    # Мокаем os.remove чтобы вызвать ошибку
    with patch('os.remove') as mock_remove:
        mock_remove.side_effect = PermissionError("Permission denied")
        
        with patch.object(cleanup_manager.logger, 'error') as mock_error:
            # Запускаем очистку
            await cleanup_manager._cleanup_old_files()
            
            # Файл должен остаться (не удален из-за ошибки)
            assert old_file.exists()
            
            # Проверяем что ошибка была залогирована
            mock_error.assert_called()


@pytest.mark.asyncio
async def test_cleanup_old_files_different_file_types(cleanup_manager, temp_dir):
    """Тест очистки файлов разных типов"""
    # Создаем файлы разных типов
    files = [
        ("old.txt", 40, True),      # .txt старше 30 дней - удалить
        ("new.txt", 20, False),     # .txt младше 30 дней - оставить
        ("old.pdf", 100, True),     # .pdf старше 90 дней - удалить
        ("new.pdf", 50, False),     # .pdf младше 90 дней - оставить
        ("old.jpg", 200, True),     # .jpg старше 180 дней - удалить
        ("new.jpg", 100, False),    # .jpg младше 180 дней - оставить
        ("old.dcm", 400, True),     # .dcm старше 365 дней - удалить
        ("new.dcm", 200, False),    # .dcm младше 365 дней - оставить
    ]
    
    for filename, age_days, should_delete in files:
        file_path = temp_dir / filename
        file_path.write_text("content")
        
        # Устанавливаем время доступа
        old_time = time.time() - (age_days * 24 * 3600)
        os.utime(file_path, (old_time, old_time))
    
    # Запускаем очистку
    await cleanup_manager._cleanup_old_files()
    
    # Проверяем результат
    for filename, age_days, should_delete in files:
        file_path = temp_dir / filename
        if should_delete:
            assert not file_path.exists(), f"{filename} должен был быть удален"
        else:
            assert file_path.exists(), f"{filename} не должен был быть удален"


@pytest.mark.asyncio
async def test_start_cleanup_task(cleanup_manager):
    """Тест запуска задачи очистки"""
    with patch.object(cleanup_manager, '_cleanup_old_files') as mock_cleanup:
        with patch('asyncio.sleep') as mock_sleep:
            # Заставляем sleep вызывать исключение после первого вызова чтобы выйти из цикла
            mock_sleep.side_effect = [None, Exception("Test exit")]
            
            # Запускаем задачу
            with pytest.raises(Exception, match="Test exit"):
                await cleanup_manager.start_cleanup_task()
            
            # Проверяем что cleanup был вызван
            assert mock_cleanup.called


@pytest.mark.asyncio
async def test_start_cleanup_task_with_error(cleanup_manager):
    """Тест задачи очистки с ошибкой"""
    with patch.object(cleanup_manager, '_cleanup_old_files') as mock_cleanup:
        mock_cleanup.side_effect = Exception("Cleanup error")
        
        with patch('asyncio.sleep') as mock_sleep:
            # Первый sleep после ошибки, второй вызов Exception чтобы выйти
            mock_sleep.side_effect = [None, Exception("Test exit")]
            
            with patch.object(cleanup_manager.logger, 'error') as mock_error:
                # Запускаем задачу
                with pytest.raises(Exception, match="Test exit"):
                    await cleanup_manager.start_cleanup_task()
                
                # Проверяем что ошибка была залогирована
                mock_error.assert_called()


def test_get_cleanup_stats_empty_directory(cleanup_manager, temp_dir):
    """Тест статистики для пустой директории"""
    stats = cleanup_manager.get_cleanup_stats()
    
    assert stats["total"] == 0
    assert stats["to_delete"] == 0
    assert stats["files"] == []


def test_get_cleanup_stats_with_files(cleanup_manager, temp_dir):
    """Тест статистики с файлами"""
    # Создаем файлы разных возрастов
    files = [
        ("new.txt", 10),    # Новый, не для удаления
        ("old.txt", 40),    # Старый, для удаления
        ("new.pdf", 50),    # Новый PDF
        ("old.pdf", 100),   # Старый PDF, для удаления
    ]
    
    for filename, age_days in files:
        file_path = temp_dir / filename
        file_path.write_text("content")
        
        # Устанавливаем время доступа
        old_time = time.time() - (age_days * 24 * 3600)
        os.utime(file_path, (old_time, old_time))
    
    # Получаем статистику
    stats = cleanup_manager.get_cleanup_stats()
    
    # Проверяем
    assert stats["total"] == 4
    assert stats["to_delete"] == 2  # old.txt и old.pdf
    assert len(stats["files"]) == 2
    
    # Проверяем структуру информации о файлах
    for file_info in stats["files"]:
        assert "name" in file_info
        assert "size" in file_info
        assert "age_days" in file_info
        assert "last_access" in file_info
        assert "ttl_days" in file_info
        assert "scheduled_deletion" in file_info
        
        # Проверяем что age_days > ttl_days (иначе не должно быть в списке)
        assert file_info["age_days"] > file_info["ttl_days"]


def test_get_cleanup_stats_directory_not_exists(cleanup_manager):
    """Тест статистики когда директория не существует"""
    # Создаем менеджер с несуществующей директорией
    non_existent_dir = Path("/non/existent/dir")
    manager = FileCleanupManager(non_existent_dir)
    
    stats = manager.get_cleanup_stats()
    
    assert stats["total"] == 0
    assert stats["to_delete"] == 0
    assert stats["files"] == []


if __name__ == "__main__":
    pytest.main([__file__])
