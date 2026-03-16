# app/audit/audit.py
import json
import csv
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

class AuditLogger:
    """Логирование всех операций с файлами + ротация CSV по размеру"""

    MAX_CSV_SIZE = 10 * 1024 * 1024  # 10 МБ
    LOG_DIR = Path("audit_logs")

    def __init__(self, log_dir: Path = None):
        self.log_dir = log_dir or self.LOG_DIR
        self.log_dir.mkdir(exist_ok=True)

        # JSON-лог по дням
        self.today_log = self.log_dir / f"audit_{datetime.now():%Y-%m-%d}.log"

        # CSV-лог с ротацией
        self.csv_log = self.log_dir / "audit.csv"
        self._init_csv()

    def _init_csv(self):
        """Создаёт CSV с заголовками, если файла нет"""
        if not self.csv_log.exists():
            with open(self.csv_log, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'action', 'filename', 'size',
                    'user', 'ip', 'hash', 'reason', 'success'
                ])

    def _rotate_csv_if_needed(self):
        """Ротация CSV, если размер превысил лимит"""
        if not self.csv_log.exists():
            self._init_csv()
            return

        current_size = self.csv_log.stat().st_size
        if current_size <= self.MAX_CSV_SIZE:
            return

        # Формируем имя архива по дате создания текущего файла
        ctime = datetime.fromtimestamp(self.csv_log.stat().st_ctime)
        date_str = ctime.strftime("%Y-%m-%d_%H-%M-%S")
        archive_path = self.log_dir / f"audit_{date_str}.csv"

        # Переименовываем
        self.csv_log.rename(archive_path)
        print(f"[AUDIT] CSV ротирован: {self.csv_log.name} → {archive_path.name} "
              f"(было {current_size / 1024 / 1024:.2f} МБ)")

        # Логируем ротацию в JSON
        self._log_rotation(archive_path.name, current_size)

        # Создаём новый пустой audit.csv
        self._init_csv()

    def _log_rotation(self, archived_name: str, size_bytes: int):
        """Логируем факт ротации в JSON"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "action": "log_rotation",
            "filename": archived_name,
            "size": size_bytes,
            "user": "system",
            "ip": "system",
            "reason": "CSV size exceeded 10MB",
            "success": True,
            "metadata": {"rotated_from": "audit.csv"}
        }
        with open(self.today_log, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    def log_operation(self,
                      action: str,
                      filename: str = None,
                      user: str = "system",
                      ip: str = "127.0.0.1",
                      reason: str = "",
                      success: bool = True,
                      metadata: Dict[str, Any] = None):
        """
        Логирует операцию в JSON (по дням) и CSV (с ротацией)
        """
        timestamp = datetime.now().isoformat()
        metadata = metadata or {}

        # JSON лог
        log_entry = {
            "timestamp": timestamp,
            "action": action,
            "filename": filename,
            "user": user,
            "ip": ip,
            "reason": reason,
            "success": success,
            "metadata": metadata
        }

        with open(self.today_log, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')

        # CSV с ротацией
        self._rotate_csv_if_needed()

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

    def get_audit_log(self, date: str = None, action: str = None) -> list:
        """Получение JSON-логов по фильтрам (дата и/или действие)"""
        if date:
            log_file = self.log_dir / f"audit_{date}.log"
        else:
            log_file = self.today_log

        if not log_file.exists():
            return []

        logs = []
        with open(log_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if action and entry.get('action') != action:
                        continue
                    logs.append(entry)
                except json.JSONDecodeError:
                    continue

        return logs