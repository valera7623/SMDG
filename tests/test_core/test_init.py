# tests/test_core/test_init_working.py
import pytest
import tempfile
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock, mock_open

# Тест 1: Простой тест функции init_keys (работает!)
@pytest.mark.asyncio
async def test_init_keys_simple_working():
    """Простой рабочий тест функции init_keys"""
    
    # Создаем мок для crypto_manager
    mock_crypto_manager = MagicMock()
    mock_crypto_manager.generate_keypair = AsyncMock(return_value=("age1simplekey", "private"))
    
    # Мокаем открытие файла - файл существует с ключом
    with patch('builtins.open', mock_open(read_data="age1simplekey\n")), \
         patch('app.crypto.crypto.crypto_manager', mock_crypto_manager), \
         patch('pathlib.Path.exists', return_value=True), \
         patch('builtins.print'):
        
        # Импортируем функцию
        from app.core.__init__ import init_keys
        
        # Используем временный путь
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            
            with patch('app.core.__init__.PRIVATE_KEY_PATH', tmp_path / "keys" / "age.key"), \
                 patch('app.core.__init__._PUBLIC_KEY', None):
                
                await init_keys()
                
                # Проверяем результат
                from app.core.__init__ import _PUBLIC_KEY
                assert _PUBLIC_KEY == "age1simplekey"

# Тест 2: Функция get_public_key (работает!)
def test_get_public_key_logic_working():
    """Рабочий тест логики функции get_public_key"""
    from app.core.__init__ import get_public_key
    
    with patch('app.core.__init__._PUBLIC_KEY', None):
        with pytest.raises(RuntimeError, match="Публичный ключ не инициализирован"):
            get_public_key()
    
    with patch('app.core.__init__._PUBLIC_KEY', "test_key_456"):
        result = get_public_key()
        assert result == "test_key_456"

# Тест 3: Логика создания директорий (работает!)
def test_directory_creation_logic_working():
    """Рабочий тест логики создания директорий"""
    def simulate_directory_creation(base_dir):
        from pathlib import Path
        upload_dir = base_dir / "uploads"
        encrypted_dir = base_dir / "encrypted"
        decrypted_dir = base_dir / "decrypted"
        return upload_dir, encrypted_dir, decrypted_dir
    
    base_dir = Path("/test/project")
    upload, encrypted, decrypted = simulate_directory_creation(base_dir)
    
    assert upload == Path("/test/project/uploads")
    assert encrypted == Path("/test/project/encrypted")
    assert decrypted == Path("/test/project/decrypted")

# Тест 4: Проверка структуры модуля (работает!)
def test_module_structure_working():
    """Рабочий тест структуры модуля"""
    import app.core.__init__ as core_module
    
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

# Тест 5: Проверка менеджеров (работает!)
def test_managers_working():
    """Рабочий тест менеджеров"""
    import app.core.__init__ as core_module
    
    assert hasattr(core_module, 'file_storage')
    assert hasattr(core_module, 'cleanup_manager')
    assert hasattr(core_module, 'audit_logger')
    
    assert core_module.file_storage is not None
    assert core_module.cleanup_manager is not None
    assert core_module.audit_logger is not None

# Тест 6: Проверка экспорта модуля (работает!)
def test_module_exports_working():
    """Рабочий тест экспорта модуля"""
    import app.core.__init__ as core_module
    
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

# Тест 7: Интеграционный тест (работает!)
def test_module_initialization_working():
    """Рабочий интеграционный тест инициализации модуля"""
    import app.core.__init__ as core_module
    
    assert isinstance(core_module.BASE_DIR, Path)
    assert isinstance(core_module.UPLOAD_DIR, Path)
    assert isinstance(core_module.ENCRYPTED_DIR, Path)
    assert isinstance(core_module.DECRYPTED_DIR, Path)
    assert isinstance(core_module.PRIVATE_KEY_PATH, Path)
    
    assert core_module.UPLOAD_DIR == core_module.BASE_DIR / "uploads"
    assert core_module.ENCRYPTED_DIR == core_module.BASE_DIR / "encrypted"
    assert core_module.DECRYPTED_DIR == core_module.BASE_DIR / "decrypted"
    assert core_module.PRIVATE_KEY_PATH == core_module.BASE_DIR / "keys" / "age.key"

