"""
Тесты для app/api/stats.py
Обновленная версия с правильным моком аутентификации
"""

import pytest
import json
import time
import asyncio
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
from app.main import app


# ============================================================================
# ФИКСТУРЫ
# ============================================================================

@pytest.fixture
def client():
    """Создает тестовый клиент FastAPI"""
    return TestClient(app)


@pytest.fixture
def mock_auth():
    """Создает мок для аутентификации"""
    mock = AsyncMock()
    mock.return_value = "admin_user"
    return mock


@pytest.fixture
def client_with_auth(mock_auth):
    """Клиент с замоканной аутентификацией"""
    from app.api.stats import get_current_admin
    
    # Переопределяем зависимость
    app.dependency_overrides[get_current_admin] = lambda: mock_auth.return_value
    
    client = TestClient(app)
    yield client
    
    # Очищаем переопределения после теста
    app.dependency_overrides.clear()


# ============================================================================
# ТЕСТЫ ЭНДПОИНТОВ С АВТОРИЗАЦИЕЙ
# ============================================================================

def test_get_system_stats_success(client_with_auth):
    """Тест успешного получения системной статистики"""
    mock_stats = {
        "timestamp": "2024-01-01T00:00:00",
        "system": {"uptime": 3600},
        "storage": {"total_size_mb": 100},
        "files": {"encrypted": {"count": 5}},
        "cleanup": {},
        "audit": {},
        "performance": {},
        "summary": {"total_files": 5, "total_size_mb": 100}
    }
    
    with patch('app.api.stats._collect_all_stats') as mock_collect:
        mock_collect.return_value = mock_stats
        
        response = client_with_auth.get("/api/stats")
        
        assert response.status_code == 200
        data = response.json()
        assert data == mock_stats
        mock_collect.assert_called_once()


def test_get_system_stats_error(client_with_auth):
    """Тест ошибки при получении статистики"""
    with patch('app.api.stats._collect_all_stats') as mock_collect:
        mock_collect.side_effect = Exception("Test error")
        
        response = client_with_auth.get("/api/stats")
        
        assert response.status_code == 500
        data = response.json()
        assert "detail" in data
        assert "Test error" in data["detail"]


def test_get_stats_summary_success(client_with_auth):
    """Тест успешного получения сводки статистики"""
    mock_full_stats = {
        "timestamp": "2024-01-01T00:00:00",
        "summary": {"total_files": 10, "total_size_mb": 50},
        "system": {"uptime": 7200},
        "storage": {
            "directories": {
                "encrypted": {"size_bytes": 1024, "file_count": 2},
                "decrypted": {"size_bytes": 2048, "file_count": 3}
            },
            "total_size_mb": 50
        },
        "files": {
            "encrypted": {
                "extensions": {
                    ".txt": {"count": 5},
                    ".pdf": {"count": 3}
                }
            }
        },
        "cleanup": {
            "files_scheduled_for_deletion": {"count": 1},
            "temporary_files": {"total_files": 2}
        }
    }
    
    with patch('app.api.stats._collect_all_stats') as mock_collect:
        mock_collect.return_value = mock_full_stats
        
        response = client_with_auth.get("/api/stats/summary")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["timestamp"] == "2024-01-01T00:00:00"
        assert data["total_files"] == 10
        assert data["total_size_mb"] == 50
        assert "directories" in data
        assert "file_types" in data
        assert "cleanup" in data


def test_get_stats_summary_with_missing_data(client_with_auth):
    """Тест /stats/summary с неполными данными"""
    mock_full_stats = {
        "timestamp": "2024-01-01T00:00:00",
        "summary": {"total_files": 0, "total_size_mb": 0},
        "system": {"uptime": 0},
        "storage": {
            "directories": {},
            "total_size_mb": 0
        },
        "files": {"encrypted": {"extensions": {}, "count": 0}},
        "cleanup": {
            "files_scheduled_for_deletion": {"count": 0},
            "temporary_files": {}
        }
    }
    
    with patch('app.api.stats._collect_all_stats') as mock_collect:
        mock_collect.return_value = mock_full_stats
        
        response = client_with_auth.get("/api/stats/summary")
        
        assert response.status_code == 200
        data = response.json()
        assert data["total_files"] == 0
        assert data["total_size_mb"] == 0


