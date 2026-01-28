# tests/test_api_delete.py
import pytest
from unittest.mock import patch, MagicMock, mock_open
from fastapi.testclient import TestClient
from fastapi import HTTPException
import os
from pathlib import Path
import tempfile
import shutil

# Импортируем приложение
from app.main import app

client = TestClient(app)


class TestDeleteAPI:
    """Тесты для API удаления файлов"""

    @pytest.fixture
    def temp_encrypted_dir(self):
        """Создает временную директорию для зашифрованных файлов"""
        temp_dir = tempfile.mkdtemp()
        original_encrypted_dir = None
        
        with patch('app.api.delete.ENCRYPTED_DIR', Path(temp_dir)):
            yield Path(temp_dir)
        
        # Очистка после тестов
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

    @pytest.fixture
    def mock_auth(self):
        """Мокает аутентификацию администратора"""
        with patch('app.api.delete.get_current_admin') as mock_auth:
            mock_auth.return_value = "admin"
            yield mock_auth

    @pytest.fixture
    def mock_audit_logger(self):
        """Мокает аудит-логгер"""
        with patch('app.api.delete.audit_logger') as mock_logger:
            mock_logger.log_operation = MagicMock()
            yield mock_logger

    def test_delete_file_success(self, temp_encrypted_dir, mock_auth, mock_audit_logger):
        """Тест успешного удаления файла с подтверждением"""
        # Создаем тестовый файл
        test_file = temp_encrypted_dir / "testfile.age"
        test_content = b"encrypted test content"
        test_file.write_bytes(test_content)
        
        # Мокаем calculate_hash
        with patch('app.api.delete.calculate_hash') as mock_hash:
            mock_hash.return_value = "a1b2c3d4e5f6" * 8
            
            # Выполняем запрос на удаление с подтверждением
            response = client.post(
                "/api/delete",
                data={
                    "filename": "testfile",
                    "confirm": "true",
                    "reason": "Тестовое удаление"
                }
            )
        
        # Проверяем ответ
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "✅ Файл успешно удален"
        assert data["filename"] == "testfile.age"
        assert data["hash"] == "a1b2c3d4e5f6" * 8
        assert data["size"] == len(test_content)
        assert data["audit_logged"] is True
        
        # Проверяем, что файл удален
        assert not test_file.exists()
        
        # Проверяем аудит-логирование
        mock_audit_logger.log_operation.assert_called_once_with(
            action="delete",
            filename="testfile.age",
            user="admin",
            reason="Тестовое удаление",
            metadata={
                "filename": "testfile.age",
                "size": len(test_content),
                "hash": "a1b2c3d4e5f6" * 8,
                "path": str(test_file)
            },
            success=True
        )

    def test_delete_file_with_full_filename(self, temp_encrypted_dir, mock_auth, mock_audit_logger):
        """Тест удаления файла с указанием полного имени (с .age)"""
        # Создаем тестовый файл
        test_file = temp_encrypted_dir / "document.age"
        test_content = b"encrypted document content"
        test_file.write_bytes(test_content)
        
        with patch('app.api.delete.calculate_hash') as mock_hash:
            mock_hash.return_value = "hash1234567890"
            
            response = client.post(
                "/api/delete",
                data={
                    "filename": "document.age",  # Указываем с расширением
                    "confirm": "true",
                    "reason": ""
                }
            )
        
        assert response.status_code == 200
        assert not test_file.exists()
        mock_audit_logger.log_operation.assert_called_once()

    def test_delete_file_confirmation_required(self, temp_encrypted_dir, mock_auth, mock_audit_logger):
        """Тест что требуется подтверждение для удаления"""
        # Создаем тестовый файл
        test_file = temp_encrypted_dir / "needconfirm.age"
        test_file.write_bytes(b"content")
        
        with patch('app.api.delete.calculate_hash') as mock_hash:
            mock_hash.return_value = "somehash"
            
            # Выполняем запрос БЕЗ подтверждения
            response = client.post(
                "/api/delete",
                data={
                    "filename": "needconfirm",
                    "confirm": "false",  # Нет подтверждения
                    "reason": ""
                }
            )
        
        # Проверяем ответ с требованием подтверждения
        assert response.status_code == 200
        data = response.json()
        assert data["confirmation_required"] is True
        assert "Требуется подтверждение удаления" in data["message"]
        assert data["file_info"]["requires_confirmation"] is True
        
        # Файл не должен быть удален
        assert test_file.exists()
        
        # Аудит не должен логироваться
        mock_audit_logger.log_operation.assert_not_called()

    def test_delete_file_not_found(self, temp_encrypted_dir, mock_auth, mock_audit_logger):
        """Тест удаления несуществующего файла"""
        response = client.post(
            "/api/delete",
            data={
                "filename": "nonexistent.file",
                "confirm": "true",
                "reason": ""
            }
        )
        
        assert response.status_code == 404
        assert "File not found" in response.json()["detail"]
        mock_audit_logger.log_operation.assert_not_called()

    def test_delete_file_without_age_extension(self, temp_encrypted_dir, mock_auth, mock_audit_logger):
        """Тест удаления файла когда указываем имя без .age, но файл с .age существует"""
        # Создаем файл с расширением .age
        test_file = temp_encrypted_dir / "data.age"
        test_content = b"encrypted data"
        test_file.write_bytes(test_content)
        
        # Создаем файл БЕЗ расширения .age (не должен быть найден)
        other_file = temp_encrypted_dir / "data"
        other_file.write_bytes(b"other content")
        
        with patch('app.api.delete.calculate_hash') as mock_hash:
            mock_hash.return_value = "testhash123"
            
            # Запрашиваем удаление файла без указания .age
            response = client.post(
                "/api/delete",
                data={
                    "filename": "data",  # Без .age
                    "confirm": "true",
                    "reason": ""
                }
            )
        
        # Должен найти и удалить файл с .age
        assert response.status_code == 200
        assert not test_file.exists()  # Файл с .age удален
        assert other_file.exists()  # Файл без .age остался
        
        data = response.json()
        assert data["filename"] == "data.age"  # В ответе должно быть полное имя

    def test_delete_file_various_confirm_values(self, temp_encrypted_dir, mock_auth):
        """Тест различных значений подтверждения"""
        test_cases = [
            ("true", True, "should delete"),
            ("yes", True, "should delete"),
            ("1", True, "should delete"),
            ("on", True, "should delete"),
            ("confirmed", True, "should delete"),
            ("false", False, "should require confirmation"),
            ("no", False, "should require confirmation"),
            ("0", False, "should require confirmation"),
            ("off", False, "should require confirmation"),
            ("", False, "should require confirmation"),
        ]
        
        for confirm_value, should_delete, description in test_cases:
            # Создаем новый файл для каждого теста
            test_file = temp_encrypted_dir / f"test_{confirm_value}.age"
            test_file.write_bytes(b"content")
            
            with patch('app.api.delete.calculate_hash') as mock_hash:
                mock_hash.return_value = "hash"
                
                response = client.post(
                    "/api/delete",
                    data={
                        "filename": f"test_{confirm_value}",
                        "confirm": confirm_value,
                        "reason": ""
                    }
                )
            
            if should_delete:
                assert response.status_code == 200, f"Failed for {confirm_value}: {description}"
                assert not test_file.exists(), f"File should be deleted for {confirm_value}"
            else:
                assert response.status_code == 200, f"Failed for {confirm_value}: {description}"
                assert test_file.exists(), f"File should not be deleted for {confirm_value}"
                assert response.json()["confirmation_required"] is True

    def test_delete_file_get_endpoint(self, temp_encrypted_dir, mock_auth, mock_audit_logger):
        """Тест GET эндпоинта для удаления"""
        # Создаем тестовый файл
        test_file = temp_encrypted_dir / "gettest.age"
        test_file.write_bytes(b"get test content")
        
        with patch('app.api.delete.calculate_hash') as mock_hash:
            mock_hash.return_value = "gethash123"
            
            # Используем GET запрос
            response = client.get(
                "/api/delete",
                params={
                    "filename": "gettest",
                    "x-api-key": "dummy-key",  # Будет проигнорировано из-за мока
                    "confirm": "true",
                    "reason": "GET тест"
                }
            )
        
        assert response.status_code == 200
        assert not test_file.exists()
        mock_audit_logger.log_operation.assert_called_once()

    def test_delete_file_unauthorized(self, temp_encrypted_dir):
        """Тест удаления без авторизации"""
        # Мокаем аутентификацию чтобы она провалилась
        with patch('app.api.delete.get_current_admin') as mock_auth:
            mock_auth.side_effect = HTTPException(status_code=401, detail="Unauthorized")
            
            response = client.post(
                "/api/delete",
                data={
                    "filename": "sometest",
                    "confirm": "true",
                    "reason": ""
                }
            )
        
        assert response.status_code == 401

    def test_delete_file_error_during_deletion(self, temp_encrypted_dir, mock_auth, mock_audit_logger):
        """Тест ошибки при удалении файла"""
        # Создаем тестовый файл
        test_file = temp_encrypted_dir / "errortest.age"
        test_file.write_bytes(b"content")
        
        with patch('app.api.delete.calculate_hash') as mock_hash:
            mock_hash.return_value = "errorhash"
            
            # Мокаем os.remove чтобы выбросить исключение
            with patch('app.api.delete.os.remove') as mock_remove:
                mock_remove.side_effect = PermissionError("Permission denied")
                
                response = client.post(
                    "/api/delete",
                    data={
                        "filename": "errortest",
                        "confirm": "true",
                        "reason": "should fail"
                    }
                )
        
        # Должна быть ошибка 500
        assert response.status_code == 500
        assert "Delete failed" in response.json()["detail"]
        
        # Файл должен остаться
        assert test_file.exists()
        
        # Должно быть залогировано неудачное удаление
        mock_audit_logger.log_operation.assert_called_once_with(
            action="delete",
            filename="errortest.age",
            user="admin",
            reason="should fail",
            metadata={
                "filename": "errortest.age",
                "size": len(b"content"),
                "hash": "errorhash",
                "path": str(test_file)
            },
            success=False
        )

    def test_delete_file_sanitization(self, temp_encrypted_dir, mock_auth, mock_audit_logger):
        """Тест санитизации имени файла"""
        # Создаем тестовый файл с безопасным именем
        test_file = temp_encrypted_dir / "safe_name.age"
        test_file.write_bytes(b"content")
        
        # Пытаемся удалить с небезопасным именем
        with patch('app.api.delete.calculate_hash') as mock_hash:
            mock_hash.return_value = "sanitizedhash"
            
            response = client.post(
                "/api/delete",
                data={
                    "filename": "../../etc/passwd",  # Попытка path traversal
                    "confirm": "true",
                    "reason": ""
                }
            )
        
        # Должен вернуть 404, так как файл не найден после санитизации
        assert response.status_code == 404
        
        # Проверяем, что sanitize_filename был вызван (косвенно)
        assert not (temp_encrypted_dir / "etc" / "passwd").exists()

    def test_delete_file_empty_reason(self, temp_encrypted_dir, mock_auth, mock_audit_logger):
        """Тест удаления с пустой причиной"""
        test_file = temp_encrypted_dir / "noreason.age"
        test_file.write_bytes(b"content")
        
        with patch('app.api.delete.calculate_hash') as mock_hash:
            mock_hash.return_value = "emptyreasonhash"
            
            response = client.post(
                "/api/delete",
                data={
                    "filename": "noreason",
                    "confirm": "true",
                    "reason": ""  # Пустая причина
                }
            )
        
        assert response.status_code == 200
        
        # Проверяем, что использовалась причина по умолчанию
        mock_audit_logger.log_operation.assert_called_once()
        call_args = mock_audit_logger.log_operation.call_args
        assert "Ручное удаление администратором" in call_args[1]["reason"]

    @patch('app.api.delete.print')  # Мокаем print для чистоты вывода
    def test_delete_file_debug_output(self, mock_print, temp_encrypted_dir, mock_auth):
        """Тест что функция выводит отладочную информацию"""
        test_file = temp_encrypted_dir / "debug.age"
        test_file.write_bytes(b"debug content")
        
        with patch('app.api.delete.calculate_hash') as mock_hash:
            mock_hash.return_value = "debughash"
            
            client.post(
                "/api/delete",
                data={
                    "filename": "debug",
                    "confirm": "true",
                    "reason": "debug test"
                }
            )
        
        # Проверяем что print был вызван несколько раз
        assert mock_print.call_count >= 5
        
        # Проверяем содержание некоторых вызовов
        print_calls = [call[0][0] for call in mock_print.call_args_list]
        
        # Должны быть сообщения о начале удаления
        assert any("🗑️  Запрос на удаление файла" in str(call) for call in print_calls)
        assert any("Безопасное имя:" in str(call) for call in print_calls)
        assert any("Путь к файлу:" in str(call) for call in print_calls)


