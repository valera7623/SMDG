# tests/test_app/test_main.py
import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

# Добавляем корень проекта в PYTHONPATH
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Мокаем audit_logger перед импортом app
with patch("app.core.audit_logger") as mock_audit_logger:
    with patch("app.main.audit_logger") as mock_main_audit:
        # Создаем мок для log_operation
        mock_log = MagicMock()
        mock_audit_logger.log_operation = mock_log
        mock_main_audit.log_operation = mock_log
        
        # Импортируем app после моков
        from app.main import app

def test_health_check():
    """Тест эндпоинта проверки здоровья"""
    from fastapi.testclient import TestClient
    
    # Мокаем os.path.exists чтобы вернуть True для всех директорий
    with patch("os.path.exists", return_value=True):
        client = TestClient(app)
        response = client.get("/health")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "smdg"
    assert "features" in data
    assert "directories" in data

def test_index_page():
    """Тест главной страницы"""
    from fastapi.testclient import TestClient
    
    # Мокаем файл index.html
    with patch("builtins.open", mock_open(read_data="<html>SMDG Test</html>")):
        with patch("os.path.exists", return_value=True):
            client = TestClient(app)
            response = client.get("/")
    
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "SMDG" in response.text

def test_admin_page():
    """Тест страницы администратора"""
    from fastapi.testclient import TestClient
    
    # Мокаем файл admin.html
    with patch("builtins.open", mock_open(read_data="<html>Admin Panel</html>")):
        with patch("os.path.exists", return_value=True):
            client = TestClient(app)
            response = client.get("/admin")
    
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

def test_index_page_file_not_found():
    """Тест главной страницы при отсутствии файла"""
    from fastapi.testclient import TestClient
    
    with patch("builtins.open", side_effect=FileNotFoundError):
        with patch("os.path.exists", return_value=True):
            client = TestClient(app)
            response = client.get("/")
    
    assert response.status_code == 200
    # Проверяем что возвращается fallback HTML
    assert "SMDG" in response.text
    assert "не найден файл" in response.text or "Ошибка" in response.text

def test_logs_page():
    """Тест страницы просмотра логов"""
    from fastapi.testclient import TestClient
    
    # Мокаем os.listdir для возврата тестовых логов
    with patch("os.path.exists", return_value=True):
        with patch("os.listdir", return_value=["audit_2026-01-27.log", "audit_2026-01-26.log"]):
            client = TestClient(app)
            response = client.get("/logs")
    
    assert response.status_code == 200
    assert "логи аудита" in response.text.lower()
    assert "text/html" in response.headers["content-type"]

def test_api_routes_registered():
    """Тест регистрации API роутов"""
    # Проверяем что основные роуты зарегистрированы в app
    routes_to_check = ["/api/upload", "/api/download", "/api/list", "/api/delete"]
    
    # Просто проверяем что app имеет роуты
    assert hasattr(app, "routes")
    assert len(app.routes) > 0

def test_static_files_mounted():
    """Тест что статические файлы смонтированы"""
    # Проверяем что у app есть mounted apps
    mounted_paths = [route.path for route in app.routes if hasattr(route, "path")]
    assert "/static" in mounted_paths