def test_get_stats_summary_exception_handling(client_with_auth):
    """Тест строк 353-381: обработка исключений в get_stats_summary"""
    with patch('app.api.stats._collect_all_stats') as mock_collect:
        mock_collect.side_effect = Exception("Failed to collect stats")
        
        response = client_with_auth.get("/api/stats/summary")
        
        assert response.status_code == 500
        data = response.json()
        assert "detail" in data
        assert "Failed to generate summary" in data["detail"]


def test_get_stats_summary_missing_keys(client_with_auth):
    """Тест строк 353-381: обработка отсутствующих ключей в get_stats_summary"""
    with patch('app.api.stats._collect_all_stats') as mock_collect:
        mock_collect.return_value = {
            "timestamp": "2024-01-01T00:00:00",
            # Нет ключа 'summary' - вызовет KeyError
        }
        
        response = client_with_auth.get("/api/stats/summary")
        
        assert response.status_code == 500
        data = response.json()
        assert "detail" in data
        assert "Failed to generate summary" in data["detail"]


def test_get_health_detailed_success(client_with_auth):
    """Тест успешного получения детального здоровья системы"""
    response = client_with_auth.get("/api/stats/health")
    
    assert response.status_code == 200
    data = response.json()
    
    assert "timestamp" in data
    assert "overall_status" in data
    assert "checks" in data
    assert isinstance(data["checks"], list)
    assert "recommendations" in data
    assert isinstance(data["recommendations"], list)


def test_get_health_detailed_with_problems(client_with_auth):
    """Тест /stats/health с проблемами в системе"""
    # Мокаем директории, чтобы они не существовали
    with patch('app.api.stats.ENCRYPTED_DIR') as mock_encrypted:
        mock_encrypted.exists.return_value = False
        mock_encrypted.absolute.return_value = Path("/test/encrypted")
        
        response = client_with_auth.get("/api/stats/health")
        
        assert response.status_code == 200
        data = response.json()
        
        # Система должна быть degraded или unhealthy
        assert data["overall_status"] in ["degraded", "unhealthy"]


def test_get_health_detailed_comprehensive(client_with_auth):
    """Тест строк 387-448: комплексное тестирование get_health_detailed"""
    with patch('app.api.stats.ENCRYPTED_DIR') as mock_encrypted:
        mock_encrypted.exists.return_value = True
        mock_encrypted.absolute.return_value = Path("/test/encrypted")
        mock_encrypted.iterdir.return_value = []
        
        response = client_with_auth.get("/api/stats/health")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "overall_status" in data
        assert "checks" in data
        assert len(data["checks"]) > 0


def test_get_health_detailed_key_file_empty(client_with_auth):
    """Тест строк 387-448: get_health_detailed с пустым ключевым файлом"""
    # Мокаем Path для возврата пустого ключевого файла
    mock_key_file = Mock()
    mock_key_file.exists.return_value = True
    mock_key_file.stat.return_value.st_size = 0
    
    with patch('pathlib.Path') as mock_path_class:
        def path_side_effect(*args, **kwargs):
            if args and "age.key" in str(args[0]):
                return mock_key_file
            # Для директорий возвращаем существующие
            mock_dir = Mock()
            mock_dir.exists.return_value = True
            mock_dir.absolute.return_value = Path("/test/dir")
            return mock_dir
        
        mock_path_class.side_effect = path_side_effect
        
        response = client_with_auth.get("/api/stats/health")
        
        assert response.status_code == 200
        data = response.json()
        
        # Проверяем, что есть проверка ключей
        key_checks = [check for check in data["checks"] if "Encryption keys" in check["check"]]
        assert len(key_checks) > 0


def test_get_health_detailed_access_exception(client_with_auth):
    """Тест строк 387-448: get_health_detailed с исключением при проверке доступа"""
    with patch('app.api.stats.ENCRYPTED_DIR') as mock_encrypted:
        mock_encrypted.exists.return_value = True
        mock_encrypted.absolute.return_value = Path("/test/encrypted")
        mock_encrypted.iterdir.side_effect = Exception("Permission denied")
        
        response = client_with_auth.get("/api/stats/health")
        
        assert response.status_code == 200
        data = response.json()
        
        # Должна быть проверка доступа
        access_checks = [check for check in data["checks"] if "File system access" in check["check"]]
        assert len(access_checks) > 0


