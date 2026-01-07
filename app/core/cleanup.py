# app/core/cleanup.py
import asyncio
from pathlib import Path
import os
import logging
from datetime import datetime, timedelta

class FileCleanupManager:
    """Менеджер автоматической очистки файлов"""
    
    def __init__(self, encrypted_dir: Path, ttl_days: int = 30):
        self.encrypted_dir = encrypted_dir
        self.ttl_days = ttl_days
        self.logger = logging.getLogger(__name__)
        
        # Политики удаления для разных типов файлов
        self.retention_policies = {
            '.txt': 30,      # 30 дней для текстовых файлов
            '.pdf': 90,      # 90 дней для PDF
            '.dcm': 365,     # 1 год для DICOM
            '.jpg': 180,     # 180 дней для изображений
            '.age': 30       # 30 дней по умолчанию
        }
    
    async def start_cleanup_task(self):
        """Запуск задачи автоматической очистки"""
        self.logger.info(f"🚮 Запуск автоматической очистки файлов (TTL: {self.ttl_days} дней)")
        
        while True:
            try:
                await self._cleanup_old_files()
                await asyncio.sleep(3600)  # Проверка каждый час
            except Exception as e:
                self.logger.error(f"Ошибка в cleanup task: {e}")
                await asyncio.sleep(300)  # Пауза при ошибке
    
    async def _cleanup_old_files(self):
        """Очистка старых файлов"""
        if not self.encrypted_dir.exists():
            return
        
        now = datetime.now()
        deleted_count = 0
        
        for file_path in self.encrypted_dir.iterdir():
            if not file_path.is_file():
                continue
            
            # Определяем TTL для типа файла
            ttl_days = self._get_ttl_for_file(file_path)
            
            # Получаем время последнего доступа
            last_access = datetime.fromtimestamp(file_path.stat().st_atime)
            file_age = (now - last_access).days
            
            if file_age > ttl_days:
                try:
                    # Логируем перед удалением
                    file_info = {
                        "name": file_path.name,
                        "size": file_path.stat().st_size,
                        "age_days": file_age,
                        "last_access": last_access.isoformat(),
                        "ttl_days": ttl_days
                    }
                    
                    self.logger.info(f"AUTO DELETE: {file_info}")
                    
                    # Удаляем файл
                    os.remove(file_path)
                    deleted_count += 1
                    
                except Exception as e:
                    self.logger.error(f"Failed to delete {file_path.name}: {e}")
        
        if deleted_count > 0:
            self.logger.info(f"✅ Автоматически удалено {deleted_count} файлов")
    
    def _get_ttl_for_file(self, file_path: Path) -> int:
        """Получение TTL для типа файла"""
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