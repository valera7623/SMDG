# app/core/storage.py
from pathlib import Path
import asyncio
import time
from datetime import datetime
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)


class FileStorageManager:
    """Менеджер временных расшифрованных файлов с автоматической очисткой по TTL."""

    def __init__(self, storage_dir: Path, ttl_seconds: int):
        self.storage_dir = storage_dir
        self.ttl = ttl_seconds
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.files: Dict[Path, float] = {}  # path -> creation_time

        logger.info(f"📁 FileStorageManager инициализирован для {storage_dir}")
        logger.info(f"   TTL: {ttl_seconds} секунд ({ttl_seconds / 3600:.1f} часов)")

        # Начальная очистка при старте
        self._cleanup_old_files_sync()

    async def save_file(self, path: Path) -> None:
        """Сохраняет файл во временное хранилище и планирует его удаление."""
        if not path.exists():
            raise FileNotFoundError(f"Файл не найден: {path}")

        self.files[path] = time.time()

        file_size = path.stat().st_size
        logger.info(f"📁 Сохранён временный файл: {path.name} ({file_size} байт)")
        logger.debug(f"   Всего временных файлов в памяти: {len(self.files)}")

        # Планируем удаление
        asyncio.create_task(self._schedule_file_deletion(path))

    async def _schedule_file_deletion(self, path: Path) -> None:
        """Удаляет файл через TTL секунд."""
        await asyncio.sleep(self.ttl)

        if path in self.files:
            try:
                if path.exists():
                    file_size = path.stat().st_size
                    path.unlink()
                    logger.info(f"🗑️ Удалён файл по TTL: {path.name} ({file_size} байт)")

                self.files.pop(path, None)
                logger.debug(f"   Осталось временных файлов: {len(self.files)}")
            except Exception as e:
                logger.error(f"❌ Ошибка удаления файла {path}: {e}")

    async def cleanup_task(self) -> None:
        """Фоновая периодическая очистка (запускается в lifespan)."""
        logger.info("🧹 Запущена фоновая задача очистки временных файлов (интервал 60 сек)")

        while True:
            try:
                await self._cleanup_old_files_async()
                await asyncio.sleep(60)
            except Exception as e:
                logger.error(f"❌ Ошибка в cleanup_task: {e}")
                await asyncio.sleep(30)

    def _cleanup_old_files_sync(self) -> None:
        """Синхронная начальная очистка при старте приложения."""
        logger.info("🧹 Начальная очистка старых файлов...")

        if not self.storage_dir.exists():
            return

        deleted_count = 0
        current_time = time.time()

        for item in self.storage_dir.iterdir():
            if item.is_file():
                try:
                    file_age = current_time - item.stat().st_mtime
                    if file_age > self.ttl:
                        file_size = item.stat().st_size
                        item.unlink()
                        deleted_count += 1
                        logger.info(f"   🗑️ Удалён старый файл: {item.name} ({file_size} байт, {file_age/3600:.1f} ч)")
                except Exception as e:
                    logger.error(f"   ❌ Ошибка удаления {item}: {e}")

        if deleted_count > 0:
            logger.info(f"✅ Удалено {deleted_count} старых файлов при старте")
        else:
            logger.info("   ℹ️ Старых файлов не найдено")

    async def _cleanup_old_files_async(self) -> None:
        """Асинхронная периодическая очистка."""
        if not self.storage_dir.exists():
            return

        current_time = time.time()
        to_delete: List[Path] = []

        # Файлы из словаря
        for path, creation_time in list(self.files.items()):
            if current_time - creation_time > self.ttl:
                to_delete.append(path)

        deleted_count = 0
        for path in to_delete:
            try:
                if path.exists():
                    file_size = path.stat().st_size
                    path.unlink()
                    logger.info(f"🧹 Удалён файл по TTL: {path.name} ({file_size} байт)")
                self.files.pop(path, None)
                deleted_count += 1
            except Exception as e:
                logger.error(f"❌ Ошибка удаления {path}: {e}")

        # "Бродячие" файлы (не попали в словарь)
        for item in self.storage_dir.iterdir():
            if item.is_file() and item not in self.files:
                try:
                    file_age = current_time - item.stat().st_mtime
                    if file_age > self.ttl:
                        file_size = item.stat().st_size
                        item.unlink()
                        logger.info(f"🧹 Удалён бродячий файл: {item.name} ({file_size} байт)")
                        deleted_count += 1
                except Exception as e:
                    logger.error(f"❌ Ошибка удаления бродячего файла {item}: {e}")

        if deleted_count > 0:
            logger.info(f"🧹 Периодическая очистка: удалено {deleted_count} файлов")

    def get_stats(self) -> Dict[str, Any]:
        """Статистика временных файлов."""
        current_time = time.time()
        files_info = []

        for path, creation_time in self.files.items():
            if path.exists():
                file_age = current_time - creation_time
                time_left = max(0, self.ttl - file_age)
                files_info.append({
                    "name": path.name,
                    "size": path.stat().st_size,
                    "age_seconds": round(file_age, 1),
                    "time_left_seconds": round(time_left, 1),
                    "created": datetime.fromtimestamp(creation_time).isoformat()
                })

        return {
            "total_files": len(self.files),
            "storage_dir": str(self.storage_dir),
            "ttl_seconds": self.ttl,
            "files": files_info
        }

    def force_cleanup(self) -> Dict[str, Any]:
        """Принудительная очистка всех временных файлов."""
        logger.info("🧹 Запущена принудительная очистка всех временных файлов")

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
                    logger.info(f"   🗑️ Удалён: {item.name} ({file_size} байт)")
                except Exception as e:
                    errors.append(f"Ошибка удаления {item}: {e}")
                    logger.error(f"   ❌ {e}")

        self.files.clear()

        result = {"deleted": deleted_count}
        if errors:
            result["errors"] = errors

        logger.info(f"✅ Принудительная очистка завершена. Удалено {deleted_count} файлов")
        return result