# ============================================================================
# ТЕСТЫ БЕЗ АВТОРИЗАЦИИ
# ============================================================================

def test_stats_endpoints_without_auth(client):
    """Тест endpoints без аутентификации"""
    endpoints = [
        "/api/stats",
        "/api/stats/summary",
        "/api/stats/health"
    ]
    
    for endpoint in endpoints:
        response = client.get(endpoint)
        # Должны получить 401 или 403
        assert response.status_code in [401, 403]


def test_stats_endpoints_with_doctor_role(client):
    """Тест endpoints с ролью doctor (должен быть 403)"""
    from app.api.stats import get_current_admin
    from fastapi import HTTPException
    
    mock_auth = AsyncMock()
    mock_auth.side_effect = HTTPException(status_code=403, detail="Admin access required")
    
    app.dependency_overrides[get_current_admin] = lambda: mock_auth
    
    try:
        response = client.get("/api/stats")
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_stats_endpoints_with_user_role(client):
    """Тест endpoints с ролью user (должен быть 403)"""
    from app.api.stats import get_current_admin
    from fastapi import HTTPException
    
    mock_auth = AsyncMock()
    mock_auth.side_effect = HTTPException(status_code=403, detail="Admin access required")
    
    app.dependency_overrides[get_current_admin] = lambda: mock_auth
    
    try:
        response = client.get("/api/stats/summary")
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


# ============================================================================
# ТЕСТЫ ВСПОМОГАТЕЛЬНЫХ ФУНКЦИЙ
# ============================================================================

@pytest.mark.asyncio
async def test_get_system_stats_function():
    """Тест функции _get_system_stats"""
    from app.api.stats import _get_system_stats
    
    with patch('platform.system', return_value="Linux"):
        with patch('platform.version', return_value="5.15.0"):
            with patch('platform.python_version', return_value="3.12.3"):
                with patch('platform.node', return_value="test-host"):
                    with patch('platform.processor', return_value="x86_64"):
                        with patch('psutil.cpu_percent', return_value=50.0):
                            with patch('psutil.cpu_count', return_value=8):
                                with patch('psutil.virtual_memory') as mock_memory:
                                    mock_memory.return_value.total = 16 * 1024**3
                                    mock_memory.return_value.available = 8 * 1024**3
                                    mock_memory.return_value.used = 8 * 1024**3
                                    mock_memory.return_value.percent = 50.0
                                    
                                    with patch('psutil.disk_usage') as mock_disk:
                                        mock_disk.return_value.total = 100 * 1024**3
                                        mock_disk.return_value.used = 50 * 1024**3
                                        mock_disk.return_value.free = 50 * 1024**3
                                        mock_disk.return_value.percent = 50.0
                                        
                                        with patch('psutil.boot_time', return_value=time.time() - 3600):
                                            stats = await _get_system_stats()
                                            
                                            assert stats["system"]["platform"] == "Linux"
                                            assert stats["cpu"]["percent"] == 50.0
                                            assert stats["cpu"]["count"] == 8
                                            assert stats["memory"]["total_gb"] == 16.0
                                            assert stats["disk"]["total_gb"] == 100.0
                                            assert stats["uptime"] > 0


@pytest.mark.asyncio
async def test_get_system_stats_loadavg_not_supported():
    """Тест строки 89: когда psutil.getloadavg не поддерживается"""
    from app.api.stats import _get_system_stats
    
    with patch('platform.system', return_value="Linux"):
        with patch('platform.version', return_value="5.15.0"):
            with patch('platform.python_version', return_value="3.12.3"):
                with patch('platform.node', return_value="test-host"):
                    with patch('platform.processor', return_value="x86_64"):
                        with patch('psutil.cpu_percent', return_value=50.0):
                            with patch('psutil.cpu_count', return_value=8):
                                # Симулируем отсутствие getloadavg в psutil
                                with patch('app.api.stats.hasattr') as mock_hasattr:
                                    def hasattr_side_effect(obj, name):
                                        if name == 'getloadavg':
                                            return False
                                        return True
                                    
                                    mock_hasattr.side_effect = hasattr_side_effect
                                    
                                    with patch('psutil.virtual_memory') as mock_memory:
                                        mock_memory.return_value.total = 16 * 1024**3
                                        mock_memory.return_value.available = 8 * 1024**3
                                        mock_memory.return_value.used = 8 * 1024**3
                                        mock_memory.return_value.percent = 50.0
                                        
                                        with patch('psutil.disk_usage') as mock_disk:
                                            mock_disk.return_value.total = 100 * 1024**3
                                            mock_disk.return_value.used = 50 * 1024**3
                                            mock_disk.return_value.free = 50 * 1024**3
                                            mock_disk.return_value.percent = 50.0
                                            
                                            with patch('psutil.boot_time', return_value=time.time() - 3600):
                                                stats = await _get_system_stats()
                                                
                                                assert "cpu" in stats
                                                assert "load_avg" in stats["cpu"]
                                                assert stats["cpu"]["load_avg"] == "not_supported"


