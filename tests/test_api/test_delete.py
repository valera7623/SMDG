import pytest
from unittest.mock import Mock, patch, AsyncMock
from fastapi.testclient import TestClient
from app.main import app
import os


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_auth():
    """Мокает аутентификацию администратора"""
    with patch('app.api.delete.get_current_admin') as mock_auth:
        mock_user = Mock()
        mock_user.sub = "admin"
        mock_user.role = "admin"
        mock_auth.return_value = mock_user
        yield mock_auth


def test_delete_file_success_with_confirmation(client, mock_auth):
    """Тест успешного удаления файла с подтверждением"""
    with patch('app.api.delete.sanitize_filename') as mock_sanitize:
        mock_sanitize.return_value = "test.txt.age"
        
        with patch('app.api.delete.ENCRYPTED_DIR') as mock_encrypted_dir:
            mock_file_path = Mock()
            mock_file_path.exists.return_value = True
            mock_file_path.stat.return_value.st_size = 1024
            mock_encrypted_dir.__truediv__.return_value = mock_file_path
            
            with patch('app.api.delete.calculate_hash') as mock_hash:
                mock_hash.return_value = "abc123def456"
                
                with patch('os.remove') as mock_remove:
                    with patch('app.api.delete.audit_logger') as mock_logger:
                        response = client.post("/api/delete", data={
                            "filename": "test.txt.age",
                            "confirm": "true",
                            "reason": "Test deletion"
                        })
                        
                        assert response.status_code == 200
                        data = response.json()
                        
                        assert data["message"] == "✅ Файл успешно удален"
                        assert data["filename"] == "test.txt.age"
                        assert data["hash"] == "abc123def456"
                        assert data["size"] == 1024
                        assert data["audit_logged"] is True
                        
                        # Проверяем что файл был удален
                        mock_remove.assert_called_once_with(mock_file_path)
                        
                        # Проверяем аудит-логирование
                        mock_logger.log_operation.assert_called_once_with(
                            action="delete",
                            filename="test.txt.age",
                            user="admin",
                            reason="Test deletion",
                            metadata=mock.ANY,
                            success=True
                        )


def test_delete_file_requires_confirmation(client, mock_auth):
    """Тест что удаление требует подтверждения"""
    with patch('app.api.delete.sanitize_filename') as mock_sanitize:
        mock_sanitize.return_value = "test.txt.age"
        
        with patch('app.api.delete.ENCRYPTED_DIR') as mock_encrypted_dir:
            mock_file_path = Mock()
            mock_file_path.exists.return_value = True
            mock_file_path.stat.return_value.st_size = 1024
            mock_encrypted_dir.__truediv__.return_value = mock_file_path
            
            with patch('app.api.delete.calculate_hash') as mock_hash:
                mock_hash.return_value = "abc123def456"
                
                response = client.post("/api/delete", data={
                    "filename": "test.txt.age",
                    "confirm": "false",  # Без подтверждения
                    "reason": "Test"
                })
                
                assert response.status_code == 200
                data = response.json()
                
                # Должен вернуть информацию о файле с требованием подтверждения
                assert data["confirmation_required"] is True
                assert data["message"] == "⚠️ Требуется подтверждение удаления"
                assert "file_info" in data
                assert data["file_info"]["requires_confirmation"] is True
                assert data["file_info"]["name"] == "test.txt.age"
                assert data["file_info"]["size"] == 1024


def test_delete_file_not_found(client, mock_auth):
    """Тест удаления несуществующего файла"""
    with patch('app.api.delete.sanitize_filename') as mock_sanitize:
        mock_sanitize.return_value = "nonexistent.txt.age"
        
        with patch('app.api.delete.ENCRYPTED_DIR') as mock_encrypted_dir:
            mock_file_path = Mock()
            mock_file_path.exists.return_value = False
            
            # Проверяем и с .age и без
            mock_file_path_with_age = Mock()
            mock_file_path_with_age.exists.return_value = False
            
            mock_encrypted_dir.__truediv__.side_effect = [
                mock_file_path,  # Первый вызов без .age
                mock_file_path_with_age  # Второй вызов с .age
            ]
            
            response = client.post("/api/delete", data={
                "filename": "nonexistent.txt.age",
                "confirm": "true",
                "reason": "Test"
            })
            
            assert response.status_code == 404
            data = response.json()
            assert "detail" in data
            assert "not found" in data["detail"].lower() or "не найден" in data["detail"]


def test_delete_file_found_without_age_extension(client, mock_auth):
    """Тест когда файл найден без .age расширения"""
    with patch('app.api.delete.sanitize_filename') as mock_sanitize:
        mock_sanitize.return_value = "test.txt"  # Без .age
        
        with patch('app.api.delete.ENCRYPTED_DIR') as mock_encrypted_dir:
            # Первый файл не существует
            mock_file1 = Mock()
            mock_file1.exists.return_value = False
            
            # Файл с .age существует
            mock_file2 = Mock()
            mock_file2.exists.return_value = True
            mock_file2.stat.return_value.st_size = 1024
            
            mock_encrypted_dir.__truediv__.side_effect = [
                mock_file1,  # test.txt
                mock_file2   # test.txt.age
            ]
            
            with patch('app.api.delete.calculate_hash') as mock_hash:
                mock_hash.return_value = "hash123"
                
                with patch('os.remove') as mock_remove:
                    with patch('builtins.print') as mock_print:
                        response = client.post("/api/delete", data={
                            "filename": "test.txt",  # Без .age
                            "confirm": "true",
                            "reason": "Test"
                        })
                        
                        # Должен найти файл с .age расширением
                        assert response.status_code == 200
                        mock_print.assert_any_call("   ⚠️  Файл найден с .age: test.txt.age")


