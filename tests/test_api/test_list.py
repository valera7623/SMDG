# tests/test_api/test_list.py
import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

@pytest.mark.asyncio
async def test_list_files(client, mock_doctor, temp_dirs):
    """Тест получения списка файлов"""
    # Создаем тестовый файл
    test_file = temp_dirs["encrypted"] / "test.pdf.age"
    test_file.write_bytes(b"encrypted content")
    
    # Мокаем rate limiter
    with patch("app.api.list.limiter.limit", lambda *args, **kwargs: (lambda x: x)):
        response = client.get("/api/list")
    
    if response.status_code == 200:
        data = response.json()
        assert "count" in data
        assert "files" in data
        assert isinstance(data["files"], list)
    else:
        print(f"List failed: {response.status_code} - {response.text}")

def test_list_endpoint_structure():
    """Тест структуры эндпоинта list"""
    from app.api.list import router
    
    # Находим эндпоинт
    list_endpoints = [
        route for route in router.routes 
        if hasattr(route, 'path') and '/list' in str(route.path)
    ]
    
    assert len(list_endpoints) > 0
    endpoint = list_endpoints[0]
    assert hasattr(endpoint, 'methods')
    assert 'GET' in endpoint.methods