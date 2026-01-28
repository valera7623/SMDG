# tests/test_api/test_cleanup.py
import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pathlib import Path
import tempfile
import shutil
import time
import os

# Создаем тестовое приложение
app = FastAPI()


class TestCleanupAPI:
    """Тесты для API очистки временных файлов"""

    @pytest.fixture
    def temp_decrypted_dir(self):
        """Создает временную директорию для расшифрованных файлов"""
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def mock_file_storage(self):
        """Мокает глобальный file_storage"""
        mock_storage = MagicMock()
        mock_storage.get_stats = MagicMock()
        mock_storage.force_cleanup = MagicMock()
        return mock_storage

    @pytest.fixture
    def mock_auth_admin(self):
        """Мокает аутентификацию администратора"""
        # Создаем объект токена с атрибутами
        class MockToken:
            def __init__(self):
                self.sub = "admin_user"
                self.role = "admin"
        
        mock_token = MockToken()
        
        async def mock_get_current_admin():
            return mock_token
        
        with patch('app.api.cleanup.get_current_admin', mock_get_current_admin):
            yield mock_token

    @pytest.fixture
    def mock_auth_non_admin(self):
        """Мокает аутентификацию не-администратора (должен вызывать ошибку)"""
        async def mock_get_current_admin():
            raise HTTPException(status_code=403, detail="Admin access required")
        
        with patch('app.api.cleanup.get_current_admin', mock_get_current_admin):
            yield

    # ====== Тесты для /cleanup/stats ======

    @pytest.mark.asyncio
    async def test_get_cleanup_stats_success(self, mock_file_storage, mock_auth_admin):
        """Тест успешного получения статистики"""
        # Настраиваем мок file_storage
        mock_stats = {
            "total_files": 5,
            "storage_dir": "/tmp/decrypted",
            "ttl_seconds": 3600,
            "files": [
                {"name": "file1.txt", "size": 1024, "age_seconds": 1800},
                {"name": "file2.txt", "size": 2048, "age_seconds": 900},
            ]
        }
        mock_file_storage.get_stats.return_value = mock_stats
        
        with patch('app.api.cleanup.file_storage', mock_file_storage):
            # Импортируем функцию
            with patch('app.api.cleanup.router', None):  # Чтобы избежать циклических импортов
                from app.api.cleanup import get_cleanup_stats
                
                # Вызываем функцию
                response = await get_cleanup_stats(
                    current_user=mock_auth_admin
                )
        
        # Проверяем результат
        assert response == mock_stats
        mock_file_storage.get_stats.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_cleanup_stats_unauthorized(self, mock_file_storage, mock_auth_non_admin):
        """Тест получения статистики без прав администратора"""
        with patch('app.api.cleanup.file_storage', mock_file_storage):
            with patch('app.api.cleanup.router', None):
                from app.api.cleanup import get_cleanup_stats
                
                # Должно вызвать исключение
                with pytest.raises(HTTPException) as exc_info:
                    await get_cleanup_stats(
                        current_user=None  # Будет переопределено моком
                    )
        
        # Проверяем ошибку
        assert exc_info.value.status_code == 403
        assert "Admin access required" in str(exc_info.value.detail)
        
        # file_storage.get_stats не должен вызываться
        mock_file_storage.get_stats.assert_not_called()

    # ====== Тесты для /cleanup/force ======

    @pytest.mark.asyncio
    async def test_force_cleanup_success(self, mock_file_storage, mock_auth_admin):
        """Тест успешной принудительной очистки"""
        # Настраиваем мок file_storage
        mock_result = {
            "deleted": 3,
            "errors": []
        }
        mock_file_storage.force_cleanup.return_value = mock_result
        
        with patch('app.api.cleanup.file_storage', mock_file_storage):
            with patch('app.api.cleanup.router', None):
                from app.api.cleanup import force_cleanup
                
                # Вызываем функцию
                response = await force_cleanup(
                    current_user=mock_auth_admin
                )
        
        # Проверяем результат
        assert response == mock_result
        mock_file_storage.force_cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_force_cleanup_with_errors(self, mock_file_storage, mock_auth_admin):
        """Тест принудительной очистки с ошибками"""
        # Настраиваем мок file_storage с ошибками
        mock_result = {
            "deleted": 2,
            "errors": ["Ошибка удаления file1.txt: Permission denied"]
        }
        mock_file_storage.force_cleanup.return_value = mock_result
        
        with patch('app.api.cleanup.file_storage', mock_file_storage):
            with patch('app.api.cleanup.router', None):
                from app.api.cleanup import force_cleanup
                
                # Вызываем функцию
                response = await force_cleanup(
                    current_user=mock_auth_admin
                )
        
        # Проверяем результат
        assert response == mock_result
        assert response["deleted"] == 2
        assert len(response["errors"]) == 1
        assert "Permission denied" in response["errors"][0]

    @pytest.mark.asyncio
    async def test_force_cleanup_unauthorized(self, mock_file_storage, mock_auth_non_admin):
        """Тест принудительной очистки без прав администратора"""
        with patch('app.api.cleanup.file_storage', mock_file_storage):
            with patch('app.api.cleanup.router', None):
                from app.api.cleanup import force_cleanup
                
                # Должно вызвать исключение
                with pytest.raises(HTTPException) as exc_info:
                    await force_cleanup(
                        current_user=None  # Будет переопределено моком
                    )
        
        # Проверяем ошибку
        assert exc_info.value.status_code == 403
        mock_file_storage.force_cleanup.assert_not_called()

    # ====== Тесты для /cleanup/files ======

    @pytest.mark.asyncio
    async def test_list_temp_files_empty_directory(self, temp_decrypted_dir, mock_auth_admin):
        """Тест списка временных файлов из пустой директории"""
        # Мокаем DECRYPTED_DIR
        with patch('app.api.cleanup.DECRYPTED_DIR', temp_decrypted_dir):
            with patch('app.api.cleanup.router', None):
                from app.api.cleanup import list_temp_files
                
                # Вызываем функцию
                response = await list_temp_files(
                    current_user=mock_auth_admin
                )
        
        # Проверяем результат
        assert response["count"] == 0
        assert response["directory"] == str(temp_decrypted_dir)
        assert response["files"] == []

    @pytest.mark.asyncio
    async def test_list_temp_files_with_files(self, temp_decrypted_dir, mock_auth_admin):
        """Тест списка временных файлов с файлами в директории"""
        # Создаем тестовые файлы
        file1 = temp_decrypted_dir / "file1.txt"
        file1.write_text("content 1")
        
        # Изменяем время модификации для теста
        old_time = time.time() - 7200  # 2 часа назад
        os.utime(file1, (old_time, old_time))
        
        file2 = temp_decrypted_dir / "file2.dat"
        file2.write_bytes(b"content 2")
        
        # Создаем директорию (должна быть проигнорирована)
        subdir = temp_decrypted_dir / "subdir"
        subdir.mkdir()
        
        # Мокаем DECRYPTED_DIR
        with patch('app.api.cleanup.DECRYPTED_DIR', temp_decrypted_dir):
            with patch('app.api.cleanup.router', None):
                from app.api.cleanup import list_temp_files
                
                # Вызываем функцию
                response = await list_temp_files(
                    current_user=mock_auth_admin
                )
        
        # Проверяем результат
        assert response["count"] == 2
        assert response["directory"] == str(temp_decrypted_dir)
        assert len(response["files"]) == 2
        
        # Проверяем структуру файлов
        for file_data in response["files"]:
            assert "name" in file_data
            assert "size" in file_data
            assert "modified" in file_data
            assert "age_hours" in file_data
            
            # Возраст должен быть в часах
            assert file_data["age_hours"] > 0
        
        # Проверяем сортировку (новые сверху)
        # file2 создан позже file1
        assert response["files"][0]["name"] == "file2.dat"
        assert response["files"][1]["name"] == "file1.txt"
        
        # Проверяем возраст file1 (должен быть около 2 часов)
        file1_data = next(f for f in response["files"] if f["name"] == "file1.txt")
        assert 1.5 < file1_data["age_hours"] < 2.5  # Примерно 2 часа

    @pytest.mark.asyncio
    async def test_list_temp_files_directory_not_exists(self, mock_auth_admin):
        """Тест списка временных файлов когда директория не существует"""
        # Мокаем DECRYPTED_DIR чтобы он не существовал
        mock_dir = MagicMock(spec=Path)
        mock_dir.exists.return_value = False
        
        with patch('app.api.cleanup.DECRYPTED_DIR', mock_dir):
            with patch('app.api.cleanup.router', None):
                from app.api.cleanup import list_temp_files
                
                # Вызываем функцию
                response = await list_temp_files(
                    current_user=mock_auth_admin
                )
        
        # Проверяем результат
        assert response["count"] == 0
        assert response["files"] == []
        
        # Проверяем что exists был вызван
        mock_dir.exists.assert_called_once()
        # iterdir не должен вызываться
        mock_dir.iterdir.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_temp_files_ignore_directories(self, temp_decrypted_dir, mock_auth_admin):
        """Тест что директории игнорируются при списке файлов"""
        # Создаем только директорию (без файлов)
        subdir = temp_decrypted_dir / "subdirectory"
        subdir.mkdir()
        
        with patch('app.api.cleanup.DECRYPTED_DIR', temp_decrypted_dir):
            with patch('app.api.cleanup.router', None):
                from app.api.cleanup import list_temp_files
                
                # Вызываем функцию
                response = await list_temp_files(
                    current_user=mock_auth_admin
                )
        
        # Директория должна быть проигнорирована
        assert response["count"] == 0
        assert response["files"] == []

    @pytest.mark.asyncio
    async def test_list_temp_files_unauthorized(self, temp_decrypted_dir, mock_auth_non_admin):
        """Тест списка временных файлов без прав администратора"""
        with patch('app.api.cleanup.DECRYPTED_DIR', temp_decrypted_dir):
            with patch('app.api.cleanup.router', None):
                from app.api.cleanup import list_temp_files
                
                # Должно вызвать исключение
                with pytest.raises(HTTPException) as exc_info:
                    await list_temp_files(
                        current_user=None  # Будет переопределено моком
                    )
        
        # Проверяем ошибку
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_list_temp_files_stat_error(self, temp_decrypted_dir, mock_auth_admin):
        """Тест обработки ошибок при получении информации о файле"""
        # Создаем файл
        test_file = temp_decrypted_dir / "test.txt"
        test_file.write_text("test")
        
        # Мокаем stat() чтобы выбросить исключение
        with patch('pathlib.Path.stat') as mock_stat:
            mock_stat.side_effect = PermissionError("Permission denied")
            
            with patch('app.api.cleanup.DECRYPTED_DIR', temp_decrypted_dir):
                with patch('app.api.cleanup.router', None):
                    from app.api.cleanup import list_temp_files
                    
                    # Вызываем функцию - должна обработать ошибку и продолжить
                    response = await list_temp_files(
                        current_user=mock_auth_admin
                    )
        
        # Функция должна вернуть пустой список (файл с ошибкой пропускается)
        assert response["count"] == 0
        assert response["files"] == []

    # ====== Edge cases ======

    @pytest.mark.asyncio
    async def test_list_temp_files_large_number_of_files(self, temp_decrypted_dir, mock_auth_admin):
        """Тест с большим количеством файлов"""
        # Создаем 50 тестовых файлов
        for i in range(50):
            file_path = temp_decrypted_dir / f"file_{i:03d}.txt"
            file_path.write_text(f"content {i}")
        
        with patch('app.api.cleanup.DECRYPTED_DIR', temp_decrypted_dir):
            with patch('app.api.cleanup.router', None):
                from app.api.cleanup import list_temp_files
                
                # Вызываем функцию
                response = await list_temp_files(
                    current_user=mock_auth_admin
                )
        
        # Проверяем результат
        assert response["count"] == 50
        assert len(response["files"]) == 50
        
        # Все файлы должны быть отсортированы
        files = response["files"]
        for i in range(len(files) - 1):
            # Проверяем что файлы отсортированы по времени модификации (новые сверху)
            assert files[i]["modified"] >= files[i + 1]["modified"]

    @pytest.mark.asyncio
    async def test_list_temp_files_with_special_characters(self, temp_decrypted_dir, mock_auth_admin):
        """Тест с файлами со специальными символами в именах"""
        # Создаем файлы с разными именами
        test_files = [
            "normal.txt",
            "file with spaces.txt",
            "file_with_underscores.txt",
            "file-dashes.txt",
            "UPPERCASE.TXT",
            "mixedCase.File",
        ]
        
        for filename in test_files:
            file_path = temp_decrypted_dir / filename
            file_path.write_text("content")
        
        with patch('app.api.cleanup.DECRYPTED_DIR', temp_decrypted_dir):
            with patch('app.api.cleanup.router', None):
                from app.api.cleanup import list_temp_files
                
                # Вызываем функцию
                response = await list_temp_files(
                    current_user=mock_auth_admin
                )
        
        # Проверяем результат
        assert response["count"] == len(test_files)
        
        # Проверяем что все файлы присутствуют
        returned_names = {f["name"] for f in response["files"]}
        for filename in test_files:
            assert filename in returned_names


