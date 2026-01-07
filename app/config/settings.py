from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Директории
UPLOAD_DIR = BASE_DIR / "uploads"
ENCRYPTED_DIR = BASE_DIR / "encrypted"
DECRYPTED_DIR = BASE_DIR / "decrypted"

# Ключи
PRIVATE_KEY_PATH = BASE_DIR / "private_key.key"
PUBLIC_KEY_PATH = BASE_DIR / "public_key.key"

# Создание директорий при старте
for d in [UPLOAD_DIR, ENCRYPTED_DIR, DECRYPTED_DIR]:
    d.mkdir(exist_ok=True)
