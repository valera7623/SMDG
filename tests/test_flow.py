# app/tests/test_flow.py
import asyncio
from pathlib import Path
import shutil
import os
from app.crypto.crypto import crypto_manager, CryptoManager
from app.storage.storage import FileStorageManager

# Константы теста
TEST_UPLOAD_DIR = Path("test_uploads")
TEST_UPLOAD_DIR.mkdir(exist_ok=True)
TEST_FILE_PATH = TEST_UPLOAD_DIR / "test_file.txt"
TTL_SECONDS = 5  # Для быстрого теста

async def test_flow():
    print("🚀 Запуск end-to-end теста SMDG")

    # --- 1. Генерация ключей ---
    private_key_path = Path("private_key_test.key")
    public_key_path = Path("public_key_test.key")

    if not private_key_path.exists() or not public_key_path.exists():
        private_key, public_key = await crypto_manager.generate_keypair()
        private_key_path.write_text(private_key)
        public_key_path.write_text(public_key)
        print("✅ Ключи сгенерированы")
    else:
        print("✅ Ключи уже существуют")

    # --- 2. Создаём тестовый файл для загрузки ---
    TEST_FILE_PATH.write_text("Это тестовый файл для SMDG")
    print(f"✅ Тестовый файл создан: {TEST_FILE_PATH}")

    # --- 3. Шифруем файл ---
    public_key_content = public_key_path.read_text().splitlines()[0]
    encrypted_path = await crypto_manager.encrypt_file(TEST_FILE_PATH, public_key_content)
    print(f"✅ Файл зашифрован: {encrypted_path}")

    # --- 4. Сохраняем файл в storage с TTL ---
    storage = FileStorageManager(storage_dir=Path("test_storage"), ttl_seconds=TTL_SECONDS)
    await storage.save_file(encrypted_path)
    print(f"✅ Файл добавлен в storage с TTL={TTL_SECONDS}s")

    # --- 5. Проверяем наличие файла в storage до TTL ---
    files = storage.list_files()
    print(f"📦 Файлы в storage до очистки: {files}")
    assert encrypted_path.name in files, "Файл должен быть в storage"

    # --- 6. Ждём, пока TTL истечёт и запускаем одноразовую очистку ---
    print(f"⏳ Ждём {TTL_SECONDS+1} секунд для проверки TTL...")
    await asyncio.sleep(TTL_SECONDS + 1)
    await storage.cleanup_task_once()
    files_after = storage.list_files()
    print(f"📦 Файлы в storage после TTL: {files_after}")
    assert encrypted_path.name not in files_after, "Файл должен быть удалён по TTL"

    # --- 7. Дешифруем файл и проверяем содержимое ---
    # Сохраним заново для дешифрования
    await storage.save_file(encrypted_path)
    decrypted_path = await crypto_manager.decrypt_file(encrypted_path, private_key_path)
    decrypted_content = decrypted_path.read_text()
    assert decrypted_content == "Это тестовый файл для SMDG", "Содержимое не совпадает"
    print(f"✅ Файл успешно расшифрован: {decrypted_path}")

    # --- 8. Очистка тестовых файлов ---
    shutil.rmtree(TEST_UPLOAD_DIR, ignore_errors=True)
    shutil.rmtree(Path("test_storage"), ignore_errors=True)
    private_key_path.unlink(missing_ok=True)
    public_key_path.unlink(missing_ok=True)
    if decrypted_path.exists():
        decrypted_path.unlink()
    print("🧹 Тестовые файлы удалены")
    print("🎉 End-to-end тест пройден успешно!")

if __name__ == "__main__":
    asyncio.run(test_flow())