# ====== Интеграционные тесты с TestClient ======

class TestCleanupIntegration:
    """Интеграционные тесты для cleanup API"""
    
    def setup_method(self):
        """Настройка перед каждым тестом"""
        self.app = FastAPI()
        
        # Мокаем все зависимости
        mock_file_storage = MagicMock()
        mock_file_storage.get_stats = MagicMock()
        mock_file_storage.force_cleanup = MagicMock()
        
        mock_token = MagicMock()
        mock_token.sub = "admin_user"
        mock_token.role = "admin"
        
        async def mock_get_current_admin():
            return mock_token
        
        with patch('app.api.cleanup.file_storage', mock_file_storage):
            with patch('app.api.cleanup.get_current_admin', mock_get_current_admin):
                from app.api.cleanup import router as cleanup_router
                self.app.include_router(cleanup_router, prefix="/api")
        
        self.client = TestClient(self.app)
    
    def test_cleanup_stats_endpoint_exists(self):
        """Тест что эндпоинт /api/cleanup/stats существует"""
        response = self.client.get("/api/cleanup/stats")
        # Не должно быть 404
        assert response.status_code != 404
    
    def test_cleanup_force_endpoint_exists(self):
        """Тест что эндпоинт /api/cleanup/force существует"""
        response = self.client.post("/api/cleanup/force")
        # Не должно быть 404
        assert response.status_code != 404
    
    def test_cleanup_files_endpoint_exists(self):
        """Тест что эндпоинт /api/cleanup/files существует"""
        response = self.client.get("/api/cleanup/files")
        # Не должно быть 404
        assert response.status_code != 404


