# tests/test_core/test_rate_limiter.py
import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from app.core.rate_limiter import (
    limiter, 
    custom_key_func,  # изменено: get_remote_address -> custom_key_func
    reset_rate_limit_cache,
    # storage_backend - удаляем, его нет в модуле
)
from slowapi.errors import RateLimitExceeded


def test_custom_key_func_with_user():
    """Тест функции получения ключа с авторизованным пользователем"""
    mock_request = Mock()
    mock_request.client.host = "192.168.1.100"
    mock_request.scope = {"user": Mock(sub="user123")}
    
    result = custom_key_func(mock_request)
    
    assert result == "rate_limit:user:user123"


def test_custom_key_func_without_user():
    """Тест функции получения ключа без авторизованного пользователя"""
    mock_request = Mock()
    mock_request.client.host = "192.168.1.100"
    mock_request.scope = {}
    
    # Мокаем get_remote_address через патч
    with patch('app.core.rate_limiter.get_remote_address', return_value="192.168.1.100"):
        result = custom_key_func(mock_request)
    
    assert result == "rate_limit:ip:192.168.1.100"


def test_limiter_initialization():
    """Тест инициализации лимитера"""
    assert limiter is not None
    assert hasattr(limiter, '_storage')
    assert hasattr(limiter, 'key_func')
    
    # Проверяем лимиты по умолчанию
    assert limiter._default_limits == ["100/minute"]


@pytest.mark.asyncio
async def test_reset_rate_limit_cache():
    """Тест сброса кеша Redis (только Redis, rate limiter in-memory)"""
    with patch('app.core.rate_limiter.redis_client') as mock_redis:
        mock_redis.flushdb = AsyncMock()
        
        await reset_rate_limit_cache()
        
        mock_redis.flushdb.assert_called_once()


@pytest.mark.asyncio
async def test_reset_rate_limit_cache_error():
    """Тест ошибки при сбросе кеша"""
    with patch('app.core.rate_limiter.redis_client') as mock_redis:
        mock_redis.flushdb = AsyncMock()
        mock_redis.flushdb.side_effect = Exception("Redis error")
        
        # Не должно вызывать исключение (ошибка логируется)
        await reset_rate_limit_cache()


@pytest.mark.asyncio
async def test_rate_limiter_integration():
    """Интеграционный тест rate limiter (in-memory)"""
    # Создаем простую функцию с лимитом
    @limiter.limit("5/minute")
    async def limited_function(request):
        return {"message": "success"}
    
    mock_request = Mock()
    mock_request.client.host = "192.168.1.100"
    mock_request.scope = {}
    
    # Патчим custom_key_func для теста
    with patch('app.core.rate_limiter.custom_key_func', return_value="test_key"):
        # Вызываем 5 раз - должно быть успешно
        for i in range(5):
            result = await limited_function(mock_request)
            assert result["message"] == "success"
        
        # 6-й вызов должен превысить лимит
        with pytest.raises(RateLimitExceeded):
            await limited_function(mock_request)
    
    # Сбрасываем кеш Redis (не влияет на rate limiter, т.к. он in-memory)
    await reset_rate_limit_cache()


def test_limiter_configuration():
    """Тест конфигурации лимитера"""
    # Проверяем key_func
    assert limiter._key_func == custom_key_func
    
    # Проверяем что используется MemoryStorage
    storage_type = type(limiter._storage).__name__
    assert "Memory" in storage_type or "InMemory" in storage_type


@pytest.mark.asyncio
async def test_concurrent_rate_limiting():
    """Тест конкурентного rate limiting"""
    @limiter.limit("10/minute")
    async def concurrent_function(request):
        await asyncio.sleep(0.01)  # Небольшая задержка
        return {"count": 1}
    
    mock_request = Mock()
    mock_request.client.host = "192.168.1.100"
    mock_request.scope = {}
    
    # Патчим custom_key_func для теста
    with patch('app.core.rate_limiter.custom_key_func', return_value="test_key"):
        # Запускаем несколько конкурентных вызовов
        tasks = [concurrent_function(mock_request) for _ in range(15)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Подсчитываем успешные и неудачные
        successes = sum(1 for r in results if not isinstance(r, Exception))
        failures = sum(1 for r in results if isinstance(r, Exception))
        
        # Должно быть не больше 10 успешных (из-за лимита)
        assert successes <= 10
        assert failures >= 5


@pytest.mark.asyncio
async def test_rate_limiter_different_keys():
    """Тест rate limiter с разными ключами"""
    @limiter.limit("3/minute")
    async def limited_function(request):
        return {"message": "success"}
    
    # Создаем два разных запроса с разными ключами
    mock_request1 = Mock()
    mock_request1.client.host = "192.168.1.100"
    mock_request1.scope = {}
    
    mock_request2 = Mock()
    mock_request2.client.host = "192.168.1.101"
    mock_request2.scope = {}
    
    with patch('app.core.rate_limiter.custom_key_func') as mock_key_func:
        # Для первого запроса возвращаем ключ1
        mock_key_func.side_effect = lambda req: f"test_key_{req.client.host}"
        
        # Вызываем 3 раза для первого IP
        for i in range(3):
            result = await limited_function(mock_request1)
            assert result["message"] == "success"
        
        # 4-й вызов для первого IP должен превысить лимит
        with pytest.raises(RateLimitExceeded):
            await limited_function(mock_request1)
        
        # Для второго IP должно быть успешно (разные ключи)
        for i in range(3):
            result = await limited_function(mock_request2)
            assert result["message"] == "success"


if __name__ == "__main__":
    pytest.main([__file__])