@pytest.mark.asyncio
async def test_get_system_stats_psutil_unavailable():
    """Тест _get_system_stats когда psutil недоступен (как в Docker)"""
    from app.api.stats import _get_system_stats
    
    with patch('platform.system', return_value="Linux"):
        with patch('platform.version', return_value="5.15.0"):
            with patch('platform.python_version', return_value="3.12.3"):
                with patch('platform.node', return_value="test-host"):
                    with patch('platform.processor', return_value="x86_64"):
                        with patch('psutil.cpu_percent', side_effect=Exception("Docker限制")):
                            with patch('psutil.cpu_count', side_effect=Exception("Docker限制")):
                                with patch('psutil.getloadavg', side_effect=AttributeError):
                                    with patch('psutil.virtual_memory', side_effect=Exception("Docker限制")):
                                        with patch('psutil.disk_usage', side_effect=Exception("Docker限制")):
                                            with patch('psutil.boot_time', side_effect=Exception("Docker限制")):
                                                stats = await _get_system_stats()
                                                
                                                assert "cpu" in stats
                                                assert "memory" in stats
                                                assert "disk" in stats
                                                assert stats["cpu"]["percent"] == "unavailable_in_container"
                                                assert stats["cpu"]["count"] == "unavailable_in_container"


@pytest.mark.asyncio
async def test_get_storage_stats():
    """Тест функции _get_storage_stats"""
    from app.api.stats import _get_storage_stats
    
    with patch('app.api.stats.ENCRYPTED_DIR') as mock_encrypted:
        with patch('app.api.stats.DECRYPTED_DIR') as mock_decrypted:
            with patch('app.api.stats.UPLOAD_DIR') as mock_upload:
                mock_dir = Mock(spec=Path)
                mock_dir.exists.return_value = True
                mock_dir.rglob.return_value = []
                
                mock_encrypted.return_value = mock_dir
                mock_decrypted.return_value = mock_dir
                mock_upload.return_value = mock_dir
                
                with patch('pathlib.Path.exists', return_value=True):
                    with patch('pathlib.Path.rglob', return_value=[]):
                        stats = await _get_storage_stats()
                        
                        assert "directories" in stats
                        assert "total_size_bytes" in stats
                        assert "total_size_mb" in stats
                        assert "total_files" in stats


@pytest.mark.asyncio
async def test_get_directory_stats_existing():
    """Тест функции _get_directory_stats для существующей директории"""
    from app.api.stats import _get_directory_stats
    
    with patch('pathlib.Path.exists', return_value=True):
        with patch('pathlib.Path.rglob') as mock_rglob:
            mock_file = Mock()
            mock_file.is_file.return_value = True
            mock_file.stat.return_value.st_size = 1024
            mock_file.stat.return_value.st_mtime = 1704067200
            
            mock_rglob.return_value = [mock_file]
            
            stats = await _get_directory_stats(Path("/test"))
            
            assert stats["exists"] is True
            assert stats["size_bytes"] == 1024
            assert stats["file_count"] == 1
            assert "last_modified" in stats


@pytest.mark.asyncio
async def test_get_directory_stats_nonexistent():
    """Тест функции _get_directory_stats для несуществующей директории"""
    from app.api.stats import _get_directory_stats
    
    with patch('pathlib.Path.exists', return_value=False):
        stats = await _get_directory_stats(Path("/nonexistent"))
        
        assert stats["exists"] is False
        assert stats["size_bytes"] == 0
        assert stats["file_count"] == 0
        assert stats["last_modified"] is None


