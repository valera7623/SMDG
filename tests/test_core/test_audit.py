import pytest
import json
import csv
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch, mock_open
from app.core.audit import AuditLogger


@pytest.fixture
def temp_dir(tmp_path):
    """Создает временную директорию для тестов"""
    return tmp_path


@pytest.fixture
def audit_logger(temp_dir):
    """Создает AuditLogger для тестов"""
    return AuditLogger(log_dir=temp_dir)


def test_audit_logger_initialization(audit_logger, temp_dir):
    """Тест инициализации AuditLogger"""
    assert audit_logger.log_dir == temp_dir
    assert temp_dir.exists()
    
    # Проверяем что файлы созданы
    today = datetime.now().strftime('%Y-%m-%d')
    expected_log_file = temp_dir / f"audit_{today}.log"
    expected_csv_file = temp_dir / "audit.csv"
    
    # Файлы должны существовать после инициализации
    assert expected_csv_file.exists()
    
    # Проверяем заголовок CSV
    with open(expected_csv_file, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        headers = next(reader)
        expected_headers = [
            'timestamp', 'action', 'filename', 'size', 
            'user', 'ip', 'hash', 'reason', 'success'
        ]
        assert headers == expected_headers


def test_log_operation_basic(audit_logger, temp_dir):
    """Тест базового логирования операции"""
    # Мокаем запись в файлы
    mock_log_data = []
    mock_csv_data = []
    
    def mock_write_log(data):
        mock_log_data.append(data)
    
    def mock_write_csv(row):
        mock_csv_data.append(row)
    
    with patch('builtins.open', mock_open()) as mock_file:
        # Заменяем write чтобы сохранить данные
        mock_file.return_value.write.side_effect = mock_write_log
        mock_file.return_value.__enter__.return_value = mock_file.return_value
        
        # Логируем операцию
        audit_logger.log_operation(
            action="upload",
            filename="test.txt",
            user="testuser",
            ip="192.168.1.1",
            reason="Test upload",
            success=True,
            metadata={"size": 1024, "hash": "abc123"}
        )
    
    # Проверяем что файлы были открыты для записи
    assert mock_file.call_count >= 2


def test_log_operation_with_defaults(audit_logger):
    """Тест логирования с значениями по умолчанию"""
    with patch('builtins.open', mock_open()) as mock_file:
        audit_logger.log_operation(
            action="download",
            filename="file.pdf"
        )
        
        # Должны быть вызовы для обоих файлов
        assert mock_file.call_count >= 2


def test_log_operation_without_metadata(audit_logger):
    """Тест логирования без метаданных"""
    with patch('builtins.open', mock_open()) as mock_file:
        audit_logger.log_operation(
            action="delete",
            filename="old.txt",
            user="admin",
            reason="File expired",
            success=True
        )
        
        assert mock_file.call_count >= 2


def test_log_operation_failure(audit_logger):
    """Тест логирования неудачной операции"""
    with patch('builtins.open', mock_open()) as mock_file:
        audit_logger.log_operation(
            action="upload",
            filename="malware.exe",
            user="attacker",
            reason="Virus detected",
            success=False,
            metadata={"virus": "Eicar-Test-Signature"}
        )
        
        assert mock_file.call_count >= 2


def test_get_audit_log_no_date(audit_logger, temp_dir):
    """Тест получения логов без указания даты"""
    # Создаем тестовый лог-файл
    today = datetime.now().strftime('%Y-%m-%d')
    log_file = temp_dir / f"audit_{today}.log"
    
    test_entries = [
        {"timestamp": "2024-01-01T10:00:00", "action": "upload", "filename": "file1.txt"},
        {"timestamp": "2024-01-01T11:00:00", "action": "download", "filename": "file1.txt"},
    ]
    
    with open(log_file, 'w', encoding='utf-8') as f:
        for entry in test_entries:
            f.write(json.dumps(entry) + '\n')
    
    # Получаем логи
    logs = audit_logger.get_audit_log()
    
    assert len(logs) == 2
    assert logs[0]["action"] == "upload"
    assert logs[1]["action"] == "download"


def test_get_audit_log_with_date(audit_logger, temp_dir):
    """Тест получения логов с указанием даты"""
    # Создаем лог-файл для конкретной даты
    specific_date = "2024-01-01"
    log_file = temp_dir / f"audit_{specific_date}.log"
    
    test_entry = {"timestamp": "2024-01-01T10:00:00", "action": "upload", "filename": "test.txt"}
    
    with open(log_file, 'w', encoding='utf-8') as f:
        f.write(json.dumps(test_entry) + '\n')
    
    # Получаем логи для этой даты
    logs = audit_logger.get_audit_log(date=specific_date)
    
    assert len(logs) == 1
    assert logs[0]["action"] == "upload"
    assert logs[0]["filename"] == "test.txt"


def test_get_audit_log_with_action_filter(audit_logger, temp_dir):
    """Тест получения логов с фильтром по действию"""
    # Создаем тестовый лог-файл
    today = datetime.now().strftime('%Y-%m-%d')
    log_file = temp_dir / f"audit_{today}.log"
    
    test_entries = [
        {"timestamp": "2024-01-01T10:00:00", "action": "upload", "filename": "file1.txt"},
        {"timestamp": "2024-01-01T11:00:00", "action": "download", "filename": "file1.txt"},
        {"timestamp": "2024-01-01T12:00:00", "action": "upload", "filename": "file2.txt"},
    ]
    
    with open(log_file, 'w', encoding='utf-8') as f:
        for entry in test_entries:
            f.write(json.dumps(entry) + '\n')
    
    # Получаем только upload логи
    logs = audit_logger.get_audit_log(action="upload")
    
    assert len(logs) == 2
    assert all(log["action"] == "upload" for log in logs)


def test_get_audit_log_file_not_exists(audit_logger):
    """Тест получения логов когда файл не существует"""
    logs = audit_logger.get_audit_log(date="1900-01-01")
    assert logs == []


def test_get_audit_log_invalid_json(audit_logger, temp_dir):
    """Тест получения логов с невалидным JSON"""
    today = datetime.now().strftime('%Y-%m-%d')
    log_file = temp_dir / f"audit_{today}.log"
    
    # Пишем невалидный JSON
    with open(log_file, 'w', encoding='utf-8') as f:
        f.write("{invalid json}\n")
        f.write('{"valid": "json"}\n')
        f.write("not json at all\n")
    
    # Получаем логи - должен проигнорировать невалидные строки
    logs = audit_logger.get_audit_log()
    
    assert len(logs) == 1
    assert logs[0]["valid"] == "json"


def test_log_operation_creates_directories():
    """Тест что логгер создает директории при необходимости"""
    non_existent_dir = Path("/tmp/nonexistent/audit/test")
    
    # Директория не должна существовать
    if non_existent_dir.exists():
        non_existent_dir.rmdir()
    
    # Создаем логгер - должен создать директорию
    logger = AuditLogger(log_dir=non_existent_dir)
    
    assert non_existent_dir.exists()
    
    # Очищаем
    non_existent_dir.rmdir()


def test_log_operation_csv_format(audit_logger, temp_dir):
    """Тест формата CSV записи"""
    csv_file = temp_dir / "audit.csv"
    
    # Логируем операцию
    audit_logger.log_operation(
        action="test",
        filename="test.txt",
        user="user1",
        ip="127.0.0.1",
        reason="test reason",
        success=True,
        metadata={"size": 1234, "hash": "testhash"}
    )
    
    # Читаем CSV
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        headers = next(reader)  # Пропускаем заголовок
        row = next(reader)
        
        # Проверяем структуру
        assert len(row) == 9
        assert row[1] == "test"  # action
        assert row[2] == "test.txt"  # filename
        assert row[3] == "1234"  # size
        assert row[4] == "user1"  # user
        assert row[5] == "127.0.0.1"  # ip
        assert row[6] == "testhash"  # hash
        assert row[7] == "test reason"  # reason
        assert row[8] == "True"  # success


if __name__ == "__main__":
    pytest.main([__file__])
