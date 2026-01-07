from pathlib import Path
from .crypto.crypto import CryptoManager, crypto_manager
import asyncio

BASE_DIR = Path(__file__).parent.parent

# Директории
UPLOAD_DIR = BASE_DIR / "uploads"
ENCRYPTED_DIR = BASE_DIR / "encrypted"
DECRYPTED_DIR = BASE_DIR / "decrypted"

# Создаём папки
for d in [UPLOAD_DIR, ENCRYPTED_DIR, DECRYPTED_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Пути к ключам
KEYS_DIR = BASE_DIR / "keys"
PRIVATE_KEY_PATH = KEYS_DIR / "age.key"
PUBLIC_KEY = None

# API ключи (для v0.1 можно так, потом перенести в БД/переменные окружения)
API_KEYS = {"test-token-123"}
API_KEY_HEADER = "X-API-KEY"

# Хранилище файлов с TTL
from app.storage.storage import FileStorageManager
file_storage = FileStorageManager(
    storage_dir=DECRYPTED_DIR,
    ttl_seconds=3600  # 1 час
)

async def init_keys():
    """Инициализация ключей"""
    KEYS_DIR.mkdir(exist_ok=True)
    
    if not PRIVATE_KEY_PATH.exists():
        # Генерируем ключи
        print("🔐 Генерация ключей age...")
        private_key, public_key = await crypto_manager.generate_keypair(PRIVATE_KEY_PATH)
        
        # Сохраняем публичный ключ
        public_key_path = KEYS_DIR / "age.pub"
        with open(public_key_path, "w") as f:
            f.write(public_key)
        
        global PUBLIC_KEY
        PUBLIC_KEY = public_key
        print("✅ Ключи созданы")
    else:
        # Читаем существующий публичный ключ
        with open(PRIVATE_KEY_PATH, "r") as f:
            for line in f:
                if line.startswith("# public key:"):
                    PUBLIC_KEY = line.split(": ")[1].strip()
                    break
        print("✅ Ключи загружены")
    
    # Запускаем очистку старых файлов
    asyncio.create_task(file_storage.cleanup_task())

