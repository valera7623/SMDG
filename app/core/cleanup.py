# app/core/cleanup.py
import asyncio
from pathlib import Path
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

class FileCleanupManager:
    def __init__(self, encrypted_dir: Path, ttl_days: int = 30):
        self.encrypted_dir = encrypted_dir
        self.ttl_days = ttl_days
        self.logger = logging.getLogger(__name__)
        
        self.retention_policies = {
            '.txt': 30,
            '.pdf': 90,
            '.dcm': 365,
            '.jpg': 180,
            '.age': 30
        }

    async def start_cleanup_task(self):
        """Запуск периодической очистки каждые 30 минут через APScheduler"""
        scheduler = AsyncIOScheduler()
        
        scheduler.add_job(
            self._cleanup_old_files,
            trigger=IntervalTrigger(minutes=30),
            id='cleanup_old_files',
            name='Periodic cleanup of old encrypted files',
            replace_existing=True
        )
        
        scheduler.start()
        self.logger.info("🗓️ APScheduler запущен: очистка каждые 30 минут")

    async def _cleanup_old_files(self):
        """Очистка старых файлов с батчингом"""
        self.logger.info("🚮 Запуск очистки старых файлов")
        
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
            last_access = datetime.fromtimestamp(file_path.stat().st_atime)
            file_age = (now - last_access).days
            if file_age > ttl_days:
                files_to_delete.append(file_path)

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
            await asyncio.sleep(0.05)  # пауза между батчами

        result = {
            "total_scanned": len(list(self.encrypted_dir.iterdir())),
            "deleted": deleted_count,
            "errors": errors
        }
        self.logger.info(f"Очистка завершена: удалено {deleted_count} файлов, ошибок {len(errors)}")
        return result

    def _get_ttl_for_file(self, file_path: Path) -> int:
        for ext, ttl in self.retention_policies.items():
            if file_path.name.endswith(ext):
                return ttl
        return self.ttl_days

    def get_cleanup_stats(self) -> dict:
        """Статистика по файлам для удаления"""
        if not self.encrypted_dir.exists():
            return {"total": 0, "to_delete": 0, "files": []}
        
        now = datetime.now()
        files_to_delete = []
        
        for file_path in self.encrypted_dir.iterdir():
            if not file_path.is_file():
                continue
            
            ttl_days = self._get_ttl_for_file(file_path)
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
        
        return {
            "total": len(list(self.encrypted_dir.iterdir())),
            "to_delete": len(files_to_delete),
            "files": files_to_delete
        }