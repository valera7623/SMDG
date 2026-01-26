# app/core/__init__.py
from pathlib import Path
import asyncio
from app.core.storage import FileStorageManager
from .cleanup import FileCleanupManager
from .audit import AuditLogger
from .config import settings  
from .constants import BASE_DIR, UPLOAD_DIR, ENCRYPTED_DIR, DECRYPTED_DIR, PRIVATE_KEY_PATH

# Инициализация аудит-логгера (первым, чтобы другие компоненты могли его использовать)
audit_logger = AuditLogger()

# Корневая директория проекта
BASE_DIR = Path.cwd()

# Отладочный режим — берётся из настроек
DEBUG_MODE = settings.debug

if DEBUG_MODE:
    print(f"🔧 DEBUG: Корень проекта: {BASE_DIR}")
    print(f"🔧 DEBUG: __file__: {Path(__file__)}")

# Корректировка BASE_DIR, если запущено из подпапки app/
if BASE_DIR.name == 'app' and (BASE_DIR / 'core').exists():
    BASE_DIR = BASE_DIR.parent
    if DEBUG_MODE:
        print(f"🔧 DEBUG: Исправляем BASE_DIR на: {BASE_DIR}")

# Директории проекта
UPLOAD_DIR = BASE_DIR / "uploads"
ENCRYPTED_DIR = BASE_DIR / "encrypted"
DECRYPTED_DIR = BASE_DIR / "decrypted"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ENCRYPTED_DIR.mkdir(parents=True, exist_ok=True)
DECRYPTED_DIR.mkdir(parents=True, exist_ok=True)

# Путь к приватному ключу
PRIVATE_KEY_PATH = BASE_DIR / "keys" / "age.key"

# TTL для временных файлов (в секундах, 1 час по умолчанию)
TEMP_TTL_SECONDS = 3600

# Глобальные менеджеры
file_storage = FileStorageManager(DECRYPTED_DIR, TEMP_TTL_SECONDS)
cleanup_manager = FileCleanupManager(ENCRYPTED_DIR)

# Приватный и публичный ключ (инициализируются при старте)
_PUBLIC_KEY = None



async def init_keys():
    """Инициализация ключей шифрования"""
    from app.crypto.crypto import crypto_manager  # ← Ленивый импорт — правильно!

    global _PUBLIC_KEY
    if _PUBLIC_KEY is None:
        PRIVATE_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        pub_path = PRIVATE_KEY_PATH.with_name("age.pub")
        if PRIVATE_KEY_PATH.exists() and pub_path.exists():
            with open(pub_path, "r") as f:
                lines = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]
                if lines:
                    _PUBLIC_KEY = lines[-1]  # берём последнюю валидную строку (age1...)
                else:
                    raise ValueError("Файл age.pub пустой или содержит только комментарии")
        else:
            # Генерация новой пары (как было)
            print("Публичный ключ не найден, генерируем новую пару...")
            public_key, _ = await crypto_manager.generate_keypair(PRIVATE_KEY_PATH)
            _PUBLIC_KEY = public_key
            with open(pub_path, "w") as f:
                f.write(public_key + "\n")
            with open(pub_path, "r") as f:
                lines = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]
                if lines:
                    _PUBLIC_KEY = lines[-1]  # последняя валидная строка age1...
                else:
                    raise ValueError("age.pub пустой или только комментарии")    
                
                

def get_public_key() -> str:
    """Возвращает публичный ключ после инициализации"""
    if _PUBLIC_KEY is None:
        raise RuntimeError("Публичный ключ не инициализирован. Вызовите await init_keys() при старте.")
    return _PUBLIC_KEY

# Экспорт всех объектов, используемых в других модулях
__all__ = [
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