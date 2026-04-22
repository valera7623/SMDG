# app/core/cleanup.py
import asyncio
from pathlib import Path
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.storage_backend import StorageBackend, LocalStorageBackend
from app.core.config import settings
from app.core.timeout import TimeoutError, run_with_timeout


class FileCleanupManager:
    def __init__(self, encrypted_dir: Path, ttl_days: int = 30, storage_backend: StorageBackend = None):
        self.encrypted_dir = encrypted_dir
        self.ttl_days = ttl_days
        # Единый путь работы с файлами через StorageBackend:
        # если backend не передан — автоматически создаём LocalStorageBackend над encrypted_dir.
        self.storage_backend: StorageBackend = storage_backend or LocalStorageBackend(encrypted_dir)
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

    def _get_ttl_for_file_by_name(self, filename: str) -> int:
        for ext, ttl in self.retention_policies.items():
            if filename.lower().endswith(ext):
                return ttl
        return self.ttl_days

    def _get_ttl_for_file(self, file_path: Path) -> int:
        """Совместимость: TTL по объекту Path."""
        return self._get_ttl_for_file_by_name(file_path.name)

    async def _collect_expired(self):
        """Собирает список ключей с истёкшим TTL. Возвращает (keys, meta_by_key, total)."""
        try:
            objects = await self.storage_backend.list_objects()
        except Exception as e:
            self.logger.error(f"Ошибка получения списка объектов: {e}")
            raise

        now = datetime.now()
        keys_to_delete: list[str] = []
        meta_by_key: dict[str, dict] = {}

        for obj in objects:
            if obj.last_modified is None:
                # Безопаснее пропустить объекты без timestamp
                self.logger.debug(f"Нет timestamp для {obj.key}, пропускаем")
                continue

            ttl_days = self._get_ttl_for_file_by_name(obj.key)
            last_modified = datetime.fromtimestamp(obj.last_modified)
            file_age = (now - last_modified).days

            if file_age > ttl_days:
                keys_to_delete.append(obj.key)
                meta_by_key[obj.key] = {
                    "size": obj.size,
                    "age_days": file_age,
                    "last_access": last_modified.isoformat(),
                    "ttl_days": ttl_days,
                    "scheduled_deletion": (last_modified + timedelta(days=ttl_days)).isoformat(),
                }

        return keys_to_delete, meta_by_key, len(objects)

    async def _cleanup_old_files(self):
        """Очистка старых файлов с батчингом (единый путь через StorageBackend)."""
        self.logger.info("🚮 Запуск периодической очистки старых файлов")

        try:
            keys_to_delete, _meta, total_scanned = await run_with_timeout(
                self._collect_expired(),
                timeout_seconds=float(settings.BACKGROUND_TASK_TIMEOUT_SECONDS),
                error_message="Cleanup task timeout",
                service="background",
                operation="cleanup_collect_expired",
            )
        except TimeoutError as e:
            self.logger.error("Cleanup task timed out: %s", e)
            return {"total": 0, "deleted": 0, "errors": [str(e)]}
        except Exception as e:
            return {"total": 0, "deleted": 0, "errors": [str(e)]}

        deleted_count = 0
        errors: list[str] = []
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

            await asyncio.sleep(0.05)  # небольшая пауза между батчами

        self.logger.info(f"Очистка завершена: удалено {deleted_count} файлов, ошибок {len(errors)}")
        return {
            "total_scanned": total_scanned,
            "deleted": deleted_count,
            "errors": errors,
        }

    async def get_cleanup_stats(self) -> dict:
        """Статистика по файлам, которые будут удалены при следующей очистке."""
        try:
            keys_to_delete, meta_by_key, total = await self._collect_expired()
        except Exception as e:
            return {"total": 0, "to_delete": 0, "files": [], "error": str(e)}

        files = [{"name": key, **meta_by_key[key]} for key in keys_to_delete]
        return {
            "total": total,
            "to_delete": len(files),
            "files": files,
        }
