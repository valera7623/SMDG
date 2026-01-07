# app/core/__init__.py
from pathlib import Path
import os
from app.crypto.crypto import crypto_manager
from app.core.storage import FileStorageManager
from .cleanup import FileCleanupManager
from .audit import AuditLogger
import asyncio

# Инициализация аудит-логгера (первым, чтобы все компоненты могли его использовать)
audit_logger = AuditLogger()

# Корневая директория проекта
BASE_DIR = Path.cwd()

# Отладочные print'ы — только если DEBUG=true в окружении
DEBUG_MODE = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")

if DEBUG_MODE:
    print(f"🔧 DEBUG: Корень проекта: {BASE_DIR}")
    print(f"🔧 DEBUG: __file__: {Path(__file__)}")

# Корректировка BASE_DIR, если запущено из подпапки app/
if BASE_DIR.name == 'app' and (BASE_DIR / 'core').exists():
    BASE_DIR = BASE_DIR.parent
    if DEBUG_MODE:
        print(f"🔧 DEBUG: Исправляем BASE_DIR на: {BASE_DIR}")

# Основные рабочие директории (в корне проекта)
UPLOAD_DIR = BASE_DIR / "uploads"
ENCRYPTED_DIR = BASE_DIR / "encrypted"
DECRYPTED_DIR = BASE_DIR / "decrypted"

if DEBUG_MODE:
    print(f"📁 UPLOAD_DIR: {UPLOAD_DIR}")
    print(f"📁 ENCRYPTED_DIR: {ENCRYPTED_DIR}")
    print(f"📁 DECRYPTED_DIR: {DECRYPTED_DIR}")

# Создаём директории
for d in [UPLOAD_DIR, ENCRYPTED_DIR, DECRYPTED_DIR]:
    d.mkdir(parents=True, exist_ok=True)
    if DEBUG_MODE:
        print(f"✅ Создана/проверена директория: {d}")
        print(f"   📍 Абсолютный путь: {d.absolute()}")

# Директория с ключами шифрования
KEYS_DIR = BASE_DIR / "keys"
KEYS_DIR.mkdir(exist_ok=True)
PRIVATE_KEY_PATH = KEYS_DIR / "age.key"

# Глобальная переменная для публичного ключа
_PUBLIC_KEY: str | None = None

# API-ключи через переменную окружения
raw_api_keys = os.getenv("API_KEYS", "test-token-123")  # fallback только для локальной разработки
API_KEYS = {key.strip() for key in raw_api_keys.split(",") if key.strip()}
API_KEY_HEADER = "X-API-KEY"

if DEBUG_MODE or "test-token-123" in API_KEYS:
    print(f"🔑 Загружено {len(API_KEYS)} API-ключ(ей)")
    if "test-token-123" in API_KEYS:
        print("⚠️  ВНИМАНИЕ: обнаружен тестовый ключ 'test-token-123' — замените в production!")

# Менеджер временных расшифрованных файлов (TTL = 1 час)
file_storage = FileStorageManager(
    storage_dir=DECRYPTED_DIR,
    ttl_seconds=3600
)

# Менеджер автоматической очистки зашифрованных файлов (TTL = 30 дней)
cleanup_manager = FileCleanupManager(
    encrypted_dir=ENCRYPTED_DIR,
    ttl_days=30
)

async def init_keys() -> str:
    """Безопасная инициализация ключей age с поддержкой DEV_MODE"""
    global _PUBLIC_KEY
    
    KEYS_DIR.mkdir(exist_ok=True)
    
    dev_mode = os.getenv("DEV_MODE", "false").lower() in ("true", "1", "yes")
    
    if PRIVATE_KEY_PATH.exists():
        if DEBUG_MODE:
            print(f"🔑 Найден существующий приватный ключ: {PRIVATE_KEY_PATH}")
        try:
            with open(PRIVATE_KEY_PATH, "r", encoding="utf-8") as f:
                content = f.read()
            
            public_key = None
            for line in content.splitlines():
                if line.startswith("# public key:"):
                    public_key = line.split(": ", 1)[1].strip()
                    break
            
            if not public_key:
                raise ValueError("Не удалось извлечь публичный ключ из age.key")
            
            _PUBLIC_KEY = public_key
            if DEBUG_MODE:
                print("✅ Публичный ключ успешно загружен")
            audit_logger.log_operation(
                action="keys_loaded",
                filename="age.key",
                user="system",
                reason="Существующие ключи загружены при старте",
                success=True
            )
            return public_key
        
        except Exception as e:
            error_msg = f"Ошибка чтения приватного ключа: {e}"
            if DEBUG_MODE:
                print(f"❌ {error_msg}")
            audit_logger.log_operation(
                action="keys_load_failed",
                filename="age.key",
                user="system",
                reason=error_msg,
                success=False
            )
            raise
    
    else:
        if dev_mode:
            if DEBUG_MODE:
                print("🔐 DEV_MODE активен — генерируем новую пару ключей age...")
            try:
                private_key, public_key = await crypto_manager.generate_keypair(PRIVATE_KEY_PATH)
                
                pub_path = KEYS_DIR / "age.pub"
                with open(pub_path, "w", encoding="utf-8") as f:
                    f.write(f"# Public key for SMDG\n{public_key}\n")
                
                _PUBLIC_KEY = public_key
                if DEBUG_MODE:
                    print(f"✅ Новые ключи созданы: {PRIVATE_KEY_PATH}")
                    print("⚠️  В production используйте вручную созданные ключи!")
                
                audit_logger.log_operation(
                    action="keys_generated",
                    filename="age.key",
                    user="system",
                    reason="Автоматическая генерация в DEV_MODE",
                    success=True
                )
                return public_key
            
            except Exception as e:
                error_msg = f"Ошибка генерации ключей: {e}"
                if DEBUG_MODE:
                    print(f"❌ {error_msg}")
                raise
        else:
            error_msg = (
                f"❌ Критическая ошибка: приватный ключ не найден ({PRIVATE_KEY_PATH})\n"
                "Автоматическая генерация запрещена вне DEV_MODE.\n"
                "Создайте ключ вручную: age-keygen -o keys/age.key"
            )
            if DEBUG_MODE:
                print(error_msg)
            audit_logger.log_operation(
                action="keys_missing",
                filename="age.key",
                user="system",
                reason="Отсутствует приватный ключ в production",
                success=False
            )
            raise RuntimeError("Encryption private key missing in production mode")

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
    'crypto_manager',
    'API_KEYS',
    'API_KEY_HEADER',
    'file_storage',
    'cleanup_manager',
    'audit_logger',
    'init_keys'
]