@pytest.mark.asyncio
async def test_get_directory_stats_with_exception():
    """Тест _get_directory_stats при исключении во время обхода файлов"""
    from app.api.stats import _get_directory_stats
    
    mock_dir = Mock(spec=Path)
    mock_dir.exists.return_value = True
    
    with patch('pathlib.Path.rglob', side_effect=Exception("Permission denied")):
        stats = await _get_directory_stats(mock_dir)
        
        assert stats["exists"] is True
        assert "error" in stats
        assert stats["size_bytes"] == 0
        assert stats["file_count"] == 0


def test_get_files_stats_with_files():
    """Тест функции _get_files_stats с файлами"""
    from app.api.stats import _get_files_stats
    
    with patch('app.api.stats.ENCRYPTED_DIR') as mock_dir:
        mock_dir.exists.return_value = True
        
        mock_file1 = Mock()
        mock_file1.is_file.return_value = True
        mock_file1.name = "test1.txt"
        mock_file1.suffix = ".txt"
        mock_file1.stat.return_value.st_size = 1024
        mock_file1.stat.return_value.st_ctime = time.time() - 86400
        mock_file1.stat.return_value.st_mtime = time.time() - 86400
        
        mock_file2 = Mock()
        mock_file2.is_file.return_value = True
        mock_file2.name = "test2.pdf"
        mock_file2.suffix = ".pdf"
        mock_file2.stat.return_value.st_size = 2048
        mock_file2.stat.return_value.st_ctime = time.time() - 172800
        mock_file2.stat.return_value.st_mtime = time.time() - 172800
        
        mock_dir.iterdir.return_value = [mock_file1, mock_file2]
        
        with patch('app.api.stats.file_storage') as mock_storage:
            mock_storage.get_stats.return_value = {"temp_files": 3}
            
            stats = asyncio.run(_get_files_stats())
            
            assert stats["encrypted"]["count"] == 2
            assert stats["encrypted"]["total_size"] == 3072
            assert ".txt" in stats["encrypted"]["extensions"]
            assert ".pdf" in stats["encrypted"]["extensions"]
            assert len(stats["encrypted"]["oldest_files"]) <= 5
            assert len(stats["encrypted"]["newest_files"]) <= 5
            assert len(stats["encrypted"]["largest_files"]) <= 5
            assert "temporary" in stats


def test_get_files_stats_empty():
    """Тест функции _get_files_stats без файлов"""
    from app.api.stats import _get_files_stats
    
    with patch('app.api.stats.ENCRYPTED_DIR') as mock_dir:
        mock_dir.exists.return_value = True
        mock_dir.iterdir.return_value = []
        
        stats = asyncio.run(_get_files_stats())
        
        assert stats["encrypted"]["count"] == 0
        assert stats["encrypted"]["total_size"] == 0
        assert stats["encrypted"]["extensions"] == {}
        assert stats["encrypted"]["oldest_files"] == []
        assert stats["encrypted"]["newest_files"] == []
        assert stats["encrypted"]["largest_files"] == []


@pytest.mark.asyncio
async def test_get_files_stats_except_continue():
    """Тест строк 181-182: обработка исключений в _get_files_stats"""
    from app.api.stats import _get_files_stats
    
    with patch('app.api.stats.ENCRYPTED_DIR') as mock_dir:
        mock_dir.exists.return_value = True
        
        mock_file_good = Mock()
        mock_file_good.is_file.return_value = True
        mock_file_good.name = "good.txt"
        mock_file_good.suffix = ".txt"
        mock_file_good.stat.return_value.st_size = 1024
        mock_file_good.stat.return_value.st_ctime = time.time() - 86400
        mock_file_good.stat.return_value.st_mtime = time.time() - 86400
        
        mock_file_bad = Mock()
        mock_file_bad.is_file.return_value = True
        mock_file_bad.name = "bad.txt"
        mock_file_bad.suffix = ".txt"
        mock_file_bad.stat.side_effect = Exception("Permission denied")
        
        mock_dir.iterdir.return_value = [mock_file_good, mock_file_bad]
        
        with patch('app.api.stats.file_storage') as mock_storage:
            mock_storage.get_stats.return_value = {}
            
            stats = await _get_files_stats()
            
            assert stats["encrypted"]["count"] == 1
            assert stats["encrypted"]["total_size"] == 1024
            assert ".txt" in stats["encrypted"]["extensions"]
            assert stats["encrypted"]["extensions"][".txt"]["count"] == 1


