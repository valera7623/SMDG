# app/core/audit.py
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any
import csv

class AuditLogger:
    """Логирование всех операций с файлами"""
    
    def __init__(self, log_dir: Path = Path("audit_logs")):
        self.log_dir = log_dir
        self.log_dir.mkdir(exist_ok=True)
        
        # Форматы логов
        self.today_log = self.log_dir / f"audit_{datetime.now().strftime('%Y-%m-%d')}.log"
        self.csv_log = self.log_dir / "audit.csv"
        
        # Инициализируем CSV если нужно
        if not self.csv_log.exists():
            with open(self.csv_log, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'action', 'filename', 'size', 
                    'user', 'ip', 'hash', 'reason', 'success'
                ])
    
    def log_operation(self, action: str, filename: str, user: str = "system", 
                     ip: str = "127.0.0.1", reason: str = "", success: bool = True,
                     metadata: Dict[str, Any] = None):
        """Логирование операции"""
        timestamp = datetime.now().isoformat()
        
        # JSON лог
        log_entry = {
            "timestamp": timestamp,
            "action": action,  # upload, download, delete, view
            "filename": filename,
            "user": user,
            "ip": ip,
            "reason": reason,
            "success": success,
            "metadata": metadata or {}
        }
        
        with open(self.today_log, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        
        # CSV лог для анализа
        with open(self.csv_log, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                timestamp, action, filename, 
                metadata.get('size', 0) if metadata else 0,
                user, ip, metadata.get('hash', '') if metadata else '',
                reason, success
            ])
    
    def get_audit_log(self, date: str = None, action: str = None) -> list:
        """Получение логов по фильтрам"""
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
                    log_entry = json.loads(line.strip())
                    if action and log_entry.get('action') != action:
                        continue
                    logs.append(log_entry)
                except:
                    continue
        
        return logs