def test_delete_file_error_during_deletion(client, mock_auth):
    """Тест ошибки при удалении файла"""
    with patch('app.api.delete.sanitize_filename') as mock_sanitize:
        mock_sanitize.return_value = "test.txt.age"
        
        with patch('app.api.delete.ENCRYPTED_DIR') as mock_encrypted_dir:
            mock_file_path = Mock()
            mock_file_path.exists.return_value = True
            mock_file_path.stat.return_value.st_size = 1024
            mock_encrypted_dir.__truediv__.return_value = mock_file_path
            
            with patch('app.api.delete.calculate_hash') as mock_hash:
                mock_hash.return_value = "abc123"
                
                with patch('os.remove') as mock_remove:
                    mock_remove.side_effect = PermissionError("Permission denied")
                    
                    with patch('app.api.delete.audit_logger') as mock_logger:
                        with patch('builtins.print') as mock_print:
                            response = client.post("/api/delete", data={
                                "filename": "test.txt.age",
                                "confirm": "true",
                                "reason": "Test"
                            })
                            
                            assert response.status_code == 500
                            data = response.json()
                            assert "detail" in data
                            assert "failed" in data["detail"].lower()
                            
                            # Проверяем что ошибка была залогирована
                            mock_logger.log_operation.assert_called_once_with(
                                action="delete",
                                filename="test.txt.age",
                                user="admin",
                                reason="Test",
                                metadata=mock.ANY,
                                success=False
                            )


def test_delete_file_get_endpoint(client, mock_auth):
    """Тест GET endpoint для удаления"""
    with patch('app.api.delete.sanitize_filename') as mock_sanitize:
        mock_sanitize.return_value = "test.txt.age"
        
        with patch('app.api.delete.ENCRYPTED_DIR') as mock_encrypted_dir:
            mock_file_path = Mock()
            mock_file_path.exists.return_value = True
            mock_file_path.stat.return_value.st_size = 1024
            mock_encrypted_dir.__truediv__.return_value = mock_file_path
            
            with patch('app.api.delete.calculate_hash') as mock_hash:
                mock_hash.return_value = "abc123"
                
                with patch('os.remove') as mock_remove:
                    # GET запрос с параметрами в query string
                    response = client.get("/api/delete?filename=test.txt.age&confirm=true&reason=Test")
                    
                    # GET endpoint должен вызывать ту же функцию
                    assert response.status_code == 200
                    mock_remove.assert_called_once()


def test_delete_file_different_confirm_values(client, mock_auth):
    """Тест разных значений confirm"""
    test_cases = [
        ("true", True),
        ("True", True),
        ("TRUE", True),
        ("yes", True),
        ("Yes", True),
        ("YES", True),
        ("1", True),
        ("on", True),
        ("On", True),
        ("confirmed", True),
        ("false", False),
        ("no", False),
        ("0", False),
        ("off", False),
    ]
    
    for confirm_value, should_delete in test_cases:
        with patch('app.api.delete.sanitize_filename') as mock_sanitize:
            mock_sanitize.return_value = "test.txt.age"
            
            with patch('app.api.delete.ENCRYPTED_DIR') as mock_encrypted_dir:
                mock_file_path = Mock()
                mock_file_path.exists.return_value = True
                mock_file_path.stat.return_value.st_size = 1024
                mock_encrypted_dir.__truediv__.return_value = mock_file_path
                
                with patch('app.api.delete.calculate_hash') as mock_hash:
                    mock_hash.return_value = "abc123"
                    
                    with patch('os.remove') as mock_remove:
                        response = client.post("/api/delete", data={
                            "filename": "test.txt.age",
                            "confirm": confirm_value,
                            "reason": "Test"
                        })
                        
                        if should_delete:
                            assert response.status_code == 200
                            data = response.json()
                            assert "✅ Файл успешно удален" in data["message"]
                            mock_remove.assert_called_once()
                        else:
                            assert response.status_code == 200
                            data = response.json()
                            assert "Требуется подтверждение" in data["message"]
                            mock_remove.assert_not_called()
                        
                        # Сбрасываем моки для следующего теста
                        mock_remove.reset_mock()


def test_delete_file_audit_metadata(client, mock_auth):
    """Тест что правильные метаданные передаются в аудит"""
    with patch('app.api.delete.sanitize_filename') as mock_sanitize:
        mock_sanitize.return_value = "test.txt.age"
        
        with patch('app.api.delete.ENCRYPTED_DIR') as mock_encrypted_dir:
            mock_file_path = Mock()
            mock_file_path.exists.return_value = True
            mock_file_path.stat.return_value.st_size = 2048
            mock_encrypted_dir.__truediv__.return_value = mock_file_path
            
            with patch('app.api.delete.calculate_hash') as mock_hash:
                mock_hash.return_value = "test_hash_12345"
                
                with patch('os.remove'):
                    with patch('app.api.delete.audit_logger') as mock_logger:
                        response = client.post("/api/delete", data={
                            "filename": "test.txt.age",
                            "confirm": "true",
                            "reason": "Expired file"
                        })
                        
                        assert response.status_code == 200
                        
                        # Проверяем метаданные в аудит-логе
                        call_args = mock_logger.log_operation.call_args
                        metadata = call_args[1]['metadata']
                        
                        assert metadata["filename"] == "test.txt.age"
                        assert metadata["size"] == 2048
                        assert metadata["hash"] == "test_hash_12345"
                        assert "path" in metadata


if __name__ == "__main__":
    pytest.main([__file__])