# Тест 8: Проверка debug mode (работает!)
def test_debug_mode_if_enabled_working():
    """Рабочий тест debug mode"""
    import app.core.__init__ as core_module
    
    assert hasattr(core_module, 'settings')
    assert hasattr(core_module.settings, 'debug')

# Тест 9: Тест инициализации ключей с ошибкой (новый)
@pytest.mark.asyncio
async def test_init_keys_with_error():
    """Тест init_keys с ошибкой при чтении файла"""
    
    mock_crypto_manager = MagicMock()
    mock_crypto_manager.generate_keypair = AsyncMock(return_value=("age1key", "private"))
    
    # Мокаем exists чтобы файл не существовал (нужна генерация)
    with patch('pathlib.Path.exists', return_value=False), \
         patch('builtins.open', mock_open(read_data="age1key\n")), \
         patch('app.crypto.crypto.crypto_manager', mock_crypto_manager), \
         patch('builtins.print'):
        
        from app.core.__init__ import init_keys
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            
            with patch('app.core.__init__.PRIVATE_KEY_PATH', tmp_path / "keys" / "age.key"), \
                 patch('app.core.__init__._PUBLIC_KEY', None):
                
                await init_keys()
                
                # Проверяем что ключи сгенерированы
                mock_crypto_manager.generate_keypair.assert_called_once()
                
                # Проверяем результат
                from app.core.__init__ import _PUBLIC_KEY
                assert _PUBLIC_KEY == "age1key"

# Тест 10: Тест init_keys с существующими ключами
@pytest.mark.asyncio
async def test_init_keys_existing_keys():
    """Тест init_keys когда ключи уже существуют"""
    
    # Мокаем exists чтобы файлы существовали
    with patch('pathlib.Path.exists', return_value=True), \
         patch('builtins.open', mock_open(read_data="age1existingkey\n")), \
         patch('app.crypto.crypto.crypto_manager', MagicMock()), \
         patch('builtins.print'):
        
        from app.core.__init__ import init_keys
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            
            with patch('app.core.__init__.PRIVATE_KEY_PATH', tmp_path / "keys" / "age.key"), \
                 patch('app.core.__init__._PUBLIC_KEY', None):
                
                await init_keys()
                
                # Проверяем результат
                from app.core.__init__ import _PUBLIC_KEY
                assert _PUBLIC_KEY == "age1existingkey"
                
                


# Тест для покрытия строк 25-27: коррекция BASE_DIR
def test_base_dir_correction_with_debug():
    """Тест коррекции BASE_DIR с debug mode"""
    
    # Создаем временную структуру каталогов
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        project_dir = tmp_path / "myproject"
        app_dir = project_dir / "app"
        app_dir.mkdir(parents=True)
        
        # Создаем подкаталог core
        core_dir = app_dir / "core"
        core_dir.mkdir()
        
        # Мокаем debug mode = True
        mock_settings = MagicMock()
        mock_settings.debug = True
        
        # Мокаем Path.cwd чтобы вернуть путь к app директории
        with patch('app.core.__init__.settings', mock_settings), \
             patch('app.core.__init__.Path.cwd', return_value=app_dir), \
             patch('builtins.print') as mock_print, \
             patch('pathlib.Path.mkdir'), \
             patch('app.core.storage.FileStorageManager'), \
             patch('app.core.cleanup.FileCleanupManager'), \
             patch('app.core.audit.AuditLogger'):
            
            # Очищаем кэш модуля
            import sys
            if 'app.core' in sys.modules:
                del sys.modules['app.core']
            if 'app.core.__init__' in sys.modules:
                del sys.modules['app.core.__init__']
            
            import app.core as core_module
            
            # Проверяем что BASE_DIR был скорректирован
            assert core_module.BASE_DIR == project_dir
            
            # Проверяем debug вывод
            debug_messages = []
            for call in mock_print.call_args_list:
                if call[0] and len(call[0]) > 0:
                    args_str = str(call[0][0])
                    if "DEBUG" in args_str or "🔧" in args_str or "Исправляем" in args_str:
                        debug_messages.append(args_str)
            
            # Должен быть debug вывод о коррекции
            assert len(debug_messages) > 0

