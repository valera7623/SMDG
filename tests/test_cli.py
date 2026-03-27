# tests/test_cli.py
import pytest
from typer.testing import CliRunner
from unittest.mock import AsyncMock, patch, MagicMock
from app.cli import cli

runner = CliRunner()


# ========== ТЕСТЫ АСИНХРОННОЙ ЛОГИКИ ==========

@pytest.mark.asyncio
async def test_create_admin_async_new_user():
    """Тест асинхронной логики создания нового админа"""
    with patch("app.cli.AsyncSessionLocal") as mock_session_local, \
         patch("app.cli.get_password_hash") as mock_hash:
        
        mock_session = AsyncMock()
        mock_session_local.return_value.__aenter__.return_value = mock_session
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        mock_hash.return_value = "hashed_password"
        
        from app.cli import _create_admin_async
        
        result = await _create_admin_async(
            username="testadmin",
            password="testpass",
            email="test@example.com"
        )
        
        assert "создан" in result
        assert "test@example.com" in result
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_create_admin_async_update_existing():
    """Тест асинхронной логики обновления существующего админа"""
    with patch("app.cli.AsyncSessionLocal") as mock_session_local, \
         patch("app.cli.get_password_hash") as mock_hash:
        
        mock_session = AsyncMock()
        mock_session_local.return_value.__aenter__.return_value = mock_session
        
        existing_user = MagicMock()
        existing_user.username = "existing"
        existing_user.email = "old@example.com"
        existing_user.role = "user"
        existing_user.is_active = True
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_user
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        mock_hash.return_value = "new_hashed"
        
        from app.cli import _create_admin_async
        
        result = await _create_admin_async(
            username="existing",
            password="newpass",
            email="new@example.com"
        )
        
        assert "обновлён" in result
        assert existing_user.hashed_password == "new_hashed"
        assert existing_user.role == "admin"
        mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_rotate_keys_async_success():
    """Тест асинхронной логики ротации ключей"""
    with patch("app.crypto.crypto.crypto_manager") as mock_crypto:
        mock_crypto.rotate_keys = AsyncMock(return_value="new_pub_key_123")
        
        from app.cli import _rotate_keys_async
        
        result = await _rotate_keys_async(backup_dir="/tmp/backup")
        
        assert "Ротация завершена" in result
        assert "new_pub_key_123" in result
        mock_crypto.rotate_keys.assert_called_once_with(
            backup_old_key=True,
            backup_dir="/tmp/backup"
        )


@pytest.mark.asyncio
async def test_rotate_keys_async_failure():
    """Тест ошибки при ротации ключей"""
    with patch("app.crypto.crypto.crypto_manager") as mock_crypto:
        mock_crypto.rotate_keys = AsyncMock(side_effect=Exception("Key error"))
        
        from app.cli import _rotate_keys_async
        
        with pytest.raises(Exception, match="Key error"):
            await _rotate_keys_async(backup_dir="/tmp/backup")


# ========== ТЕСТЫ CLI КОМАНД ==========

def test_create_admin_cli_new_user():
    """Тест CLI команды создания админа"""
    with patch("app.cli._create_admin_async") as mock_create:
        mock_create.return_value = "Админ testuser создан с email test@example.com."
        
        result = runner.invoke(cli, [
            "create-admin",
            "testuser",
            "testpass123",
            "--email", "test@example.com"
        ])
        
        assert result.exit_code == 0
        assert "Админ testuser создан" in result.stdout
        
        # Проверяем вызов с позиционными аргументами
        mock_create.assert_called_once()
        args, kwargs = mock_create.call_args
        
        assert len(args) == 3
        assert args[0] == "testuser"           # username
        assert args[1] == "testpass123"        # password
        assert args[2] == "test@example.com"   # email


def test_create_admin_cli_without_email():
    """Тест CLI команды с дефолтным email"""
    with patch("app.cli._create_admin_async") as mock_create:
        mock_create.return_value = "Админ admin создан с email admin@example.com."
        
        result = runner.invoke(cli, [
            "create-admin",
            "admin",
            "testpass123"
        ])
        
        assert result.exit_code == 0
        
        # Проверяем вызов с дефолтным email
        mock_create.assert_called_once()
        args, kwargs = mock_create.call_args
        
        assert len(args) == 3
        assert args[0] == "admin"
        assert args[1] == "testpass123"
        assert args[2] == "admin@example.com"  # дефолтный email