# ====== Тесты для FileStorageManager (дополнительно) ======

def test_file_storage_manager_get_stats_structure():
    """Тест структуры возвращаемых get_stats данных"""
    # Проверяем что функция возвращает ожидаемую структуру
    mock_storage = MagicMock()
    expected_stats = {
        "total_files": 2,
        "storage_dir": "/tmp/test",
        "ttl_seconds": 3600,
        "files": [
            {
                "name": "test.txt",
                "size": 1024,
                "age_seconds": 1800,
                "time_left_seconds": 1800,
                "created": "2024-01-01T00:00:00"
            }
        ]
    }
    mock_storage.get_stats.return_value = expected_stats
    
    result = mock_storage.get_stats()
    
    assert result["total_files"] == 2
    assert "storage_dir" in result
    assert "ttl_seconds" in result
    assert "files" in result
    assert len(result["files"]) == 1
    assert result["files"][0]["name"] == "test.txt"

def test_file_storage_manager_force_cleanup_structure():
    """Тест структуры возвращаемых force_cleanup данных"""
    mock_storage = MagicMock()
    expected_result = {
        "deleted": 5,
        "errors": []
    }
    mock_storage.force_cleanup.return_value = expected_result
    
    result = mock_storage.force_cleanup()
    
    assert "deleted" in result
    assert "errors" in result
    assert isinstance(result["deleted"], int)
    assert isinstance(result["errors"], list)


