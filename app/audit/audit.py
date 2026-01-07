# app/audit/audit.py
import json
import csv
from datetime import datetime
from pathlib import Path
from typing import Dict, Any
import os

class AuditLogger:
    """Логирование операций с ротацией по размеру (макс 10MB на файл)"""
    
    MAX_LOG_SIZE = 10 * 1024 * 1024  # 10 MB
    LOG_DIR = Path("audit_logs")
    
    def __init__(self, log_dir: Path = None):
        self.log_dir = log_dir or self.LOG_DIR
        self.log_dir.mkdir(exist_ok=True)
        
        self.csv_log = self.log_dir / "audit.csv"
        self._init_csv()
    
    def _init_csv(self):
        """Инициализация CSV-файла с заголовками"""
        if not self.csv_log.exists():
            with open(self.csv_log, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'action', 'filename', 'size', 
                    'user', 'ip', 'hash', 'reason', 'success'
                ])
    
    def _get_current_log_file(self) -> Path:
        """Определяет текущий JSON-лог файл с учётом ротации"""
        base_name = f"audit_{datetime.now():%Y-%m-%d}"
        log_file = self.log_dir / f"{base_name}.log"
        
        # Если файл существует и больше 10MB — создаём новый с суффиксом
        if log_file.exists() and log_file.stat().st_size >= self.MAX_LOG_SIZE:
            i = 1
            while True:
                rotated = self.log_dir / f"{base_name}_{i}.log"
                if not rotated.exists() or rotated.stat().st_size < self.MAX_LOG_SIZE:
                    return rotated
                i += 1
        return log_file
    
    def log_operation(self, action: str, filename: str = "", user: str = "system", 
                     ip: str = "127.0.0.1", reason: str = "", success: bool = True,
                     metadata: Dict[str, Any] = None):
        """Логирование операции в JSON и CSV"""
        timestamp = datetime.now().isoformat()
        
        log_entry = {
            "timestamp": timestamp,
            "action": action,
            "filename": filename,
            "user": user,
            "ip": ip,
            "reason": reason,
            "success": success,
            "metadata": metadata or {}
        }
        
        # Запись в JSON-лог с ротацией
        current_log = self._get_current_log_file()
        with open(current_log, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        
        # Запись в общий CSV
        size = metadata.get('size', 0) if metadata else 0
        file_hash = metadata.get('hash', '') if metadata else ''
        with open(self.csv_log, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                timestamp, action, filename, size,
                user, ip, file_hash, reason, success
            ])
    
    def get_audit_log(self, date: str = None, action: str = None) -> list:
        """Получение логов (поддерживает только основной файл дня)"""
        if date:
            pattern = f"audit_{date}*.log"
        else:
            pattern = f"audit_{datetime.now():%Y-%m-%d}*.log"
        
        logs = []
        for log_file in sorted(self.log_dir.glob(pattern)):
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        entry = json.loads(line)
                        if action and entry.get('action') != action:
                            continue
                        logs.append(entry)
            except Exception as e:
                print(f"Ошибка чтения лога {log_file}: {e}")
        
        return logs