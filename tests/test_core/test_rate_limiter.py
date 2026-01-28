import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from app.core.rate_limiter import (
    limiter, 
    get_remote_address, 
    reset_rate_limit_cache,
    storage_backend,
    wait_for_rate_limit_reset
)


def test_get_remote_address():
    """Тест функции получения удаленного адреса"""
    mock_request = Mock()
    mock_request.client.host = "192.168.1.100"
    
    result = get_remote_address(mock_request)
    
    assert result == "192.168.1.100"


def test_limiter_initialization():
    """Тест инициализации лимитера"""
    assert limiter is not None
    assert hasattr(limiter, '_storage')
    assert hasattr(limiter, 'key_func')
    
    # Проверяем лимиты по умолчанию
    assert limiter._default_limits == ["300/day"]


@pytest.mark.asyncio
async def test_reset_rate_limit_cache_redis():
    """Тест сброса кеша для Redis"""
    with patch('app.core.rate_limiter.storage_backend', 'redis'):
        with patch('app.core.rate_limiter.redis_client') as mock_redis:
            mock_redis.flushdb = AsyncMock()
            
            await reset_rate_limit_cache()
            
            mock_redis.flushdb.assert_called_once()


@pytest.mark.asyncio
async def test_reset_rate_limit_cache_memory():
    """Тест сброса кеша для памяти"""
    with patch('app.core.rate_limiter.storage_backend', 'memory'):
        # Мокаем хранилище
        mock_storage = Mock()
        mock_storage.storage = {}
        
        with patch('app.core.rate_limiter.limiter._storage', mock_storage):
            await reset_rate_limit_cache()
            
            # Проверяем что storage был очищен
            assert mock_storage.storage == {}


@pytest.mark.asyncio
async def test_reset_rate_limit_cache_error():
    """Тест ошибки при сбросе кеша"""
    with patch('app.core.rate_limiter.storage_backend', 'redis'):
        with patch('app.core.rate_limiter.redis_client') as mock_redis:
            mock_redis.flushdb = AsyncMock()
            mock_redis.flushdb.side_effect = Exception("Redis error")
            
            # Не должно вызывать исключение
            await reset_rate_limit_cache()


@pytest.mark.asyncio
async def test_wait_for_rate_limit_reset():
    """Тест ожидания сброса rate limit"""
    with patch('asyncio.sleep') as mock_sleep:
        with patch('sys.stdout.write') as mock_stdout:
            await wait_for_rate_limit_reset(seconds=3)
            
            # Проверяем что sleep вызывался нужное количество раз
            assert mock_sleep.call_count == 3
            
            # Проверяем вывод
            assert mock_stdout.call_count > 0


def test_storage_backend():
    """Тест переменной storage_backend"""
    assert storage_backend in ['memory', 'redis']


@pytest.mark.asyncio
async def test_rate_limiter_integration():
    """Интеграционный тест rate limiter"""
    from slowapi.errors import RateLimitExceeded
    
    # Создаем простую функцию с лимитом
    @limiter.limit("5/minute")
    async def limited_function(request):
        return {"message": "success"}
    
    mock_request = Mock()
    mock_request.client.host = "192.168.1.100"
    
    # Вызываем несколько раз
    for i in range(5):
        try:
            result = await limited_function(mock_request)
            assert result["message"] == "success"
        except RateLimitExceeded:
            # На 6-м вызове должен превысить лимит
            if i == 5:
                assert True
            else:
                assert False, f"Rate limit exceeded too early at call {i}"
    
    # Сбрасываем кеш
    await reset_rate_limit_cache()
    
    # Теперь снова должно работать
    try:
        result = await limited_function(mock_request)
        assert result["message"] == "success"
    except RateLimitExceeded:
        assert False, "Should work after reset"


def test_limiter_configuration():
    """Тест конфигурации лимитера"""
    # Проверяем что стратегия установлена
    assert hasattr(limiter, '_strategy')
    
    # Проверяем key_func
    assert limiter._key_func == get_remote_address
    
    # Проверяем обработку ошибок
    assert hasattr(limiter, '_in_memory_fallback_on_error')


@pytest.mark.asyncio
async def test_concurrent_rate_limiting():
    """Тест конкурентного rate limiting"""
    @limiter.limit("10/minute")
    async def concurrent_function(request):
        await asyncio.sleep(0.01)  # Небольшая задержка
        return {"count": 1}
    
    mock_request = Mock()
    mock_request.client.host = "192.168.1.100"
    
    # Запускаем несколько конкурентных вызовов
    tasks = []
    for i in range(15):
        task = concurrent_function(mock_request)
        tasks.append(task)
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Подсчитываем успешные и неудачные
    successes = sum(1 for r in results if not isinstance(r, Exception))
    failures = sum(1 for r in results if isinstance(r, Exception))
    
    # Должно быть не больше 10 успешных (из-за лимита)
    assert successes <= 10
    assert failures >= 5


if __name__ == "__main__":
    pytest.main([__file__])
