# tests/test_core/test_rate_limiter.py
import pytest
import threading
from unittest.mock import Mock, patch, AsyncMock
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.wrappers import LimitGroup

from app.core.rate_limiter import (
    limiter,
    custom_key_func,
    register_rate_limit_key,
    retry_after_seconds,
    reset_rate_limit_cache,
    check_redis_connection,
)
from redis.asyncio import RedisError


# ============================================================================
# ТЕСТЫ custom_key_func
# ============================================================================

def test_custom_key_func_with_user():
    """Тест: авторизованный пользователь → ключ по sub"""
    mock_request = Mock()
    mock_request.client.host = "192.168.1.100"
    mock_request.scope = {"user": Mock(sub="user123")}

    result = custom_key_func(mock_request)

    assert result == "rate_limit:user:user123"


def test_custom_key_func_without_user():
    """Тест: анонимный запрос → ключ по IP"""
    mock_request = Mock()
    mock_request.client.host = "192.168.1.100"
    mock_request.scope = {}

    with patch("app.core.rate_limiter.get_remote_address", return_value="192.168.1.100"):
        result = custom_key_func(mock_request)

    assert result == "rate_limit:ip:192.168.1.100"


def test_custom_key_func_user_without_sub():
    """Тест: объект user без атрибута sub → fallback на IP"""
    mock_request = Mock()
    mock_request.client.host = "10.0.0.1"
    mock_request.scope = {"user": object()}  # нет атрибута sub

    with patch("app.core.rate_limiter.get_remote_address", return_value="10.0.0.1"):
        result = custom_key_func(mock_request)

    assert result == "rate_limit:ip:10.0.0.1"


def test_custom_key_func_user_is_none():
    """Тест: user = None в scope → fallback на IP"""
    mock_request = Mock()
    mock_request.client.host = "10.0.0.2"
    mock_request.scope = {"user": None}

    with patch("app.core.rate_limiter.get_remote_address", return_value="10.0.0.2"):
        result = custom_key_func(mock_request)

    assert result == "rate_limit:ip:10.0.0.2"


def test_register_rate_limit_key():
    mock_request = Mock()
    mock_request.scope = {}

    with patch("app.core.rate_limiter.get_remote_address", return_value="203.0.113.7"):
        result = register_rate_limit_key(mock_request)

    assert result == "rate_limit:register:ip:203.0.113.7"


def test_retry_after_seconds_from_limit():
    from limits import parse

    limit_mock = Mock()
    limit_mock.limit = parse("3/hour")[0]
    exc = RateLimitExceeded(limit=limit_mock)

    assert retry_after_seconds(exc) == 3600


def test_retry_after_seconds_fallback():
    exc = RateLimitExceeded(limit=Mock(error_message="limited", limit=None))
    assert retry_after_seconds(exc) == 60


# ============================================================================
# ТЕСТ ИНИЦИАЛИЗАЦИИ ЛИМИТЕРА
# ============================================================================

def test_limiter_initialization():
    """Тест инициализации объекта Limiter"""
    assert limiter is not None
    assert isinstance(limiter, Limiter)
    assert limiter._key_func is custom_key_func

    # Хранилище — MemoryStorage
    storage_type = type(limiter._storage).__name__
    assert "Memory" in storage_type or "InMemory" in storage_type






# ============================================================================
# ТЕСТЫ Redis
# ============================================================================

@pytest.mark.asyncio
async def test_check_redis_connection_success():
    """Тест успешного подключения к Redis"""
    with patch("app.core.rate_limiter.redis_client") as mock_redis:
        mock_redis.ping = AsyncMock(return_value=True)

        await check_redis_connection()

        mock_redis.ping.assert_called_once()


@pytest.mark.asyncio
async def test_check_redis_connection_redis_error():
    """Тест: RedisError → RuntimeError"""
    with patch("app.core.rate_limiter.redis_client") as mock_redis:
        mock_redis.ping = AsyncMock(side_effect=RedisError("Connection refused"))

        with pytest.raises(RuntimeError, match="Redis connection failed"):
            await check_redis_connection()


@pytest.mark.asyncio
async def test_check_redis_connection_generic_error():
    """Тест: общее исключение → RuntimeError"""
    with patch("app.core.rate_limiter.redis_client") as mock_redis:
        mock_redis.ping = AsyncMock(side_effect=Exception("Unknown error"))

        with pytest.raises(RuntimeError, match="Redis init failed"):
            await check_redis_connection()


@pytest.mark.asyncio
async def test_reset_rate_limit_cache_success():
    """Тест успешного сброса кеша Redis"""
    with patch("app.core.rate_limiter.redis_client") as mock_redis:
        mock_redis.flushdb = AsyncMock(return_value=True)

        await reset_rate_limit_cache()

        mock_redis.flushdb.assert_called_once()


