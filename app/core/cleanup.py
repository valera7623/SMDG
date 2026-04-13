# app/core/cleanup.py
import asyncio
from pathlib import Path
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.storage_backend import StorageBackend


class FileCleanupManager:
    def __init__(self, encrypted_dir: Path, ttl_days: int = 30, storage_backend: StorageBackend = None):
        self.encrypted_dir = encrypted_dir
        self.ttl_days = ttl_days
        self.storage_backend = storage_backend
        self.logger = logging.getLogger(__name__)

        self.retention_policies = {
            '.txt': 30,
            '.pdf': 90,
            '.dcm': 365,
            '.jpg': 180,
            '.age': 30
        }

        # Шедулер создаётся один раз при инициализации объекта
        self.scheduler = AsyncIOScheduler()
        self._started = False  # флаг, чтобы не запускать повторно

    async def start_cleanup_task(self):
        """Запуск периодической очистки — безопасно вызывать несколько раз"""
        if self._started:
            self.logger.info("APScheduler уже запущен — повторный запуск пропущен")
            return

        self.scheduler.add_job(
            self._cleanup_old_files,
            trigger=IntervalTrigger(minutes=30),
            id='cleanup_old_files',
            name='Очистка старых зашифрованных файлов каждые 30 минут',
            replace_existing=True
        )

        self.scheduler.start()
        self._started = True
        self.logger.info("🗓️ APScheduler запущен: очистка каждые 30 минут")

    async def stop_cleanup_task(self):
        """Остановка периодической очистки"""
        if self._started and self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            self._started = False
            self.logger.info("🛑 APScheduler очистки остановлен")
        else:
            self.logger.debug("APScheduler не запущен — остановка пропущена")

    async def _cleanup_old_files(self):
        """Очистка старых файлов с батчингом"""
        self.logger.info("🚮 Запуск периодической очистки старых файлов")

        # Используем StorageBackend если доступен
        if self.storage_backend:
            return await self._cleanup_via_storage_backend()

        # Fallback к локальной файловой системе
        if not self.encrypted_dir.exists():
            self.logger.warning("Директория encrypted не существует")
            return {"total": 0, "deleted": 0, "errors": []}

        now = datetime.now()
        files_to_delete = []
        errors = []

        for file_path in self.encrypted_dir.iterdir():
            if not file_path.is_file():
                continue

            ttl_days = self._get_ttl_for_file(file_path)
            try:
                last_access = datetime.fromtimestamp(file_path.stat().st_atime)
                file_age = (now - last_access).days
                if file_age > ttl_days:
                    files_to_delete.append(file_path)
            except Exception as e:
                errors.append(f"Ошибка stat {file_path}: {e}")
                continue

        deleted_count = 0
        batch_size = 50

        for i in range(0, len(files_to_delete), batch_size):
            batch = files_to_delete[i:i + batch_size]
            for file_path in batch:
                try:
                    file_size = file_path.stat().st_size
                    file_path.unlink()
                    deleted_count += 1
                    self.logger.info(f"Удалён: {file_path.name} ({file_size} байт, возраст {file_age} дней)")
                except Exception as e:
                    errors.append(str(e))
                    self.logger.error(f"Ошибка удаления {file_path}: {e}")

            await asyncio.sleep(0.05)  # небольшая пауза между батчами

        result = {
            "total_scanned": len(list(self.encrypted_dir.iterdir())),
            "deleted": deleted_count,
            "errors": errors
        }

        self.logger.info(f"Очистка завершена: удалено {deleted_count} файлов, ошибок {len(errors)}")
        return result

    async def _cleanup_via_storage_backend(self):
        """Очистка через StorageBackend (S3 или локальная)"""
        try:
            objects = await self.storage_backend.list_objects()
        except Exception as e:
            self.logger.error(f"Ошибка получения списка объектов: {e}")
            return {"total": 0, "deleted": 0, "errors": [str(e)]}

        now = datetime.now()
        keys_to_delete = []
        errors = []

        for obj in objects:
            ttl_days = self._get_ttl_for_file_by_name(obj.key)

            if obj.last_modified:
                last_modified = datetime.fromtimestamp(obj.last_modified)
                file_age = (now - last_modified).days

                if file_age > ttl_days:
                    keys_to_delete.append(obj.key)
            else:
                # Если нет timestamp — пропускаем (безопаснее)
                self.logger.debug(f"Нет timestamp для {obj.key}, пропускаем")

        deleted_count = 0
        batch_size = 50

        for i in range(0, len(keys_to_delete), batch_size):
            batch = keys_to_delete[i:i + batch_size]
            try:
                result = await self.storage_backend.delete_many(batch)
                deleted_count += result.get("deleted_count", 0)
                if result.get("errors"):
                    errors.extend(result["errors"])
            except Exception as e:
                errors.append(f"Batch delete error: {e}")
                self.logger.error(f"Ошибка пакетного удаления: {e}")

            await asyncio.sleep(0.05)

        result = {
            "total_scanned": len(objects),
            "deleted": deleted_count,
            "errors": errors
        }

        self.logger.info(f"Очистка завершена: удалено {deleted_count} файлов, ошибок {len(errors)}")
        return result

    def _get_ttl_for_file(self, file_path: Path) -> int:
        for ext, ttl in self.retention_policies.items():
            if file_path.name.lower().endswith(ext):
                return ttl
        return self.ttl_days

    def _get_ttl_for_file_by_name(self, filename: str) -> int:
        for ext, ttl in self.retention_policies.items():
            if filename.lower().endswith(ext):
                return ttl
        return self.ttl_days

    def get_cleanup_stats(self) -> dict:
        """Статистика по файлам, которые будут удалены при следующей очистке"""
        # Если есть StorageBackend — используем его
        if self.storage_backend:
            return self._get_stats_via_storage_backend()

        if not self.encrypted_dir.exists():
            return {"total": 0, "to_delete": 0, "files": []}

        now = datetime.now()
        files_to_delete = []

        for file_path in self.encrypted_dir.iterdir():
            if not file_path.is_file():
                continue

            ttl_days = self._get_ttl_for_file(file_path)
            try:
                last_access = datetime.fromtimestamp(file_path.stat().st_atime)
                file_age = (now - last_access).days
                if file_age > ttl_days:
                    files_to_delete.append({
                        "name": file_path.name,
                        "size": file_path.stat().st_size,
                        "age_days": file_age,
                        "last_access": last_access.isoformat(),
                        "ttl_days": ttl_days,
                        "scheduled_deletion": (last_access + timedelta(days=ttl_days)).isoformat()
                    })
            except Exception as e:
                self.logger.warning(f"Ошибка stat {file_path}: {e}")
                continue

        return {
            "total": len(list(self.encrypted_dir.iterdir())),
            "to_delete": len(files_to_delete),
            "files": files_to_delete
        }

    def _get_stats_via_storage_backend(self) -> dict:
        """Статистика через StorageBackend"""
        try:
            objects = self.storage_backend.list_objects()
            # Для синхронного вызова (APScheduler может вызывать синхронно)
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                # Если есть running loop — создаём задачу
                objects = asyncio.ensure_future(objects)
            except RuntimeError:
                # Нет running loop — используем asyncio.run
                objects = asyncio.run(objects)
        except Exception as e:
            self.logger.warning(f"Ошибка получения списка объектов: {e}")
            return {"total": 0, "to_delete": 0, "files": [], "error": str(e)}

        # Если objects — это Future/Task, ждём результат
        if hasattr(objects, '__await__'):
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # В async контексте — возвращаем dict с пометкой
                    return {"total": 0, "to_delete": 0, "files": [], "note": "async_context"}
                objects = loop.run_until_complete(objects)
            except Exception as e:
                self.logger.warning(f"Ошибка получения объектов: {e}")
                return {"total": 0, "to_delete": 0, "files": [], "error": str(e)}

        now = datetime.now()
        files_to_delete = []

        for obj in objects:
            ttl_days = self._get_ttl_for_file_by_name(obj.key)

            if obj.last_modified:
                last_modified = datetime.fromtimestamp(obj.last_modified)
                file_age = (now - last_modified).days

                if file_age > ttl_days:
                    files_to_delete.append({
                        "name": obj.key,
                        "size": obj.size,
                        "age_days": file_age,
                        "last_access": last_modified.isoformat(),
                        "ttl_days": ttl_days,
                        "scheduled_deletion": (last_modified + timedelta(days=ttl_days)).isoformat()
                    })

        return {
            "total": len(objects),
            "to_delete": len(files_to_delete),
            "files": files_to_delete
        }