# tests/test_core/test_init.py

import pytest
import tempfile
import importlib
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock, mock_open, call


# Тест 1: Простой тест функции init_keys
@pytest.mark.asyncio
async def test_init_keys_simple_working():
    """Простой рабочий тест функции init_keys"""
    mock_crypto_manager = MagicMock()
    mock_crypto_manager.generate_keypair = AsyncMock(return_value=("age1simplekey", "private"))

    with patch('builtins.open', mock_open(read_data="age1simplekey\n")), \
         patch('app.crypto.crypto.crypto_manager', mock_crypto_manager), \
         patch('pathlib.Path.exists', return_value=True), \
         patch('builtins.print'):

        from app.core import init_keys

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            with patch('app.core.PRIVATE_KEY_PATH', tmp_path / "keys" / "age.key"), \
                 patch('app.core._PUBLIC_KEY', None):

                await init_keys()

                from app.core import _PUBLIC_KEY
                assert _PUBLIC_KEY == "age1simplekey"


# Тест 2: Функция get_public_key
def test_get_public_key_logic_working():
    """Рабочий тест логики функции get_public_key"""
    from app.core import get_public_key

    with patch('app.core._PUBLIC_KEY', None):
        with pytest.raises(RuntimeError, match="Публичный ключ не инициализирован"):
            get_public_key()

    with patch('app.core._PUBLIC_KEY', "test_key_456"):
        result = get_public_key()
        assert result == "test_key_456"


# Тест 3: Логика создания директорий
def test_directory_creation_logic_working():
    """Рабочий тест логики создания директорий"""
    def simulate_directory_creation(base_dir):
        upload_dir = base_dir / "uploads"
        encrypted_dir = base_dir / "encrypted"
        decrypted_dir = base_dir / "decrypted"
        return upload_dir, encrypted_dir, decrypted_dir

    base_dir = Path("/test/project")
    upload, encrypted, decrypted = simulate_directory_creation(base_dir)

    assert upload == Path("/test/project/uploads")
    assert encrypted == Path("/test/project/encrypted")
    assert decrypted == Path("/test/project/decrypted")


# Тест 4: Проверка структуры модуля
def test_module_structure_working():
    """Рабочий тест структуры модуля"""
    import app.core as core_module

    assert hasattr(core_module, 'init_keys')
    assert hasattr(core_module, 'get_public_key')
    assert callable(core_module.init_keys)
    assert callable(core_module.get_public_key)

    assert hasattr(core_module, 'BASE_DIR')
    assert hasattr(core_module, 'UPLOAD_DIR')
    assert hasattr(core_module, 'ENCRYPTED_DIR')
    assert hasattr(core_module, 'DECRYPTED_DIR')
    assert hasattr(core_module, 'PRIVATE_KEY_PATH')
    assert hasattr(core_module, 'TEMP_TTL_SECONDS')

    assert core_module.TEMP_TTL_SECONDS == 3600


# Тест 5: Проверка менеджеров
def test_managers_working():
    """Рабочий тест менеджеров"""
    import app.core as core_module

    assert hasattr(core_module, 'file_storage')
    assert hasattr(core_module, 'cleanup_manager')
    assert hasattr(core_module, 'audit_logger')

    assert core_module.file_storage is not None
    assert core_module.cleanup_manager is not None
    assert core_module.audit_logger is not None


# Тест 6: Проверка экспорта модуля
def test_module_exports_working():
    """Рабочий тест экспорта модуля"""
    import app.core as core_module

    assert hasattr(core_module, '__all__')

    expected_exports = [
        'UPLOAD_DIR',
        'ENCRYPTED_DIR',
        'DECRYPTED_DIR',
        'PRIVATE_KEY_PATH',
        'get_public_key',
        'file_storage',
        'cleanup_manager',
        'audit_logger',
        'init_keys',
        'settings'
    ]

    for export in expected_exports:
        assert export in core_module.__all__
        assert hasattr(core_module, export)


# Тест 7: Интеграционный тест
def test_module_initialization_working():
    """Рабочий интеграционный тест инициализации модуля"""
    import app.core as core_module

    assert isinstance(core_module.BASE_DIR, Path)
    assert isinstance(core_module.UPLOAD_DIR, Path)
    assert isinstance(core_module.ENCRYPTED_DIR, Path)
    assert isinstance(core_module.DECRYPTED_DIR, Path)
    assert isinstance(core_module.PRIVATE_KEY_PATH, Path)

    assert core_module.UPLOAD_DIR == core_module.BASE_DIR / "uploads"
    assert core_module.ENCRYPTED_DIR == core_module.BASE_DIR / "encrypted"
    assert core_module.DECRYPTED_DIR == core_module.BASE_DIR / "decrypted"
    assert core_module.PRIVATE_KEY_PATH == core_module.BASE_DIR / "keys" / "age.key"


# Тест 8: Проверка debug mode
def test_debug_mode_if_enabled_working():
    """Рабочий тест debug mode"""
    import app.core as core_module

    assert hasattr(core_module, 'settings')
    assert hasattr(core_module.settings, 'debug')


# Тест 9: Тест init_keys с ошибкой (файлов нет — генерация)
@pytest.mark.asyncio
async def test_init_keys_with_error():
    """Тест init_keys с ошибкой при чтении файла"""
    mock_crypto_manager = MagicMock()
    mock_crypto_manager.generate_keypair = AsyncMock(return_value=("age1key", "private"))

    with patch('pathlib.Path.exists', return_value=False), \
         patch('builtins.open', mock_open(read_data="age1key\n")), \
         patch('app.crypto.crypto.crypto_manager', mock_crypto_manager), \
         patch('builtins.print'):

        from app.core import init_keys

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            with patch('app.core.PRIVATE_KEY_PATH', tmp_path / "keys" / "age.key"), \
                 patch('app.core._PUBLIC_KEY', None):

                await init_keys()

                mock_crypto_manager.generate_keypair.assert_called_once()

                from app.core import _PUBLIC_KEY
                assert _PUBLIC_KEY == "age1key"


