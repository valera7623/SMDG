# app/core/storage.py
from pathlib import Path
import asyncio
import time
import os
import shutil
from datetime import datetime

class FileStorageManager:
    def __init__(self, storage_dir: Path, ttl_seconds: int):
        """Управление временными файлами с автоматической очисткой"""
        self.storage_dir = storage_dir
        self.ttl = ttl_seconds
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.files = {}  # path -> creation_time
        
        print(f"📁 FileStorageManager инициализирован для {storage_dir}")
        print(f"   TTL: {ttl_seconds} секунд ({ttl_seconds/3600:.1f} часов)")
        
        # Сразу удаляем все старые файлы при инициализации
        self._cleanup_old_files_sync()

    async def save_file(self, path: Path):
        """Сохраняем ссылку на временный файл"""
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        self.files[path] = time.time()
        
        file_size = path.stat().st_size
        print(f"📁 Сохранен файл в хранилище: {path.name} ({file_size} байт)")
        print(f"   Всего временных файлов: {len(self.files)}")
        
        # Немедленно планируем удаление через TTL
        asyncio.create_task(self._schedule_file_deletion(path))

    async def _schedule_file_deletion(self, path: Path):
        """Планирует удаление файла через TTL"""
        await asyncio.sleep(self.ttl)
        
        if path in self.files:
            try:
                if path.exists():
                    file_size = path.stat().st_size
                    path.unlink()
                    print(f"🗑️  Удален файл по TTL: {path.name} ({file_size} байт)")
                
                # Удаляем из словаря
                del self.files[path]
                print(f"   Осталось временных файлов: {len(self.files)}")
            except Exception as e:
                print(f"❌ Ошибка удаления файла {path}: {e}")

    async def cleanup_task(self):
        """Фоновая задача для периодической очистки"""
        print(f"🧹 Запущена фоновая очистка временных файлов (интервал: 60 сек)")
        
        while True:
            try:
                await self._cleanup_old_files_async()
                await asyncio.sleep(60)  # Проверка каждую минуту
            except Exception as e:
                print(f"❌ Ошибка в cleanup_task: {e}")
                await asyncio.sleep(30)

    def _cleanup_old_files_sync(self):
        """Синхронная очистка старых файлов при старте"""
        print("🧹 Начальная очистка старых файлов...")
        
        if not self.storage_dir.exists():
            return
        
        deleted_count = 0
        current_time = time.time()
        
        for item in self.storage_dir.iterdir():
            if item.is_file():
                try:
                    file_age = current_time - item.stat().st_mtime
                    
                    # Удаляем файлы старше TTL
                    if file_age > self.ttl:
                        file_size = item.stat().st_size
                        item.unlink()
                        deleted_count += 1
                        print(f"   🗑️  Удален старый файл: {item.name} ({file_size} байт, {file_age/3600:.1f} часов)")
                except Exception as e:
                    print(f"   ❌ Ошибка удаления {item}: {e}")
        
        if deleted_count > 0:
            print(f"✅ Удалено {deleted_count} старых файлов")
        else:
            print("   ℹ️  Старых файлов не найдено")

    async def _cleanup_old_files_async(self):
        """Асинхронная очистка старых файлов"""
        if not self.storage_dir.exists():
            return
        
        current_time = time.time()
        deleted_count = 0
        
        # Удаляем файлы из словаря которые превысили TTL
        to_delete = []
        for path, creation_time in self.files.items():
            file_age = current_time - creation_time
            if file_age > self.ttl:
                to_delete.append(path)
        
        for path in to_delete:
            try:
                if path.exists():
                    file_size = path.stat().st_size
                    path.unlink()
                    print(f"🧹 Удален файл по TTL из словаря: {path.name} ({file_size} байт)")
                
                if path in self.files:
                    del self.files[path]
                deleted_count += 1
            except Exception as e:
                print(f"❌ Ошибка удаления {path}: {e}")
        
        # Также проверяем всю директорию на случай если есть файлы не в словаре
        for item in self.storage_dir.iterdir():
            if item.is_file() and item not in self.files:
                try:
                    file_age = current_time - item.stat().st_mtime
                    if file_age > self.ttl:
                        file_size = item.stat().st_size
                        item.unlink()
                        print(f"🧹 Удален бродячий файл: {item.name} ({file_size} байт)")
                        deleted_count += 1
                except Exception as e:
                    print(f"❌ Ошибка удаления бродячего файла {item}: {e}")
        
        if deleted_count > 0:
            print(f"🧹 Удалено {deleted_count} файлов")

    def get_stats(self):
        """Статистика по временным файлам"""
        current_time = time.time()
        files_info = []
        
        for path, creation_time in self.files.items():
            if path.exists():
                file_age = current_time - creation_time
                time_left = max(0, self.ttl - file_age)
                
                files_info.append({
                    "name": path.name,
                    "size": path.stat().st_size,
                    "age_seconds": file_age,
                    "time_left_seconds": time_left,
                    "created": datetime.fromtimestamp(creation_time).isoformat()
                })
        
        return {
            "total_files": len(self.files),
            "storage_dir": str(self.storage_dir),
            "ttl_seconds": self.ttl,
            "files": files_info
        }

    def force_cleanup(self):
        """Принудительная очистка всех временных файлов"""
        print("🧹 Принудительная очистка всех временных файлов...")
        
        if not self.storage_dir.exists():
            return {"deleted": 0, "error": "Directory not exists"}
        
        deleted_count = 0
        errors = []
        
        for item in self.storage_dir.iterdir():
            if item.is_file():
                try:
                    file_size = item.stat().st_size
                    item.unlink()
                    deleted_count += 1
                    print(f"   🗑️  Удален: {item.name} ({file_size} байт)")
                except Exception as e:
                    error_msg = f"Ошибка удаления {item}: {e}"
                    errors.append(error_msg)
                    print(f"   ❌ {error_msg}")
        
        # Очищаем словарь
        self.files.clear()
        
        result = {"deleted": deleted_count}
        if errors:
            result["errors"] = errors
        
        print(f"✅ Удалено {deleted_count} файлов")
        return result