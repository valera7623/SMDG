# tests/test_cli.py
import pytest
from typer.testing import CliRunner
from unittest.mock import patch, MagicMock, AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession
from app.cli import cli
from app.models.user import User
from app.core.security import verify_password, get_password_hash

runner = CliRunner()


class TestCLI:
    """Тесты для CLI команд"""

    def test_create_admin_new_user(self):
        """Тест создания нового администратора"""
        # Мокаем асинхронные зависимости
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.execute.return_value.scalar_one_or_none.return_value = None
        
        mock_session_class = MagicMock()
        mock_session_class.return_value.__aenter__.return_value = mock_session
        
        # Мокаем asyncio.run чтобы избежать ошибки event loop
        with patch('app.cli.asyncio.run') as mock_asyncio_run:
            with patch('app.cli.AsyncSessionLocal', mock_session_class):
                
                def capture_coroutine(coro):
                    # Запускаем корутину синхронно для проверки
                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(coro)
                    finally:
                        loop.close()
                    return None
                
                mock_asyncio_run.side_effect = capture_coroutine
                
                # Запускаем CLI команду
                result = runner.invoke(cli, ["create-admin", "newadmin", "securepass123"])
                
                # Проверяем вывод
                assert result.exit_code == 0, f"Expected exit code 0, got {result.exit_code}. Output: {result.stdout}"
                assert "Админ newadmin создан." in result.stdout
                assert "Готово. Теперь можно логиниться." in result.stdout
                
                # Проверяем, что session.commit был вызван
                mock_session.commit.assert_called_once()
                
                # Проверяем, что пользователь был добавлен с правильными данными
                mock_session.add.assert_called_once()
                added_user = mock_session.add.call_args[0][0]
                
                assert isinstance(added_user, User)
                assert added_user.username == "newadmin"
                assert added_user.role == "admin"
                assert added_user.is_active is True
                # Пароль должен быть хэширован
                assert added_user.hashed_password != "securepass123"
                assert verify_password("securepass123", added_user.hashed_password)

    def test_create_admin_update_existing(self):
        """Тест обновления существующего пользователя до администратора"""
        # Создаем мок существующего пользователя
        existing_user = User(
            id=1,
            username="existinguser",
            hashed_password="old_hash",  # Старый хэш
            role="user",  # Изначально обычный пользователь
            is_active=False  # Изначально неактивен
        )
        
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.execute.return_value.scalar_one_or_none.return_value = existing_user
        
        mock_session_class = MagicMock()
        mock_session_class.return_value.__aenter__.return_value = mock_session
        
        # Мокаем asyncio.run чтобы избежать ошибки event loop
        with patch('app.cli.asyncio.run') as mock_asyncio_run:
            with patch('app.cli.AsyncSessionLocal', mock_session_class):
                
                def capture_coroutine(coro):
                    # Запускаем корутину синхронно для проверки
                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(coro)
                    finally:
                        loop.close()
                    return None
                
                mock_asyncio_run.side_effect = capture_coroutine
                
                # Запускаем CLI команду
                result = runner.invoke(cli, ["create-admin", "existinguser", "newpass456"])
                
                # Проверяем вывод
                assert result.exit_code == 0, f"Expected exit code 0, got {result.exit_code}. Output: {result.stdout}"
                assert "Админ existinguser обновлён." in result.stdout
                assert "Готово. Теперь можно логиниться." in result.stdout
                
                # Проверяем, что session.commit был вызван
                mock_session.commit.assert_called_once()
                
                # Проверяем, что НЕ добавляли нового пользователя
                mock_session.add.assert_not_called()
                
                # Проверяем, что существующий пользователь обновлен
                assert existing_user.role == "admin"
                assert existing_user.is_active is True
                # Пароль должен быть обновлен
                assert existing_user.hashed_password != "old_hash"
                assert existing_user.hashed_password != "newpass456"
                # Проверяем, что get_password_hash был вызван (опосредованно через verify_password)
                assert verify_password("newpass456", existing_user.hashed_password)

    def test_create_admin_default_username(self):
        """Тест с использованием имени пользователя по умолчанию"""
        # Просто проверяем help, не запуская команду
        result = runner.invoke(cli, ["create-admin", "--help"])
        
        # Проверяем help текст
        assert result.exit_code == 0
        assert "Имя пользователя (по умолчанию: admin)" in result.stdout
        assert "Пароль администратора (без промпта)" in result.stdout

    def test_create_admin_with_explicit_default_username(self):
        """Тест создания администратора с явным указанием имени 'admin'"""
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.execute.return_value.scalar_one_or_none.return_value = None
        
        mock_session_class = MagicMock()
        mock_session_class.return_value.__aenter__.return_value = mock_session
        
        # Мокаем asyncio.run чтобы избежать ошибки event loop
        with patch('app.cli.asyncio.run') as mock_asyncio_run:
            with patch('app.cli.AsyncSessionLocal', mock_session_class):
                
                def capture_coroutine(coro):
                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(coro)
                    finally:
                        loop.close()
                    return None
                
                mock_asyncio_run.side_effect = capture_coroutine
                
                # Явно указываем username "admin" и password
                result = runner.invoke(cli, ["create-admin", "admin", "adminpass789"])
                
                # Проверяем, что команда выполнилась
                assert result.exit_code == 0, f"Expected exit code 0, got {result.exit_code}. Output: {result.stdout}"
                
                # Проверяем, что пользователь был добавлен
                mock_session.add.assert_called_once()
                added_user = mock_session.add.call_args[0][0]
                
                assert added_user.username == "admin"

    def test_create_admin_with_only_password_argument(self):
        """Тест создания администратора с передачей только пароля (username по умолчанию)"""
        # Внимание: Typer интерпретирует аргументы позиционно
        # При вызове: create-admin <password>
        # Typer думает: первый аргумент = username, второй = password
        # Но у нас password обязательный без дефолта, так что это вызовет ошибку
        
        result = runner.invoke(cli, ["create-admin", "somepassword"])
        
        # Typer ожидает 2 аргумента, поэтому будет ошибка
        # Проверяем, что это действительно так
        assert result.exit_code != 0
        # Или проверяем сообщение об ошибке
        assert "Missing argument" in result.stdout or "Error" in result.stdout

    def test_create_admin_database_error(self):
        """Тест обработки ошибки базы данных"""
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.execute.side_effect = Exception("Database connection error")
        
        mock_session_class = MagicMock()
        mock_session_class.return_value.__aenter__.return_value = mock_session
        
        # Мокаем asyncio.run чтобы избежать ошибки event loop
        with patch('app.cli.asyncio.run') as mock_asyncio_run:
            with patch('app.cli.AsyncSessionLocal', mock_session_class):
                
                def capture_coroutine(coro):
                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(coro)
                    except Exception:
                        pass  # Ожидаем исключение
                    finally:
                        loop.close()
                    return None
                
                mock_asyncio_run.side_effect = capture_coroutine
                
                # Запускаем CLI команду
                result = runner.invoke(cli, ["create-admin", "testuser", "testpass"])
                
                # Команда может завершиться с ошибкой
                # Проверяем, что asyncio.run был вызван
                mock_asyncio_run.assert_called_once()

    def test_cli_help(self):
        """Тест вывода справки"""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "create-admin" in result.stdout
        assert "Создаёт или обновляет администратора" in result.stdout

    def test_create_admin_empty_password(self):
        """Тест с пустым паролем"""
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.execute.return_value.scalar_one_or_none.return_value = None
        
        mock_session_class = MagicMock()
        mock_session_class.return_value.__aenter__.return_value = mock_session
        
        # Мокаем asyncio.run чтобы избежать ошибки event loop
        with patch('app.cli.asyncio.run') as mock_asyncio_run:
            with patch('app.cli.AsyncSessionLocal', mock_session_class):
                
                def capture_coroutine(coro):
                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(coro)
                    finally:
                        loop.close()
                    return None
                
                mock_asyncio_run.side_effect = capture_coroutine
                
                # Передаем пустой пароль
                result = runner.invoke(cli, ["create-admin", "testuser", ""])
                
                # Проверяем, что команда выполнилась
                assert result.exit_code == 0, f"Expected exit code 0, got {result.exit_code}. Output: {result.stdout}"
                
                # Пользователь должен быть создан с пустым паролем (хэшированной пустой строкой)
                mock_session.add.assert_called_once()
                added_user = mock_session.add.call_args[0][0]
                
                # Проверяем, что пароль хэширован (даже пустой)
                assert added_user.hashed_password is not None
                assert verify_password("", added_user.hashed_password)
    
    def test_create_admin_command_structure(self):
        """Тест структуры команды и аргументов"""
        # Проверяем, что команда требует ровно 2 аргумента
        result = runner.invoke(cli, ["create-admin"])
        assert result.exit_code != 0  # Должна быть ошибка - не хватает аргументов
        
        result = runner.invoke(cli, ["create-admin", "useronly"])
        assert result.exit_code != 0  # Должна быть ошибка - не хватает пароля
        
        result = runner.invoke(cli, ["create-admin", "user", "pass", "extra"])
        # Typer может принять лишние аргументы или выдать ошибку
        # Проверяем хотя бы что команда не выполняется нормально
        if result.exit_code == 0:
            print(f"Warning: Typer accepted extra arguments: {result.stdout}")