@pytest.mark.asyncio
async def test_reset_rate_limit_cache_redis_error():
    """Тест: RedisError логируется, не пробрасывается"""
    with patch("app.core.rate_limiter.redis_client") as mock_redis:
        mock_redis.flushdb = AsyncMock(side_effect=RedisError("Flush failed"))

        # Должно молча проглотить ошибку
        await reset_rate_limit_cache()

        mock_redis.flushdb.assert_called_once()


# ============================================================================
# ВСПОМОГАТЕЛЬНАЯ ФАБРИКА ТЕСТОВОГО ПРИЛОЖЕНИЯ
# ============================================================================

def _make_test_app(limit: str, key: str) -> FastAPI:
    """
    Создаёт изолированное FastAPI приложение для тестирования rate limit.

    Важно:
    - endpoint принимает `request: Request` с явной аннотацией типа fastapi.Request
      иначе FastAPI пытается парсить request из тела → 422
    - key_func — лямбда без замыкания на изменяемую переменную
    """
    test_app = FastAPI()
    # Создаём новый лимитер с фиксированным ключом
    test_limiter = Limiter(key_func=lambda request: key)
    test_app.state.limiter = test_limiter
    test_app.add_middleware(SlowAPIMiddleware)

    @test_app.get("/test")
    @test_limiter.limit(limit)
    async def test_endpoint(request: Request):  # ← тип Request обязателен
        return {"message": "success"}

    return test_app


# ============================================================================
# ИНТЕГРАЦИОННЫЕ ТЕСТЫ
# ============================================================================

def test_rate_limiter_integration():
    """Интеграционный тест: 429 после превышения лимита"""
    test_app = _make_test_app(limit="3/minute", key="integration_key_unique_1")
    client = TestClient(test_app, raise_server_exceptions=False)

    # Первые 3 — успешны
    for i in range(3):
        response = client.get("/test")
        assert response.status_code == 200, (
            f"Запрос {i + 1} должен быть успешным, получен: "
            f"{response.status_code} {response.text}"
        )

    # 4-й — превышение лимита
    response = client.get("/test")
    assert response.status_code == 429, (
        f"4-й запрос должен вернуть 429, получен: {response.status_code}"
    )


def test_rate_limiter_different_keys():
    """Тест: разные ключи имеют независимые счётчики"""
    app_a = _make_test_app(limit="2/minute", key="key_unique_client_A")
    app_b = _make_test_app(limit="2/minute", key="key_unique_client_B")

    client_a = TestClient(app_a, raise_server_exceptions=False)
    client_b = TestClient(app_b, raise_server_exceptions=False)

    # Исчерпываем лимит для A
    assert client_a.get("/test").status_code == 200
    assert client_a.get("/test").status_code == 200
    assert client_a.get("/test").status_code == 429, "key_A должен получить 429"

    # B независим и ещё не исчерпан
    assert client_b.get("/test").status_code == 200, "key_B — первый запрос успешен"
    assert client_b.get("/test").status_code == 200, "key_B — второй запрос успешен"
    assert client_b.get("/test").status_code == 429, "key_B — третий запрос даёт 429"


def test_concurrent_rate_limiting():
    """Тест конкурентного rate limiting"""
    test_app = _make_test_app(limit="5/minute", key="concurrent_key_unique")
    # raise_server_exceptions=False чтобы 429 не бросал исключение в тесте
    client = TestClient(test_app, raise_server_exceptions=False)

    results = []
    lock = threading.Lock()

    def make_request():
        response = client.get("/test")
        with lock:
            results.append(response.status_code)

    threads = [threading.Thread(target=make_request) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    successes = results.count(200)
    rate_limited = results.count(429)

    assert all(s in (200, 429) for s in results), (
        f"Ожидались только 200/429, получено: {set(results)}"
    )
    assert successes <= 5, f"Ожидалось ≤5 успешных, получено {successes}"
    assert rate_limited >= 5, f"Ожидалось ≥5 заблокированных, получено {rate_limited}"


def test_limiter_allows_requests_within_limit():
    """Тест: запросы в рамках лимита проходят, N+1 блокируется"""
    test_app = _make_test_app(limit="5/minute", key="within_limit_key_unique")
    client = TestClient(test_app, raise_server_exceptions=False)

    for i in range(5):
        response = client.get("/test")
        assert response.status_code == 200, (
            f"Запрос {i + 1} должен быть успешным, получен: "
            f"{response.status_code} {response.text}"
        )

    # 6-й — заблокирован
    response = client.get("/test")
    assert response.status_code == 429


# ============================================================================
# ТЕСТ КОНФИГУРАЦИИ
# ============================================================================

def test_limiter_configuration():
    """Тест конфигурации глобального лимитера"""
    assert limiter._key_func is custom_key_func

    storage_type = type(limiter._storage).__name__
    assert "Memory" in storage_type or "InMemory" in storage_type


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