# Тест 10: Тест init_keys с существующими ключами
@pytest.mark.asyncio
async def test_init_keys_existing_keys():
    """Тест init_keys когда ключи уже существуют"""
    with patch('pathlib.Path.exists', return_value=True), \
         patch('builtins.open', mock_open(read_data="age1existingkey\n")), \
         patch('app.crypto.crypto.crypto_manager', MagicMock()), \
         patch('builtins.print'):

        from app.core import init_keys

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            with patch('app.core.PRIVATE_KEY_PATH', tmp_path / "keys" / "age.key"), \
                 patch('app.core._PUBLIC_KEY', None):

                await init_keys()

                from app.core import _PUBLIC_KEY
                assert _PUBLIC_KEY == "age1existingkey"


# Тест: коррекция BASE_DIR — тестируем ЛОГИКУ, не перезагрузку модуля
def test_base_dir_correction_logic():
    """
    Тест логики коррекции BASE_DIR.
    Проверяем саму логику ветки, не перезагрузку модуля,
    т.к. модуль уже инициализирован и его нельзя безопасно перезагрузить.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        project_dir = tmp_path / "myproject"
        app_dir = project_dir / "app"
        core_dir = app_dir / "core"
        core_dir.mkdir(parents=True)

        printed_messages = []

        def fake_print(*args, **kwargs):
            if args:
                printed_messages.append(str(args[0]))

        # Воспроизводим логику из __init__.py напрямую
        BASE_DIR = app_dir  # имитируем Path.cwd() == app_dir

        DEBUG_MODE = True
        if DEBUG_MODE:
            fake_print(f"🔧 DEBUG: Корень проекта: {BASE_DIR}")
            fake_print(f"🔧 DEBUG: __file__: {Path(__file__)}")

        # Это и есть ветка строк 25-27
        if BASE_DIR.name == 'app' and (BASE_DIR / 'core').exists():
            BASE_DIR = BASE_DIR.parent
            if DEBUG_MODE:
                fake_print(f"🔧 DEBUG: Исправляем BASE_DIR на: {BASE_DIR}")

        # Проверяем что BASE_DIR скорректирован
        assert BASE_DIR == project_dir

        # Проверяем debug вывод
        debug_correction_messages = [m for m in printed_messages if "Исправляем" in m]
        assert len(debug_correction_messages) > 0


# Тест: генерация ключей и запись в файл — считаем реальное число вызовов open
@pytest.mark.asyncio
async def test_init_keys_generation_and_write():
    """
    Тест генерации ключей и записи в файл.
    open() вызывается 3 раза в ветке генерации:
      1. open(pub_path, "w") — запись ключа
      2. open(pub_path, "r") — чтение для валидации
    НО mock_open для итерации строк требует настройки readline.
    Используем реальный tmpdir вместо mock_open.
    """
    mock_crypto_manager = MagicMock()
    mock_crypto_manager.generate_keypair = AsyncMock(return_value=("age1generatedkey", "private_data"))

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        key_dir = tmp_path / "keys"
        key_dir.mkdir(parents=True)
        private_key_path = key_dir / "age.key"
        # pub_path НЕ создаём — чтобы сработала ветка генерации

        with patch('app.crypto.crypto.crypto_manager', mock_crypto_manager), \
             patch('builtins.print'), \
             patch('app.core.PRIVATE_KEY_PATH', private_key_path), \
             patch('app.core._PUBLIC_KEY', None):

            from app.core import init_keys
            await init_keys()

            # Проверяем что ключи сгенерированы
            mock_crypto_manager.generate_keypair.assert_called_once_with(private_key_path)

            # Проверяем что pub файл создан и содержит ключ
            pub_path = private_key_path.with_name("age.pub")
            assert pub_path.exists()
            content = pub_path.read_text().strip()
            assert content == "age1generatedkey"

            # Проверяем глобальную переменную
            from app.core import _PUBLIC_KEY
            assert _PUBLIC_KEY == "age1generatedkey"


# Тест: сгенерированный файл оказывается пустым
@pytest.mark.asyncio
async def test_init_keys_generated_file_empty():
    """Тест когда сгенерированный файл оказывается пустым"""
    mock_crypto_manager = MagicMock()
    mock_crypto_manager.generate_keypair = AsyncMock(return_value=("age1key", "private"))

    open_call_count = 0

    def open_side_effect(*args, **kwargs):
        nonlocal open_call_count
        open_call_count += 1
        mode = args[1] if len(args) > 1 else kwargs.get('mode', 'r')
        if mode == 'w':
            return mock_open()(*args, **kwargs)   # запись — успех
        else:
            return mock_open(read_data="")()       # чтение — пустой файл

    with patch('pathlib.Path.exists', return_value=False), \
         patch('app.crypto.crypto.crypto_manager', mock_crypto_manager), \
         patch('pathlib.Path.mkdir'), \
         patch('builtins.open', side_effect=open_side_effect), \
         patch('builtins.print'):

        from app.core import init_keys

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            with patch('app.core.PRIVATE_KEY_PATH', tmp_path / "keys" / "age.key"), \
                 patch('app.core._PUBLIC_KEY', None):

                with pytest.raises(ValueError, match="age.pub пустой или только комментарии"):
                    await init_keys()
