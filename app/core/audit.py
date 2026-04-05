# app/audit/audit.py
import json
import csv
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger(__name__)


class AuditLogger:
    """Централизованный аудит всех операций с файлами.

    - JSON-логи по дням (audit_YYYY-MM-DD.log)
    - CSV-лог с автоматической ротацией и архивацией
    """

    MAX_CSV_SIZE = 10 * 1024 * 1024  # 10 МБ
    LOG_DIR = Path("audit_logs")

    def __init__(self, log_dir: Optional[Path] = None):
        self.log_dir = log_dir or self.LOG_DIR
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # JSON-лог за сегодня
        self.today_log = self.log_dir / f"audit_{datetime.now():%Y-%m-%d}.log"

        # CSV-лог с ротацией
        self.csv_log = self.log_dir / "audit.csv"
        self._init_csv()

    def _init_csv(self) -> None:
        """Создаёт CSV-файл с заголовками, если его ещё нет."""
        if not self.csv_log.exists():
            with open(self.csv_log, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'action', 'filename', 'size',
                    'user', 'ip', 'hash', 'reason', 'success'
                ])
            logger.debug("Создан новый audit.csv")

    def _rotate_csv_if_needed(self) -> None:
        """Проверяет размер CSV и выполняет ротацию + архивацию при необходимости."""
        if not self.csv_log.exists():
            self._init_csv()
            return

        if self.csv_log.stat().st_size <= self.MAX_CSV_SIZE:
            return

        # Формируем имя архива по времени создания текущего файла
        ctime = datetime.fromtimestamp(self.csv_log.stat().st_ctime)
        date_str = ctime.strftime("%Y-%m-%d_%H-%M-%S")
        archive_csv = self.log_dir / f"audit_{date_str}.csv"
        archive_zip = self.log_dir / f"audit_{date_str}.zip"

        # Переименовываем
        self.csv_log.rename(archive_csv)
        logger.info(f"CSV ротирован → {archive_csv.name} ({archive_csv.stat().st_size / 1024 / 1024:.2f} МБ)")

        # Архивируем
        try:
            with zipfile.ZipFile(archive_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
                zipf.write(archive_csv, arcname=archive_csv.name)
            logger.info(f"CSV заархивирован: {archive_zip.name}")

            # Удаляем исходный CSV после успешной архивации
            archive_csv.unlink()
            logger.debug(f"Исходный CSV удалён после архивации")
        except Exception as e:
            logger.error(f"Ошибка архивации {archive_csv}: {e}")
            # Если архивация не удалась — оставляем CSV как есть

        # Создаём новый пустой CSV
        self._init_csv()

    def log_operation(
        self,
        action: str,
        filename: Optional[str] = None,
        user: str = "system",
        ip: str = "127.0.0.1",
        reason: str = "",
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Основной метод логирования операции."""
        timestamp = datetime.now().isoformat()
        metadata = metadata or {}

        # 1. JSON-лог (по дням)
        log_entry = {
            "timestamp": timestamp,
            "action": action,
            "filename": filename,
            "user": user,
            "ip": ip,
            "reason": reason,
            "success": success,
            "metadata": metadata,
        }

        try:
            with open(self.today_log, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        except Exception as e:
            logger.error(f"Не удалось записать в JSON-лог: {e}")

        # 2. CSV-лог с ротацией
        self._rotate_csv_if_needed()

        try:
            with open(self.csv_log, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    timestamp,
                    action,
                    filename,
                    metadata.get('size', 0),
                    user,
                    ip,
                    metadata.get('hash', ''),
                    reason,
                    success
                ])
        except Exception as e:
            logger.error(f"Не удалось записать в CSV-лог: {e}")

    def get_audit_log(
        self,
        date: Optional[str] = None,
        action: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Получить логи за указанную дату (или сегодня)."""
        if date:
            log_file = self.log_dir / f"audit_{date}.log"
        else:
            log_file = self.today_log

        if not log_file.exists():
            return []

        logs = []
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if action and entry.get('action') != action:
                            continue
                        logs.append(entry)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"Ошибка чтения лога {log_file}: {e}")

        return logs