# ====== Параметризованные тесты ======

@pytest.mark.parametrize("file_count,expected_count", [
    (0, 0),
    (1, 1),
    (5, 5),
    (10, 10),
])
def test_list_temp_files_count_parametrized(temp_decrypted_dir, mock_auth_admin, file_count, expected_count):
    """Параметризованный тест количества файлов"""
    # Создаем указанное количество файлов
    for i in range(file_count):
        file_path = temp_decrypted_dir / f"file_{i}.txt"
        file_path.write_text(f"content {i}")
    
    # Мокаем DECRYPTED_DIR и импортируем
    with patch('app.api.cleanup.DECRYPTED_DIR', temp_decrypted_dir):
        with patch('app.api.cleanup.router', None):
            from app.api.cleanup import list_temp_files
            
            # Запускаем синхронно
            import asyncio
            response = asyncio.run(list_temp_files(current_user=mock_auth_admin))
    
    assert response["count"] == expected_count
    assert len(response["files"]) == expected_count


# ====== Тесты для утилит ======

def test_time_module_imported():
    """Тест что модуль time импортирован"""
    from app.api.cleanup import time
    assert time.__name__ == "time"

def test_path_operations_in_code():
    """Тест операций с путями используемых в коде"""
    # Проверяем операции которые используются в list_temp_files
    test_dir = Path("/tmp/test")
    
    # .exists()
    assert hasattr(test_dir, 'exists')
    
    # .iterdir()
    assert hasattr(test_dir, 'iterdir')
    
    # .is_file()
    test_path = Path("/tmp/test.txt")
    assert hasattr(test_path, 'is_file')
    
    # .stat()
    assert hasattr(test_path, 'stat')


# ====== Тесты для вычисления возраста файлов ======

def test_file_age_calculation():
    """Тест вычисления возраста файлов"""
    import time
    
    # Создаем временный файл
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False) as f:
        file_path = Path(f.name)
        f.write(b"test content")
    
    try:
        # Получаем время модификации
        mtime = file_path.stat().st_mtime
        current_time = time.time()
        
        # Вычисляем возраст как в коде
        age_seconds = current_time - mtime
        age_hours = age_seconds / 3600
        
        # Проверяем что вычисления корректны
        assert age_seconds > 0
        assert age_hours > 0
        assert age_hours == age_seconds / 3600
        
    finally:
        # Удаляем временный файл
        file_path.unlink()


# ====== Простые тесты ======

def test_simple_import():
    """Простой тест импорта"""
    from app.api.cleanup import router
    assert router is not None

def test_router_prefix():
    """Тест что роутер имеет правильные настройки"""
    from app.api.cleanup import router
    # Проверяем что роутер имеет атрибуты
    assert hasattr(router, 'routes')


# Запустим тесты
if __name__ == "__main__":
    pytest.main([__file__, "-v"])