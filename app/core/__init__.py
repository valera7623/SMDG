# app/core/__init__.py
from pathlib import Path
from app.crypto.crypto import crypto_manager
import asyncio
from app.storage.storage import FileStorageManager

BASE_DIR = Path.cwd()

# Директории
UPLOAD_DIR = BASE_DIR / "uploads"
ENCRYPTED_DIR = BASE_DIR / "encrypted"
DECRYPTED_DIR = BASE_DIR / "decrypted"

# Создаём папки
for d in [UPLOAD_DIR, ENCRYPTED_DIR, DECRYPTED_DIR]:
    d.mkdir(parents=True, exist_ok=True)
    print(f"✅ Директория: {d}")
    
# Пути к ключам
KEYS_DIR = BASE_DIR / "keys"
KEYS_DIR.mkdir(exist_ok=True)
PRIVATE_KEY_PATH = KEYS_DIR / "age.key"

# Глобальная переменная для публичного ключа (будет установлена в init_keys)
_PUBLIC_KEY = None

# API ключи
API_KEYS = {"test-token-123"}
API_KEY_HEADER = "X-API-KEY"

# Хранилище файлов с TTL
file_storage = FileStorageManager(
    storage_dir=DECRYPTED_DIR,
    ttl_seconds=3600  # 1 час
)

async def init_keys():
    """Инициализация ключей - возвращает публичный ключ"""
    global _PUBLIC_KEY
    
    print(f"🔐 Инициализация ключей...")
    
    if not PRIVATE_KEY_PATH.exists():
        print("   Генерация новых ключей age...")
        try:
            # Генерируем ключи
            private_key, public_key = await crypto_manager.generate_keypair(PRIVATE_KEY_PATH)
            _PUBLIC_KEY = public_key
            
            # Сохраняем публичный ключ отдельно
            public_key_path = KEYS_DIR / "age.pub"
            with open(public_key_path, "w") as f:
                f.write(f"# Public key for SMDG\n{_PUBLIC_KEY}")
            
            print(f"   ✅ Ключи созданы")
            
        except Exception as e:
            print(f"   ❌ Ошибка генерации ключей: {e}")
            raise
    else:
        print("   Загрузка существующих ключей...")
        try:
            with open(PRIVATE_KEY_PATH, "r") as f:
                content = f.read()
                for line in content.splitlines():
                    if line.startswith("# public key:"):
                        _PUBLIC_KEY = line.split(": ")[1].strip()
                        print(f"   ✅ Публичный ключ загружен")
                        break
                
                if not _PUBLIC_KEY:
                    # Попробуем прочитать из отдельного файла
                    public_key_path = KEYS_DIR / "age.pub"
                    if public_key_path.exists():
                        with open(public_key_path, "r") as pf:
                            for line in pf:
                                if not line.startswith("#"):
                                    _PUBLIC_KEY = line.strip()
                                    print(f"   ✅ Публичный ключ загружен из age.pub")
                                    break
                    
                    if not _PUBLIC_KEY:
                        raise Exception("Не удалось загрузить публичный ключ")
        except Exception as e:
            print(f"   ❌ Ошибка загрузки ключей: {e}")
            raise
    
    print(f"   Публичный ключ: {_PUBLIC_KEY[:30]}...")
    
    # Запускаем очистку старых файлов
    asyncio.create_task(file_storage.cleanup_task())
    
    return _PUBLIC_KEY

def get_public_key():
    """Функция для получения публичного ключа"""
    if _PUBLIC_KEY is None:
        raise ValueError("Public key not initialized. Call init_keys() first.")
    return _PUBLIC_KEY

# Экспортируем все необходимые переменные
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
    'init_keys'
]