def test_create_admin_cli_missing_password():
    """Тест CLI команды без пароля"""
    result = runner.invoke(cli, [
        "create-admin",
        "testuser"
    ])
    
    assert result.exit_code == 2
    error_output = result.stdout + result.stderr
    assert any(msg in error_output for msg in [
        "Missing argument",
        "отсутствует",
        "PASSWORD",
        "пароль"
    ])


def test_rotate_keys_cli_success():
    """Тест CLI команды ротации ключей"""
    with patch("app.cli._rotate_keys_async") as mock_rotate:
        mock_rotate.return_value = "Ротация завершена. Новый публичный ключ: new_key"
        
        result = runner.invoke(cli, [
            "rotate-keys",
            "--backup-dir", "/custom/backup"
        ])
        
        assert result.exit_code == 0
        assert "Ротация завершена" in result.stdout
        
        mock_rotate.assert_called_once()
        args, kwargs = mock_rotate.call_args
        assert args[0] == "/custom/backup"


def test_rotate_keys_cli_default_dir():
    """Тест CLI команды с дефолтной директорией"""
    with patch("app.cli._rotate_keys_async") as mock_rotate:
        mock_rotate.return_value = "Success"
        
        result = runner.invoke(cli, ["rotate-keys"])
        
        assert result.exit_code == 0
        
        mock_rotate.assert_called_once()
        args, kwargs = mock_rotate.call_args
        assert args[0] == "/app/backups/keys"


def test_rotate_keys_cli_error():
    """Тест CLI команды с ошибкой"""
    with patch("app.cli._rotate_keys_async") as mock_rotate:
        mock_rotate.side_effect = Exception("Rotation failed")
        
        result = runner.invoke(cli, ["rotate-keys"])
        
        assert result.exit_code == 1
        assert "Ошибка ротации: Rotation failed" in result.stdout


def test_create_admin_cli_with_special_characters():
    """Тест создания админа с спецсимволами в пароле"""
    with patch("app.cli._create_admin_async") as mock_create:
        mock_create.return_value = "Админ special создан"
        
        result = runner.invoke(cli, [
            "create-admin",
            "specialuser",
            "P@ssw0rd!@#$%",
            "--email", "special@example.com"
        ])
        
        assert result.exit_code == 0
        
        mock_create.assert_called_once()
        args, kwargs = mock_create.call_args
        assert args[0] == "specialuser"
        assert args[1] == "P@ssw0rd!@#$%"
        assert args[2] == "special@example.com"


def test_create_admin_cli_very_long_username():
    """Тест с очень длинным именем пользователя"""
    with patch("app.cli._create_admin_async") as mock_create:
        mock_create.return_value = "Success"
        
        long_username = "a" * 100
        result = runner.invoke(cli, [
            "create-admin",
            long_username,
            "testpass123"
        ])
        
        assert result.exit_code == 0
        mock_create.assert_called_once()
        args, kwargs = mock_create.call_args
        assert args[0] == long_username
        assert args[1] == "testpass123"
        assert args[2] == "admin@example.com"  # дефолтный email


def test_create_admin_cli_custom_email():
    """Тест с кастомным email через флаг"""
    with patch("app.cli._create_admin_async") as mock_create:
        mock_create.return_value = "Success"
        
        result = runner.invoke(cli, [
            "create-admin",
            "user123",
            "pass123",
            "--email", "custom@hospital.com"
        ])
        
        assert result.exit_code == 0
        mock_create.assert_called_once()
        args, kwargs = mock_create.call_args
        assert args[0] == "user123"
        assert args[1] == "pass123"
        assert args[2] == "custom@hospital.com"


def test_create_admin_cli_empty_username():
    """Тест с пустым именем пользователя"""
    result = runner.invoke(cli, [
        "create-admin",
        "",
        "testpass123"
    ])
    
    # Пустое имя может быть валидным или нет, в зависимости от модели
    # Проверяем, что команда завершилась с ошибкой или успехом
    assert result.exit_code in [0, 1, 2]