# app/storage/storage.py
from pathlib import Path
import asyncio
import time

class FileStorageManager:
    def __init__(self, storage_dir: Path, ttl_seconds: int):
        """Управление временными файлами"""
        self.storage_dir = storage_dir
        self.ttl = ttl_seconds
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.files = {}  # path -> creation_time
        
        print(f"📁 FileStorageManager инициализирован для {storage_dir}")
        print(f"   TTL: {ttl_seconds} секунд")

    async def save_file(self, path: Path):
        """Сохраняем ссылку на временный файл"""
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        self.files[path] = time.time()
        print(f"📁 Сохранен файл в хранилище: {path.name}")
        print(f"   Всего временных файлов: {len(self.files)}")

    async def cleanup_task(self):
        """Задача для очистки старых файлов"""
        print(f"🧹 Запущена очистка временных файлов (интервал: 30 сек)")
        
        while True:
            try:
                now = time.time()
                to_delete = []
                
                for path, creation_time in self.files.items():
                    age = now - creation_time
                    if age > self.ttl:
                        to_delete.append(path)
                
                if to_delete:
                    print(f"🧹 Удаляю {len(to_delete)} старых файлов...")
                    for path in to_delete:
                        try:
                            if path.exists():
                                size = path.stat().st_size
                                path.unlink()
                                print(f"   Удален: {path.name} ({size} bytes)")
                        except Exception as e:
                            print(f"   Ошибка удаления {path}: {e}")
                        
                        # Удаляем из словаря
                        if path in self.files:
                            del self.files[path]
                
                # Также чистим всю директорию decrypted от старых файлов
                if self.storage_dir.exists():
                    for item in self.storage_dir.iterdir():
                        if item.is_file() and item not in self.files:
                            # Файл не в нашем управлении, но старый
                            file_age = now - item.stat().st_mtime
                            if file_age > self.ttl:
                                try:
                                    size = item.stat().st_size
                                    item.unlink()
                                    print(f"   Очистка: удален старый файл {item.name}")
                                except:
                                    pass
                
            except Exception as e:
                print(f"❌ Ошибка в cleanup_task: {e}")
            
            await asyncio.sleep(30)  # Проверяем каждые 30 секунд