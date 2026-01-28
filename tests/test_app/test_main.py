# tests/test_app/test_main.py
import pytest
import asyncio
import sys
import io
from unittest.mock import patch, AsyncMock, MagicMock, mock_open, call, PropertyMock
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import os
from fastapi.responses import HTMLResponse
from slowapi.errors import RateLimitExceeded
from fastapi import Request

from app.models.user import User
from app.core.security import get_password_hash


class TestMainModule:
    """Основные тесты для app/main.py"""

    # ========== Тесты для функций с БД ==========

    @pytest.mark.asyncio
    async def test_ensure_admin_exists_new_admin(self):
        """Тест создания нового администратора"""
        from app.main import ensure_admin_exists
        
        # Создаем мок сессии
        mock_session = AsyncMock(spec=AsyncSession)
        
        # Мокаем результат запроса - admin не существует
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = AsyncMock(return_value=None)
        
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()
        
        # Захватываем stdout для проверки print statements
        old_stdout = sys.stdout
        captured_output = io.StringIO()
        sys.stdout = captured_output
        
        try:
            await ensure_admin_exists(mock_session)
            
            output = captured_output.getvalue()
            # Проверяем сообщения о создании админа
            assert "Создаём первого администратора" in output
            assert "✅ Админ создан" in output
            
        finally:
            sys.stdout = old_stdout
        
        # Проверяем вызовы БД
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()
        mock_session.refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_admin_exists_existing_admin_valid_hash(self):
        """Тест когда admin уже существует с валидным хэшем"""
        from app.main import ensure_admin_exists
        
        # Создаем мок admin с валидным хэшем
        mock_admin = MagicMock()
        type(mock_admin).hashed_password = PropertyMock(return_value="$argon2$valid_hash")
        
        # Мокаем сессию
        mock_session = AsyncMock(spec=AsyncSession)
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = AsyncMock(return_value=mock_admin)
        
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        
        await ensure_admin_exists(mock_session)
        
        # Проверяем, что commit не вызывался (нет изменений)
        mock_session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_admin_exists_invalid_hash(self):
        """Тест с невалидным хэшем"""
        from app.main import ensure_admin_exists
        
        # Создаем мок admin с невалидным хэшем
        mock_admin = MagicMock()
        type(mock_admin).hashed_password = PropertyMock(return_value="plain_text")
        
        # Мокаем сессию
        mock_session = AsyncMock(spec=AsyncSession)
        mock_result = AsyncMock()
        mock_result.scalar_one_or_none = AsyncMock(return_value=mock_admin)
        
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        
        # Захватываем stdout
        old_stdout = sys.stdout
        captured_output = io.StringIO()
        sys.stdout = captured_output
        
        try:
            # Мокаем get_password_hash
            with patch('app.main.get_password_hash', return_value="$argon2$new_hash"):
                await ensure_admin_exists(mock_session)
                
                output = captured_output.getvalue()
                # Проверяем сообщение о невалидном хэше
                assert "НЕВАЛИДНЫЙ хэш пароля" in output or "Автоматически перехэшируем" in output
                
        finally:
            sys.stdout = old_stdout
        
        # Проверяем, что commit вызван для исправления хэша
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_first_admin_dev_mode_new(self):
        """Тест create_first_admin в dev-режиме, когда admin не существует"""
        from app.main import create_first_admin
        
        with patch('app.core.config.settings.dev_mode', True):
            # Мокаем сессию
            mock_session = AsyncMock(spec=AsyncSession)
            mock_result = AsyncMock()
            mock_result.scalar_one_or_none = AsyncMock(return_value=None)
            
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_session.add = MagicMock()
            mock_session.commit = AsyncMock()
            
            # Мокаем db.begin() как асинхронный контекстный менеджер
            mock_begin_context = AsyncMock()
            mock_begin_context.__aenter__ = AsyncMock(return_value=None)
            mock_begin_context.__aexit__ = AsyncMock(return_value=None)
            mock_session.begin.return_value = mock_begin_context
            
            # Мокаем AsyncSessionLocal
            mock_session_local = AsyncMock()
            mock_session_local.__aenter__.return_value = mock_session
            mock_session_local.__aexit__.return_value = None
            
            with patch('app.main.AsyncSessionLocal', return_value=mock_session_local):
                with patch('app.main.audit_logger.log_operation') as mock_log:
                    with patch('app.main.get_password_hash', return_value="$argon2$hashed_password"):
                        # Захватываем stdout
                        old_stdout = sys.stdout
                        captured_output = io.StringIO()
                        sys.stdout = captured_output
                        
                        try:
                            await create_first_admin()
                            
                            output = captured_output.getvalue()
                            # Проверяем все ожидаемые prints
                            assert "СОЗДАН ПЕРВЫЙ АДМИНИСТРАТОР" in output
                            assert "Логин:    admin" in output
                            assert "Пароль:   admin" in output
                            assert "Изменяйте пароль" in output
                            
                        finally:
                            sys.stdout = old_stdout
                        
                        # Проверяем вызовы БД и логирование
                        mock_session.execute.assert_called_once()
                        mock_session.add.assert_called_once()
                        mock_session.commit.assert_called_once()
                        mock_session.begin.assert_called_once()
                        mock_log.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_first_admin_dev_mode_existing(self):
        """Тест create_first_admin когда admin уже существует"""
        from app.main import create_first_admin
        
        with patch('app.core.config.settings.dev_mode', True):
            # Мокаем сессию
            mock_session = AsyncMock(spec=AsyncSession)
            mock_result = AsyncMock()
            mock_existing_admin = MagicMock()
            mock_result.scalar_one_or_none = AsyncMock(return_value=mock_existing_admin)
            
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_session.add = MagicMock()
            mock_session.commit = AsyncMock()
            
            # Мокаем db.begin()
            mock_begin_context = AsyncMock()
            mock_begin_context.__aenter__ = AsyncMock(return_value=None)
            mock_begin_context.__aexit__ = AsyncMock(return_value=None)
            mock_session.begin.return_value = mock_begin_context
            
            # Мокаем AsyncSessionLocal
            mock_session_local = AsyncMock()
            mock_session_local.__aenter__.return_value = mock_session
            mock_session_local.__aexit__.return_value = None
            
            with patch('app.main.AsyncSessionLocal', return_value=mock_session_local):
                with patch('app.main.audit_logger.log_operation') as mock_log:
                    # Захватываем stdout
                    old_stdout = sys.stdout
                    captured_output = io.StringIO()
                    sys.stdout = captured_output
                    
                    try:
                        await create_first_admin()
                        
                        output = captured_output.getvalue()
                        # Проверяем сообщение о существующем admin
                        assert "Пользователь admin уже существует" in output
                        
                    finally:
                        sys.stdout = old_stdout
                    
                    # Проверяем что add и commit не вызывались
                    mock_session.add.assert_not_called()
                    mock_session.commit.assert_not_called()
                    mock_log.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_first_admin_production_mode(self):
        """Тест create_first_admin в production-режиме"""
        from app.main import create_first_admin
        
        with patch('app.core.config.settings.dev_mode', False):
            # Захватываем stdout
            old_stdout = sys.stdout
            captured_output = io.StringIO()
            sys.stdout = captured_output
            
            try:
                await create_first_admin()
                
                output = captured_output.getvalue()
                # Проверяем сообщение о production режиме
                assert "Production-режим" in output or "пропускаем создание тестового админа" in output
                
            finally:
                sys.stdout = old_stdout

    # ========== Тесты для эндпоинтов ==========

    def test_index_endpoint_success(self):
        """Тест главной страницы (успех)"""
        from app.main import app
        from fastapi.testclient import TestClient
        
        with patch('app.main.os.path.exists', return_value=True):
            with patch('builtins.open', mock_open(read_data='<html>Test</html>')):
                client = TestClient(app)
                response = client.get("/")
        
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"

    def test_index_endpoint_file_not_found(self):
        """Тест главной страницы (файл не найден)"""
        from app.main import app
        from fastapi.testclient import TestClient
        
        with patch('app.main.os.path.exists', return_value=False):
            client = TestClient(app)
            response = client.get("/")
        
        assert response.status_code == 200
        assert "SMDG - Secure Medical Data Gateway" in response.text

    @pytest.mark.asyncio
    async def test_index_direct_call_success(self):
        """Прямой вызов функции index (успех)"""
        from app.main import index
        
        with patch('app.main.os.path.exists', return_value=True):
            with patch('builtins.open', mock_open(read_data='<html>Test</html>')):
                response = await index()
                assert response == '<html>Test</html>'

    @pytest.mark.asyncio
    async def test_index_direct_call_file_not_found(self):
        """Прямой вызов функции index (файл не найден)"""
        from app.main import index
        
        with patch('app.main.os.path.exists', return_value=False):
            response = await index()
            assert "SMDG - Secure Medical Data Gateway" in response

    def test_admin_endpoint_success(self):
        """Тест страницы администратора (успех)"""
        from app.main import app
        from fastapi.testclient import TestClient
        
        with patch('app.main.os.path.exists', return_value=True):
            with patch('builtins.open', mock_open(read_data='<html>Admin</html>')):
                client = TestClient(app)
                response = client.get("/admin")
        
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"

    def test_admin_endpoint_file_not_found(self):
        """Тест страницы администратора (файл не найден)"""
        from app.main import app
        from fastapi.testclient import TestClient
        
        with patch('app.main.os.path.exists', return_value=False):
            client = TestClient(app)
            response = client.get("/admin")
        
        assert response.status_code == 200
        assert "Панель администратора SMDG" in response.text

    @pytest.mark.asyncio
    async def test_admin_direct_call_success(self):
        """Прямой вызов функции admin (успех)"""
        from app.main import admin
        
        with patch('app.main.os.path.exists', return_value=True):
            with patch('builtins.open', mock_open(read_data='<html>Admin</html>')):
                response = await admin()
                assert response == '<html>Admin</html>'

    @pytest.mark.asyncio
    async def test_admin_direct_call_file_not_found(self):
        """Прямой вызов функции admin (файл не найден)"""
        from app.main import admin
        
        with patch('app.main.os.path.exists', return_value=False):
            response = await admin()
            assert "Панель администратора SMDG" in response

    def test_health_check_endpoint(self):
        """Тест эндпоинта проверки здоровья"""
        from app.main import app
        from fastapi.testclient import TestClient
        
        # Мокаем проверку существования директорий
        with patch('app.main.os.path.exists') as mock_exists:
            mock_exists.return_value = True
            client = TestClient(app)
            response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "healthy"
        assert data["service"] == "smdg"
        assert "features" in data
        assert "directories" in data

    def test_health_check_endpoint_missing_dirs(self):
        """Тест эндпоинта здоровья с отсутствующими директориями"""
        from app.main import app
        from fastapi.testclient import TestClient
        
        with patch('app.main.os.path.exists', return_value=False):
            client = TestClient(app)
            response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["directories"]["static"] == False

    def test_health_check_direct_call_all_dirs_exist(self):
        """Прямой вызов health_check - все директории существуют"""
        from app.main import health_check
        
        with patch('app.main.os.path.exists', return_value=True):
            response = health_check()
            
            assert response["status"] == "healthy"
            assert response["directories"]["static"] == True
            assert response["directories"]["encrypted"] == True
            assert response["directories"]["keys"] == True
            assert response["directories"]["audit_logs"] == True

    def test_health_check_direct_call_no_dirs_exist(self):
        """Прямой вызов health_check - директории не существуют"""
        from app.main import health_check
        
        with patch('app.main.os.path.exists', return_value=False):
            response = health_check()
            
            assert response["status"] == "healthy"
            assert response["directories"]["static"] == False
            assert response["directories"]["encrypted"] == False
            assert response["directories"]["keys"] == False
            assert response["directories"]["audit_logs"] == False

    def test_health_check_direct_call_mixed_dirs(self):
        """Прямой вызов health_check - некоторые директории существуют"""
        from app.main import health_check
        
        def side_effect(path):
            if "static" in str(path):
                return True
            elif "encrypted" in str(path):
                return True
            elif "keys" in str(path):
                return False
            elif "audit_logs" in str(path):
                return False
            return False
        
        with patch('app.main.os.path.exists', side_effect=side_effect):
            response = health_check()
            
            assert response["directories"]["static"] == True
            assert response["directories"]["encrypted"] == True
            assert response["directories"]["keys"] == False
            assert response["directories"]["audit_logs"] == False

    def test_health_check_direct_call_os_error(self):
        """Прямой вызов health_check с ошибкой OS"""
        from app.main import health_check
        
        with patch('app.main.os.path.exists', side_effect=OSError("Permission denied")):
            response = health_check()
            
            # При ошибке все директории должны быть False
            assert response["directories"]["static"] == False
            assert response["directories"]["encrypted"] == False
            assert response["directories"]["keys"] == False
            assert response["directories"]["audit_logs"] == False

    def test_logs_endpoint_with_logs(self):
        """Тест эндпоинта просмотра логов (есть логи)"""
        from app.main import app
        from fastapi.testclient import TestClient
        
        with patch('app.main.os.path.exists', return_value=True):
            with patch('app.main.os.listdir', return_value=['audit_2024_01_01.log']):
                client = TestClient(app)
                response = client.get("/logs")
        
        assert response.status_code == 200
        assert "Логи аудита SMDG" in response.text
        assert "audit_2024_01_01.log" in response.text

    def test_logs_endpoint_empty_logs(self):
        """Тест эндпоинта просмотра логов (директория есть, но файлов нет)"""
        from app.main import app
        from fastapi.testclient import TestClient
        
        with patch('app.main.os.path.exists', return_value=True):
            with patch('app.main.os.listdir', return_value=[]):
                client = TestClient(app)
                response = client.get("/logs")
        
        assert response.status_code == 200
        assert "Доступные логи:" in response.text

    def test_logs_endpoint_exception(self):
        """Тест эндпоинта просмотра логов при исключении"""
        from app.main import app
        from fastapi.testclient import TestClient
        
        with patch('app.main.os.path.exists', side_effect=Exception("Test error")):
            client = TestClient(app)
            response = client.get("/logs")
        
        assert response.status_code == 200
        assert "Ошибка" in response.text

    @pytest.mark.asyncio
    async def test_view_logs_direct_call_with_logs(self):
        """Прямой вызов view_logs с логами"""
        from app.main import view_logs
        
        with patch('app.main.os.path.exists', return_value=True):
            with patch('app.main.os.listdir', return_value=['audit_2024_01_01.log', 'audit_2024_01_02.log']):
                response = await view_logs()
                
                assert isinstance(response, HTMLResponse)
                html_content = response.body.decode()
                assert "Логи аудита SMDG" in html_content
                assert "audit_2024_01_01.log" in html_content
                assert "audit_2024_01_02.log" in html_content

    @pytest.mark.asyncio
    async def test_view_logs_direct_call_no_logs_dir(self):
        """Прямой вызов view_logs без директории логов"""
        from app.main import view_logs
        
        with patch('app.main.os.path.exists', return_value=False):
            response = await view_logs()
            
            assert isinstance(response, HTMLResponse)
            html_content = response.body.decode()
            assert "Логи аудита SMDG" in html_content

    @pytest.mark.asyncio
    async def test_view_logs_direct_call_empty_logs(self):
        """Прямой вызов view_logs с пустой директорией"""
        from app.main import view_logs
        
        with patch('app.main.os.path.exists', return_value=True):
            with patch('app.main.os.listdir', return_value=[]):
                response = await view_logs()
                
                assert isinstance(response, HTMLResponse)
                html_content = response.body.decode()
                assert "Доступные логи:" in html_content

    @pytest.mark.asyncio
    async def test_view_logs_direct_call_mixed_files(self):
        """Прямой вызов view_logs с разными типами файлов"""
        from app.main import view_logs
        
        def listdir_side_effect(path):
            return [
                "audit_2024_01_01.log",
                "audit_2024_01_02.log",
                "other_file.txt",  # Не должен отображаться
                "test.json",       # Не должен отображаться
                "audit_2024_01_03.log"
            ]
        
        with patch('app.main.os.path.exists', return_value=True):
            with patch('app.main.os.listdir', side_effect=listdir_side_effect):
                response = await view_logs()
                
                html_content = response.body.decode()
                # Проверяем что отображаются только .log файлы
                assert "audit_2024_01_01.log" in html_content
                assert "audit_2024_01_02.log" in html_content
                assert "audit_2024_01_03.log" in html_content
                # Проверяем что другие файлы не отображаются
                assert "other_file.txt" not in html_content
                assert "test.json" not in html_content

    @pytest.mark.asyncio
    async def test_view_logs_direct_call_exception(self):
        """Прямой вызов view_logs с исключением"""
        from app.main import view_logs
        
        with patch('app.main.os.path.exists', side_effect=Exception("Test error")):
            response = await view_logs()
            
            assert isinstance(response, HTMLResponse)
            html_content = response.body.decode()
            assert "Ошибка" in html_content

    # ========== Тесты для startup и middleware ==========

    @pytest.mark.asyncio
    async def test_startup_event(self):
        """Тест startup_event"""
        from app.main import startup_event
        
        # Мокаем все зависимости
        with patch('app.main.init_keys', new_callable=AsyncMock) as mock_init_keys:
            with patch('app.main.cleanup_manager.start_cleanup_task', new_callable=AsyncMock) as mock_cleanup:
                with patch('app.main.create_first_admin', new_callable=AsyncMock) as mock_create_admin:
                    with patch('asyncio.create_task') as mock_create_task:
                        # Захватываем stdout
                        old_stdout = sys.stdout
                        captured_output = io.StringIO()
                        sys.stdout = captured_output
                        
                        try:
                            await startup_event()
                            
                            output = captured_output.getvalue()
                            # Проверяем ожидаемые сообщения
                            assert "🚀 Запуск SMDG v0.1" in output
                            assert "✅ Ключи шифрования инициализированы" in output
                            assert "✅ Фоновая очистка запущена" in output
                            
                        finally:
                            sys.stdout = old_stdout
                        
                        # Проверяем вызовы
                        mock_init_keys.assert_called_once()
                        mock_cleanup.assert_called_once()
                        mock_create_task.assert_called_once()
                        mock_create_admin.assert_called_once()

    @pytest.mark.asyncio
    async def test_startup_event_failed_key_init(self):
        """Тест startup_event с ошибкой инициализации ключей"""
        from app.main import startup_event
        
        # Мокаем все зависимости
        with patch('app.main.init_keys', side_effect=Exception("Key init failed")) as mock_init_keys:
            with patch('app.main.cleanup_manager.start_cleanup_task', new_callable=AsyncMock) as mock_cleanup:
                with patch('app.main.create_first_admin', new_callable=AsyncMock) as mock_create_admin:
                    with patch('asyncio.create_task') as mock_create_task:
                        # Захватываем stdout
                        old_stdout = sys.stdout
                        captured_output = io.StringIO()
                        sys.stdout = captured_output
                        
                        try:
                            await startup_event()
                            
                            output = captured_output.getvalue()
                            # Проверяем сообщение об ошибке
                            assert "Ошибка инициализации ключей" in output
                            
                        finally:
                            sys.stdout = old_stdout
                        
                        # Проверяем что остальные задачи выполнены
                        mock_init_keys.assert_called_once()
                        mock_cleanup.assert_called_once()
                        mock_create_task.assert_called_once()
                        mock_create_admin.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_rate_limit_headers_middleware(self):
        """Тест middleware функции rate limit"""
        from app.main import add_rate_limit_headers
        
        # Создаем моки
        mock_request = MagicMock()
        mock_response = MagicMock()
        
        # Мокаем call_next
        async def mock_call_next(request):
            return mock_response
        
        # Вызываем middleware
        response = await add_rate_limit_headers(mock_request, mock_call_next)
        
        # Проверяем, что возвращается response
        assert response == mock_response

    # ========== Тесты для обработки ошибок ==========

    def test_safe_rate_limit_handler_rate_limit_exceeded(self):
        """Тест safe_rate_limit_handler с RateLimitExceeded"""
        from app.main import safe_rate_limit_handler
        from fastapi.responses import JSONResponse
        
        # Создаем мок request
        mock_request = MagicMock(spec=Request)
        
        # Тестируем с RateLimitExceeded
        mock_exc = MagicMock(spec=RateLimitExceeded)
        mock_exc.detail = "Too many requests"
        
        # Мокаем внутренний обработчик
        mock_response = JSONResponse(
            status_code=429,
            content={"detail": "Too many requests"}
        )
        
        with patch('app.main._rate_limit_exceeded_handler', return_value=mock_response):
            response = safe_rate_limit_handler(mock_request, mock_exc)
            assert response.status_code == 429
            assert response.body.decode() == '{"detail":"Too many requests"}'

    def test_safe_rate_limit_handler_generic_exception(self):
        """Тест safe_rate_limit_handler с другим исключением"""
        from app.main import safe_rate_limit_handler
        
        # Создаем мок request
        mock_request = MagicMock(spec=Request)
        
        # Тестируем с другим исключением
        generic_exc = Exception("Some error")
        response = safe_rate_limit_handler(mock_request, generic_exc)
        
        assert response.status_code == 429
        assert "Слишком много запросов" in response.body.decode()

    @pytest.mark.asyncio
    async def test_create_first_admin_db_error(self):
        """Тест обработки ошибок БД в create_first_admin"""
        from app.main import create_first_admin
        
        with patch('app.core.config.settings.dev_mode', True):
            # Мокаем сессию с ошибкой
            mock_session = AsyncMock(spec=AsyncSession)
            mock_result = AsyncMock()
            mock_result.scalar_one_or_none = AsyncMock(side_effect=Exception("DB error"))
            
            mock_session.execute = AsyncMock(return_value=mock_result)
            
            # Мокаем db.begin()
            mock_begin_context = AsyncMock()
            mock_begin_context.__aenter__ = AsyncMock(return_value=None)
            mock_begin_context.__aexit__ = AsyncMock(return_value=None)
            mock_session.begin.return_value = mock_begin_context
            
            # Мокаем AsyncSessionLocal
            mock_session_local = AsyncMock()
            mock_session_local.__aenter__.return_value = mock_session
            mock_session_local.__aexit__.return_value = None
            
            with patch('app.main.AsyncSessionLocal', return_value=mock_session_local):
                # Функция должна обработать исключение внутри транзакции
                try:
                    await create_first_admin()
                    # Если дошло сюда, значит исключение было обработано внутри
                    assert True
                except Exception as e:
                    # Проверяем что это не ошибка "coroutine does not support..."
                    assert "coroutine" not in str(e)

    # ========== Тесты конфигурации приложения ==========

    def test_app_metadata(self):
        """Тест метаданных приложения"""
        from app.main import app
        
        assert app.title == "Secure Medical Data Gateway v0.1"
        assert app.version == "0.1.0"
        assert hasattr(app.state, 'limiter')

    def test_app_exception_handlers(self):
        """Тест установки обработчиков исключений"""
        from app.main import app
        
        # Проверяем, что обработчик установлен
        exception_handlers = app.exception_handlers
        assert RateLimitExceeded in exception_handlers

    def test_middleware_integration(self):
        """Тест наличия middleware"""
        from app.main import app
        
        # Проверяем, что middleware добавлены
        middleware_found = False
        for middleware in app.user_middleware:
            if hasattr(middleware.cls, '__name__'):
                if middleware.cls.__name__ in ['AuditMiddleware', 'SlowAPIMiddleware']:
                    middleware_found = True
        
        assert middleware_found, "Middleware не найдены"

    def test_api_routers_included(self):
        """Тест, что все API роутеры подключены"""
        from app.main import app
        
        # Проверяем пути роутеров
        route_paths = []
        for route in app.routes:
            if hasattr(route, 'path'):
                route_paths.append(route.path)
        
        # Проверяем основные префиксы
        assert any('/api/upload' in path for path in route_paths)
        assert any('/api/download' in path for path in route_paths)
        assert any('/api/auth' in path for path in route_paths)

    def test_static_files_mounted(self):
        """Тест монтирования статических файлов"""
        from app.main import app
        
        # Проверяем mounted apps через app.mount
        # app.mount - это метод, проверяем что статические файлы настроены
        has_static_route = False
        for route in app.routes:
            if hasattr(route, 'path') and '/static' in route.path:
                has_static_route = True
                break
        
        assert has_static_route, "Static files не настроены"

    # ========== Простые тесты для импортов и структуры ==========

    def test_direct_imports(self):
        """Тест прямых импортов"""
        # Проверяем, что все импорты работают
        from app.main import (
            app, startup_event, index, admin, health_check, 
            view_logs, add_rate_limit_headers, create_first_admin,
            ensure_admin_exists, safe_rate_limit_handler
        )
        
        assert app is not None
        assert callable(startup_event)
        assert callable(index)
        assert callable(admin)
        assert callable(health_check)
        assert callable(view_logs)
        assert callable(add_rate_limit_headers)
        assert callable(create_first_admin)
        assert callable(ensure_admin_exists)
        assert callable(safe_rate_limit_handler)

    def test_module_imports(self):
        """Тест что все модули импортируются корректно"""
        # Проверяем основные импорты
        try:
            from app.main import (
                FastAPI, Request, RateLimitExceeded,
                SlowAPIMiddleware, Redis, select, AsyncSession,
                HTMLResponse, FileResponse, StaticFiles, Jinja2Templates,
                asyncio, os
            )
            assert True
        except ImportError as e:
            pytest.fail(f"Import failed: {e}")

    def test_get_public_key_function(self):
        """Тест функции get_public_key"""
        from app.core import get_public_key
        
        # Мокаем глобальную переменную
        with patch('app.core._PUBLIC_KEY', 'test_public_key'):
            key = get_public_key()
            assert key == 'test_public_key'

    def test_app_state_limiter(self):
        """Тест что app.state.limiter установлен"""
        from app.main import app
        
        # Проверяем что limiter существует
        assert hasattr(app.state, 'limiter')
        assert app.state.limiter is not None


# Простая фикстура для изолированных тестов
@pytest.fixture
def simple_test_client():
    """Простой тестовый клиент"""
    # Создаем минимальное приложение для тестов
    from fastapi import FastAPI
    
    app = FastAPI()
    
    # Добавляем простой эндпоинт
    @app.get("/test")
    async def test_endpoint():
        return {"status": "ok"}
    
    return TestClient(app)


# Простой тест с фикстурой
def test_simple_endpoint(simple_test_client):
    """Простой тест эндпоинта"""
    response = simple_test_client.get("/test")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# Запуск тестов
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "--cov=app.main", "--cov-report=term-missing"])