def test_get_cleanup_stats():
    """Тест функции _get_cleanup_stats"""
    from app.api.stats import _get_cleanup_stats
    
    with patch('app.api.stats.ENCRYPTED_DIR') as mock_dir:
        mock_dir.exists.return_value = True
        
        mock_old_file = Mock()
        mock_old_file.is_file.return_value = True
        mock_old_file.name = "old.txt"
        mock_old_file.stat.return_value.st_size = 1024
        mock_old_file.stat.return_value.st_atime = time.time() - 40 * 86400
        
        mock_dir.iterdir.return_value = [mock_old_file]
        
        with patch('app.api.stats.cleanup_manager') as mock_cleanup:
            mock_cleanup.get_cleanup_stats.return_value = {"cleaned": 5}
            
            with patch('app.api.stats.file_storage') as mock_storage:
                mock_storage.get_stats.return_value = {"total_files": 2}
                
                stats = asyncio.run(_get_cleanup_stats())
                
                assert "cleanup_manager" in stats
                assert "files_scheduled_for_deletion" in stats
                assert "temporary_files" in stats
                assert "retention_policy" in stats
                
                deletion_stats = stats["files_scheduled_for_deletion"]
                assert deletion_stats["count"] == 1
                assert deletion_stats["total_size"] == 1024


def test_get_audit_stats():
    """Тест функции _get_audit_stats"""
    from app.api.stats import _get_audit_stats
    
    with patch('pathlib.Path.exists', return_value=True):
        with patch('pathlib.Path.iterdir') as mock_iterdir:
            mock_log = Mock()
            mock_log.is_file.return_value = True
            mock_log.name = "audit_2024-01-01.log"
            mock_log.stat.return_value.st_size = 2048
            mock_log.stat.return_value.st_mtime = 1704067200
            
            mock_iterdir.return_value = [mock_log]
            
            with patch('builtins.open') as mock_open:
                mock_open.return_value.__enter__.return_value.readlines.return_value = [
                    '{"action": "upload", "filename": "test.txt"}\n',
                    '{"action": "download", "filename": "test.txt"}\n'
                ]
                
                stats = asyncio.run(_get_audit_stats())
                
                assert "total_log_files" in stats
                assert "total_log_size" in stats
                assert "recent_logs" in stats
                assert "latest_log" in stats
                assert stats["total_log_files"] == 1
                assert stats["total_log_size"] == 2048


@pytest.mark.asyncio
async def test_get_audit_stats_exception_handling():
    """Тест строк 329-330: обработка исключений в _get_audit_stats"""
    from app.api.stats import _get_audit_stats
    
    with patch('pathlib.Path.exists', side_effect=Exception("Test exception")):
        stats = await _get_audit_stats()
        
        assert "error" in stats
        assert "Test exception" in stats["error"]


@pytest.mark.asyncio
async def test_get_performance_stats():
    """Тест функции _get_performance_stats"""
    from app.api.stats import _get_performance_stats
    
    stats = await _get_performance_stats()
    
    assert "encryption_performance" in stats
    assert "api_usage" in stats
    assert stats["encryption_performance"]["note"] == "Metrics would be collected over time"
    assert stats["encryption_performance"]["average_encryption_time_ms"] == "N/A"
    assert stats["api_usage"]["note"] == "API usage statistics would be implemented"


