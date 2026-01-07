# app/core/__init__.py
from pathlib import Path
import os
from app.crypto.crypto import crypto_manager
from app.core.storage import FileStorageManager
from .cleanup import FileCleanupManager
from .audit import AuditLogger
import asyncio

# Инициализация логгера (первым, чтобы другие компоненты могли его использовать)
audit_logger = AuditLogger()

# Определение корневой директории проекта
BASE_DIR = Path.cwd()

print(f"🔧 DEBUG: Корень проекта: {BASE_DIR}")
print(f"🔧 DEBUG: __file__: {Path(__file__)}")

# Корректировка BASE_DIR, если запущено из папки app/
if BASE_DIR.name == 'app' and (BASE_DIR / 'core').exists():
    BASE_DIR = BASE_DIR.parent
    print(f"🔧 DEBUG: Исправляем BASE_DIR на: {BASE_DIR}")

# Основные директории
UPLOAD_DIR = BASE_DIR / "uploads"
ENCRYPTED_DIR = BASE_DIR / "encrypted"
DECRYPTED_DIR = BASE_DIR / "decrypted"

print(f"📁 UPLOAD_DIR: {UPLOAD_DIR}")
print(f"📁 ENCRYPTED_DIR: {ENCRYPTED_DIR}")
print(f"📁 DECRYPTED_DIR: {DECRYPTED_DIR}")

for d in [UPLOAD_DIR, ENCRYPTED_DIR, DECRYPTED_DIR]:
    d.mkdir(parents=True, exist_ok=True)
    print(f"✅ Создана/проверена директория: {d}")
    print(f"   📍 Абсолютный путь: {d.absolute()}")

# Директория и путь к ключам шифрования
KEYS_DIR = BASE_DIR / "keys"
KEYS_DIR.mkdir(exist_ok=True)
PRIVATE_KEY_PATH = KEYS_DIR / "age.key"

# Глобальная переменная для публичного ключа
_PUBLIC_KEY: str | None = None

# === API KEYS через переменные окружения ===
# Формат: API_KEYS="test-token-123,another-token-456,admin-789"
# Если переменная не задана — используем тестовый ключ (только для разработки!)
raw_api_keys = os.getenv("API_KEYS", "test-token-123")  # fallback только для dev
API_KEYS = {key.strip() for key in raw_api_keys.split(",") if key.strip()}
API_KEY_HEADER = "X-API-KEY"

print(f"🔑 Загружено {len(API_KEYS)} API-ключ(ей) из переменной окружения API_KEYS")
if "test-token-123" in API_KEYS:
    print("⚠️  Обнаружен тестовый ключ 'test-token-123' — рекомендуется заменить в production!")

# Менеджер временных файлов (расшифрованные, TTL 1 час)
file_storage = FileStorageManager(
    storage_dir=DECRYPTED_DIR,
    ttl_seconds=3600
)

# Менеджер очистки зашифрованных файлов (TTL 30 дней)
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
            print(f"❌ Ошибка чтения ключа: {e}")
            audit_logger.log_operation(
                action="keys_load_failed",
                filename="age.key",
                user="system",
                reason=str(e),
                success=False
            )
            raise
    
    else:
        if dev_mode:
            print("🔐 DEV_MODE включён — генерируем новую пару ключей...")
            try:
                private_key, public_key = await crypto_manager.generate_keypair(PRIVATE_KEY_PATH)
                
                pub_path = KEYS_DIR / "age.pub"
                with open(pub_path, "w", encoding="utf-8") as f:
                    f.write(f"# Public key for SMDG\n{public_key}\n")
                
                _PUBLIC_KEY = public_key
                print(f"✅ Новые ключи созданы: {PRIVATE_KEY_PATH}")
                print("⚠️  В production используйте вручную созданные ключи и НЕ включайте DEV_MODE!")
                
                audit_logger.log_operation(
                    action="keys_generated",
                    filename="age.key",
                    user="system",
                    reason="Автоматическая генерация в DEV_MODE",
                    success=True
                )
                return public_key
            
            except Exception as e:
                print(f"❌ Ошибка генерации ключей: {e}")
                raise
        else:
            error_msg = (
                f"❌ Критическая ошибка: приватный ключ не найден ({PRIVATE_KEY_PATH})\n"
                "Автоматическая генерация запрещена вне DEV_MODE.\n"
                "Решение:\n"
                "  1. Создайте ключ: age-keygen -o keys/age.key\n"
                "  2. Смонтируйте директорию keys/ в Docker\n"
                "  3. Перезапустите сервис"
            )
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
    """Безопасный доступ к публичному ключу"""
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