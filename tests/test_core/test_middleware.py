import pytest
from unittest.mock import Mock, AsyncMock, patch
from app.core.middleware import AuditMiddleware


@pytest.fixture
def middleware():
    """Создает AuditMiddleware для тестов"""
    return AuditMiddleware(Mock())


@pytest.mark.asyncio
async def test_audit_middleware_success_request(middleware):
    """Тест middleware для успешного запроса"""
    mock_request = Mock()
    mock_request.client.host = "192.168.1.100"
    mock_request.method = "GET"
    mock_request.url.path = "/api/test"
    mock_request.headers.get.return_value = "TestClient/1.0"

    mock_response = Mock()
    mock_response.status_code = 200

    mock_call_next = AsyncMock(return_value=mock_response)

    with patch('app.core.middleware.audit_logger') as mock_logger:
        response = await middleware.dispatch(mock_request, mock_call_next)

        mock_call_next.assert_called_once_with(mock_request)
        assert response == mock_response

        mock_logger.log_operation.assert_called_once()

        call_args = mock_logger.log_operation.call_args
        assert call_args[1]['action'] == "GET /api/test"
        assert call_args[1]['user'] == "api"
        assert call_args[1]['ip'] == "192.168.1.100"
        assert call_args[1]['success'] is True
        assert call_args[1]['metadata']['method'] == "GET"
        assert call_args[1]['metadata']['path'] == "/api/test"
        assert call_args[1]['metadata']['status'] == 200


@pytest.mark.asyncio
async def test_audit_middleware_error_request(middleware):
    """Тест middleware для запроса с ошибкой"""
    mock_request = Mock()
    mock_request.client.host = "192.168.1.100"
    mock_request.method = "POST"
    mock_request.url.path = "/api/upload"
    mock_request.headers.get.return_value = "TestClient/1.0"

    mock_response = Mock()
    mock_response.status_code = 413  # Payload Too Large

    mock_call_next = AsyncMock(return_value=mock_response)

    with patch('app.core.middleware.audit_logger') as mock_logger:
        response = await middleware.dispatch(mock_request, mock_call_next)

        mock_logger.log_operation.assert_called_once()

        call_args = mock_logger.log_operation.call_args
        assert call_args[1]['success'] is False
        assert call_args[1]['metadata']['status'] == 413


@pytest.mark.asyncio
async def test_audit_middleware_no_user_agent(middleware):
    """Тест middleware без User-Agent заголовка"""
    mock_request = Mock()
    mock_request.client.host = "192.168.1.100"
    mock_request.method = "GET"
    mock_request.url.path = "/"
    # headers.get() возвращает None — симулируем отсутствие заголовка
    mock_request.headers.get.return_value = None

    mock_response = Mock()
    mock_response.status_code = 200

    mock_call_next = AsyncMock(return_value=mock_response)

    with patch('app.core.middleware.audit_logger') as mock_logger:
        response = await middleware.dispatch(mock_request, mock_call_next)

        mock_logger.log_operation.assert_called_once()

        call_args = mock_logger.log_operation.call_args
        assert "user_agent" in call_args[1]['metadata']
        # FIX: middleware заменяет None на "unknown"
        assert call_args[1]['metadata']['user_agent'] == "unknown"


@pytest.mark.asyncio
async def test_audit_middleware_long_user_agent(middleware):
    """Тест middleware с длинным User-Agent"""
    mock_request = Mock()
    mock_request.client.host = "192.168.1.100"
    mock_request.method = "GET"
    mock_request.url.path = "/"

    long_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " + "A" * 200
    mock_request.headers.get.return_value = long_ua

    mock_response = Mock()
    mock_response.status_code = 200

    mock_call_next = AsyncMock(return_value=mock_response)

    with patch('app.core.middleware.audit_logger') as mock_logger:
        response = await middleware.dispatch(mock_request, mock_call_next)

        mock_logger.log_operation.assert_called_once()

        call_args = mock_logger.log_operation.call_args
        reason = call_args[1]['reason']
        assert len(reason.split("UA: ")[1]) <= 100


@pytest.mark.asyncio
async def test_audit_middleware_different_methods(middleware):
    """Тест middleware с разными HTTP методами"""
    test_cases = [
        ("GET", 200),
        ("POST", 201),
        ("PUT", 200),
        ("DELETE", 204),
        ("PATCH", 200),
    ]

    for method, status_code in test_cases:
        mock_request = Mock()
        mock_request.client.host = "192.168.1.100"
        mock_request.method = method
        mock_request.url.path = f"/api/{method.lower()}"
        mock_request.headers.get.return_value = "TestClient/1.0"

        mock_response = Mock()
        mock_response.status_code = status_code

        mock_call_next = AsyncMock(return_value=mock_response)

        with patch('app.core.middleware.audit_logger') as mock_logger:
            response = await middleware.dispatch(mock_request, mock_call_next)

            call_args = mock_logger.log_operation.call_args
            assert call_args[1]['action'] == f"{method} /api/{method.lower()}"
            assert call_args[1]['metadata']['method'] == method
            assert call_args[1]['metadata']['status'] == status_code


@pytest.mark.asyncio
async def test_audit_middleware_exception_in_next(middleware):
    """Тест middleware когда next вызывает исключение"""
    mock_request = Mock()
    mock_request.client.host = "192.168.1.100"
    mock_request.method = "GET"
    mock_request.url.path = "/api/error"
    mock_request.headers.get.return_value = "TestClient/1.0"

    mock_call_next = AsyncMock(side_effect=Exception("Internal server error"))

    with patch('app.core.middleware.audit_logger') as mock_logger:
        # FIX: исключение должно пробрасываться наружу (raise в except)
        with pytest.raises(Exception, match="Internal server error"):
            await middleware.dispatch(mock_request, mock_call_next)

        # После исключения лог должен быть записан
        mock_logger.log_operation.assert_called_once()

        call_args = mock_logger.log_operation.call_args
        assert call_args[1]['success'] is False
        assert "Internal server error" in call_args[1]['reason']


def test_middleware_initialization():
    """Тест инициализации middleware"""
    mock_app = Mock()
    middleware = AuditMiddleware(mock_app)

    assert middleware.app == mock_app
    assert hasattr(middleware, 'dispatch')


if __name__ == "__main__":
    pytest.main([__file__])