@pytest.mark.asyncio
async def test_collect_all_stats_success():
    """Тест успешного сбора всей статистики"""
    from app.api.stats import _collect_all_stats
    
    mock_system_stats = {
        "system": {"platform": "Linux"},
        "cpu": {"percent": 50.0},
        "memory": {"total_gb": 16.0},
        "disk": {"total_gb": 100.0},
        "uptime": 3600
    }
    
    mock_storage_stats = {
        "directories": {
            "encrypted": {"size_bytes": 1024, "file_count": 2},
            "decrypted": {"size_bytes": 2048, "file_count": 3}
        },
        "total_size_bytes": 3072,
        "total_size_mb": 0.0029296875,
        "total_size_gb": 2.86102294921875e-06,
        "total_files": 5
    }
    
    mock_files_stats = {
        "encrypted": {
            "count": 5,
            "total_size": 5120,
            "extensions": {".txt": {"count": 3}},
            "oldest_files": [],
            "newest_files": [],
            "largest_files": []
        },
        "temporary": {"total_files": 2}
    }
    
    mock_cleanup_stats = {
        "cleanup_manager": {"cleaned": 5},
        "files_scheduled_for_deletion": {"count": 1},
        "temporary_files": {"total_files": 2},
        "retention_policy": {"default_days": 30}
    }
    
    mock_audit_stats = {
        "total_log_files": 3,
        "total_log_size": 10240,
        "recent_logs": []
    }
    
    mock_performance_stats = {
        "encryption_performance": {},
        "api_usage": {}
    }
    
    with patch('app.api.stats._get_system_stats', return_value=mock_system_stats):
        with patch('app.api.stats._get_storage_stats', return_value=mock_storage_stats):
            with patch('app.api.stats._get_files_stats', return_value=mock_files_stats):
                with patch('app.api.stats._get_cleanup_stats', return_value=mock_cleanup_stats):
                    with patch('app.api.stats._get_audit_stats', return_value=mock_audit_stats):
                        with patch('app.api.stats._get_performance_stats', return_value=mock_performance_stats):
                            stats = await _collect_all_stats()
                            
                            assert "timestamp" in stats
                            assert "system" in stats
                            assert "storage" in stats
                            assert "files" in stats
                            assert "cleanup" in stats
                            assert "audit" in stats
                            assert "performance" in stats
                            assert "summary" in stats
                            assert stats["summary"]["total_files"] == 5
                            assert stats["summary"]["health"] == "healthy"


@pytest.mark.asyncio
async def test_collect_all_stats_with_errors():
    """Тест сбора статистики с ошибками в некоторых компонентах"""
    from app.api.stats import _collect_all_stats
    
    mock_system_stats = {"system": {}, "cpu": {}, "memory": {}, "disk": {}, "uptime": 0}
    mock_storage_stats = {"directories": {}, "total_size_mb": 0}
    mock_files_stats = {"encrypted": {"count": -1}}
    mock_cleanup_stats = {}
    mock_audit_stats = {}
    mock_performance_stats = {}
    
    with patch('app.api.stats._get_system_stats', return_value=mock_system_stats):
        with patch('app.api.stats._get_storage_stats', return_value=mock_storage_stats):
            with patch('app.api.stats._get_files_stats', return_value=mock_files_stats):
                with patch('app.api.stats._get_cleanup_stats', return_value=mock_cleanup_stats):
                    with patch('app.api.stats._get_audit_stats', return_value=mock_audit_stats):
                        with patch('app.api.stats._get_performance_stats', return_value=mock_performance_stats):
                            stats = await _collect_all_stats()
                            
                            assert "summary" in stats
                            assert stats["summary"]["health"] == "degraded"


# ============================================================================
# ПАРАМЕТРИЗОВАННЫЕ ТЕСТЫ
# ============================================================================

@pytest.mark.parametrize("file_name,expected_ext", [
    ("document.txt", ".txt"),
    ("report.pdf", ".pdf"),
    ("image.jpg", ".jpg"),
    ("scan.dcm", ".dcm"),
    ("data.age", ".age"),
    ("file_without_ext", "no_extension"),
    (".hidden", ""),
])
@pytest.mark.asyncio
async def test_get_files_stats_different_extensions(file_name, expected_ext):
    """Параметризованный тест для разных расширений файлов"""
    from app.api.stats import _get_files_stats
    
    with patch('app.api.stats.ENCRYPTED_DIR') as mock_dir:
        mock_dir.exists.return_value = True
        
        mock_file = Mock()
        mock_file.is_file.return_value = True
        mock_file.name = file_name
        mock_file.suffix = Path(file_name).suffix if Path(file_name).suffix else ""
        mock_file.stat.return_value.st_size = 1024
        mock_file.stat.return_value.st_ctime = time.time() - 86400
        mock_file.stat.return_value.st_mtime = time.time() - 86400
        
        mock_dir.iterdir.return_value = [mock_file]
        
        with patch('app.api.stats.file_storage') as mock_storage:
            mock_storage.get_stats.return_value = {}
            
            stats = await _get_files_stats()
            
            ext_key = expected_ext if expected_ext else "no_extension"
            if ext_key == "":
                ext_key = "no_extension"
            
            if ext_key in ["no_extension", ""]:
                assert stats["encrypted"]["count"] == 1
            else:
                assert ext_key in stats["encrypted"]["extensions"]
                assert stats["encrypted"]["extensions"][ext_key]["count"] == 1