# Дополнительные тесты для утилит
def test_sanitize_filename_integration():
    """Интеграционный тест санитизации имени файла"""
    from app.core.utils import sanitize_filename
    
    test_cases = [
        ("normal.txt", "normal.txt"),
        ("../etc/passwd", "etcpasswd"),
        ("file with spaces.txt", "filewithspaces.txt"),
        ("UPPERCASE.AGE", "UPPERCASE.AGE"),
        ("", ""),
        ("a" * 300, "a" * 255),  # Ограничение длины
    ]
    
    for input_name, expected in test_cases:
        result = sanitize_filename(input_name)
        assert result == expected, f"Failed for {input_name}: got {result}, expected {expected}"


def test_calculate_hash_integration():
    """Интеграционный тест вычисления хеша"""
    from app.core.utils import calculate_hash
    import tempfile
    from pathlib import Path
    
    # Создаем тестовый файл
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        test_content = b"Hello, World!" * 100
        tmp.write(test_content)
        tmp_path = Path(tmp.name)
    
    try:
        # Вычисляем хеш
        file_hash = calculate_hash(tmp_path)
        
        # Проверяем что хеш вычислен корректно (SHA256, 64 hex символа)
        assert len(file_hash) == 64
        assert all(c in "0123456789abcdef" for c in file_hash)
        
        # Проверяем что хеш одинаковый при повторном вычислении
        assert file_hash == calculate_hash(tmp_path)
    finally:
        # Очистка
        if tmp_path.exists():
            tmp_path.unlink()