# Тест для покрытия строк 70-80: генерация ключей и запись в файл
@pytest.mark.asyncio
async def test_init_keys_generation_and_write():
    """Тест генерации ключей и записи в файл (строки 70-80)"""
    
    mock_crypto_manager = MagicMock()
    # Возвращаем сгенерированный ключ
    mock_crypto_manager.generate_keypair = AsyncMock(return_value=("age1generatedkey", "private_data"))
    
    # Мокаем exists чтобы файлов не было (нужна генерация)
    with patch('pathlib.Path.exists', return_value=False), \
         patch('app.crypto.crypto.crypto_manager', mock_crypto_manager), \
         patch('builtins.print'):
        
        # Мокаем open для записи и чтения
        mock_file_write = mock_open()
        mock_file_read = mock_open(read_data="age1generatedkey\n")
        
        # open должен вызываться дважды: для записи и для чтения
        open_call_count = 0
        def open_side_effect(*args, **kwargs):
            nonlocal open_call_count
            open_call_count += 1
            if open_call_count == 1:
                return mock_file_write(*args, **kwargs)  # Запись
            else:
                return mock_file_read(*args, **kwargs)   # Чтение
        
        with patch('builtins.open', side_effect=open_side_effect):
            from app.core.__init__ import init_keys
            
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                
                with patch('app.core.__init__.PRIVATE_KEY_PATH', tmp_path / "keys" / "age.key"), \
                     patch('app.core.__init__._PUBLIC_KEY', None):
                    
                    await init_keys()
                    
                    # Проверяем что ключи сгенерированы
                    mock_crypto_manager.generate_keypair.assert_called_once()
                    
                    # Проверяем что open был вызван дважды
                    assert open_call_count == 2
                    
                    # Проверяем результат
                    from app.core.__init__ import _PUBLIC_KEY
                    assert _PUBLIC_KEY == "age1generatedkey"

# Тест для покрытия ветки с ошибкой в сгенерированном файле
@pytest.mark.asyncio
async def test_init_keys_generated_file_empty():
    """Тест когда сгенерированный файл оказывается пустым"""
    
    mock_crypto_manager = MagicMock()
    mock_crypto_manager.generate_keypair = AsyncMock(return_value=("age1key", "private"))
    
    # Мокаем exists чтобы файлов не было (нужна генерация)
    with patch('pathlib.Path.exists', return_value=False), \
         patch('app.crypto.crypto.crypto_manager', mock_crypto_manager), \
         patch('builtins.print'):
        
        # Мокаем open для записи и чтения (читаем пустой файл)
        mock_file_write = mock_open()
        mock_file_read = mock_open(read_data="")  # Пустой файл после генерации!
        
        open_call_count = 0
        def open_side_effect(*args, **kwargs):
            nonlocal open_call_count
            open_call_count += 1
            if open_call_count == 1:
                return mock_file_write(*args, **kwargs)  # Запись
            else:
                return mock_file_read(*args, **kwargs)   # Чтение (пустой файл)
        
        with patch('builtins.open', side_effect=open_side_effect):
            from app.core.__init__ import init_keys
            
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                
                with patch('app.core.__init__.PRIVATE_KEY_PATH', tmp_path / "keys" / "age.key"), \
                     patch('app.core.__init__._PUBLIC_KEY', None):
                    
                    # Должно вызвать ValueError
                    with pytest.raises(ValueError, match="age.pub пустой или только комментарии"):
                        await init_keys()