# ============================================================================
# ИНТЕГРАЦИОННЫЕ ТЕСТЫ
# ============================================================================

@pytest.mark.integration
def test_stats_with_real_files(tmp_path):
    """Интеграционный тест со временными файлами"""
    import asyncio
    from app.api.stats import _get_directory_stats
    
    test_dir = tmp_path / "test_storage"
    test_dir.mkdir()
    
    (test_dir / "file1.txt").write_text("Hello, World!")
    (test_dir / "file2.pdf").write_bytes(b"PDF content" * 100)
    (test_dir / "file3.jpg").write_bytes(b"JPG" * 50)
    
    subdir = test_dir / "subdir"
    subdir.mkdir()
    (subdir / "nested.txt").write_text("Nested file")
    
    stats = asyncio.run(_get_directory_stats(test_dir))
    
    assert stats["exists"] is True
    assert stats["file_count"] == 4
    assert stats["size_bytes"] > 0
    assert "last_modified" in stats


@pytest.mark.integration
def test_get_files_stats_integration(tmp_path):
    """Интеграционный тест _get_files_stats с реальными файлами"""
    import asyncio
    from app.api.stats import _get_files_stats
    
    encrypted_dir = tmp_path / "encrypted"
    encrypted_dir.mkdir()
    
    (encrypted_dir / "doc1.txt").write_text("Text document")
    (encrypted_dir / "doc2.txt").write_text("Another text")
    (encrypted_dir / "image.jpg").write_bytes(b"JPG" * 100)
    (encrypted_dir / "report.pdf").write_bytes(b"PDF" * 200)
    
    with patch('app.api.stats.ENCRYPTED_DIR', encrypted_dir):
        with patch('app.api.stats.file_storage') as mock_storage:
            mock_storage.get_stats.return_value = {"temp_files": 0}
            
            stats = asyncio.run(_get_files_stats())
            
            assert stats["encrypted"]["count"] == 4
            assert stats["encrypted"]["total_size"] > 0
            assert ".txt" in stats["encrypted"]["extensions"]
            assert stats["encrypted"]["extensions"][".txt"]["count"] == 2
            assert ".jpg" in stats["encrypted"]["extensions"]
            assert ".pdf" in stats["encrypted"]["extensions"]


# ============================================================================
# ТЕСТЫ ДЛЯ PRINT В ЭНДПОИНТАХ
# ============================================================================

def test_get_system_stats_print_and_exception(client_with_auth):
    """Тест строк 22-29: проверка вывода и обработки исключений"""
    with patch('app.api.stats._collect_all_stats') as mock_collect:
        mock_collect.side_effect = Exception("Specific test error")
        
        # Мокаем print, чтобы проверить вывод
        with patch('app.api.stats.print') as mock_print:
            response = client_with_auth.get("/api/stats")
            
            # Проверяем, что print был вызван хотя бы один раз
            assert mock_print.called
            
            # Проверяем ответ
            assert response.status_code == 500
            data = response.json()
            assert "Failed to collect stats" in data["detail"]


def test_get_system_stats_success_with_print(client_with_auth):
    """Тест строк 22-29: успешный запрос с проверкой print"""
    mock_stats = {
        "timestamp": "2024-01-01T00:00:00",
        "system": {"uptime": 3600},
        "summary": {"total_files": 5}
    }
    
    with patch('app.api.stats._collect_all_stats', return_value=mock_stats):
        with patch('app.api.stats.print') as mock_print:
            response = client_with_auth.get("/api/stats")
            
            # Проверяем, что print был вызван
            assert mock_print.called
            
            # Проверяем ответ
            assert response.status_code == 200
            data = response.json()
            assert data == mock_stats


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
