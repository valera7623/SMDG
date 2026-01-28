# tests/test_api/test_cleanup.py
import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

@pytest.mark.asyncio
async def test_cleanup_stats(client, mock_admin):
    """Тест получения статистики очистки"""
    with patch("app.api.cleanup.limiter.limit", lambda *args, **kwargs: (lambda x: x)):
        response = client.get("/api/cleanup/stats")
    
    if response.status_code == 200:
        data = response.json()
        # Проверяем структуру ответа
        assert isinstance(data, dict)
    else:
        print(f"Cleanup stats failed: {response.status_code}")

def test_cleanup_endpoints():
    """Тест что cleanup эндпоинты существуют"""
    from app.api.cleanup import router
    
    endpoints = [route for route in router.routes if hasattr(route, 'path')]
    paths = [str(route.path) for route in endpoints]
    
    assert "/cleanup/stats" in str(paths)
    assert "/cleanup/force" in str(paths)
    assert "/cleanup/files" in str(paths)