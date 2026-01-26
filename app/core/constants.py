# app/core/constants.py
from pathlib import Path

BASE_DIR = Path.cwd()
UPLOAD_DIR = BASE_DIR / "uploads"
ENCRYPTED_DIR = BASE_DIR / "encrypted"
DECRYPTED_DIR = BASE_DIR / "decrypted"
PRIVATE_KEY_PATH = BASE_DIR / "keys" / "age.key"