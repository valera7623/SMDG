import pytest
from unittest.mock import Mock, patch, AsyncMock
from fastapi.testclient import TestClient
from app.main import app
import uuid
from datetime import datetime, timezone, timedelta


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_file():
    """Мокает файл"""
    mock_file = Mock()
    mock_file.id = 1
    mock_file.user_id = 1
    mock_file.original_name = "test.txt"
    mock_file.encrypted_name = "encrypted_test.txt.age"
    mock_file.encrypted_path = "/path/to/encrypted_test.txt.age"
    mock_file.original_size = 1024
    mock_file.encrypted_size = 2048
    mock_file.original_hash = "abc123"
    mock_file.mime_type = "text/plain"
    mock_file.uploaded_at = datetime.now(timezone.utc)
    mock_file.expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    return mock_file


@pytest.fixture
def mock_file_link():
    """Мокает ссылку на файл"""
    mock_link = Mock()
    mock_link.token = "test_token_123"
    mock_link.file_id = 1
    mock_link.downloads_count = 0
    mock_link.max_downloads = 5  # Больше скачиваний для тестов
    mock_link.expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    return mock_link


def test_download_file_post_with_doctor_auth(client):
    """Тест POST скачивания с аутентификацией врача"""
    with patch('app.api.download.get_current_doctor') as mock_auth:
        mock_user = Mock()
        mock_user.sub = "doctor1"
        mock_user.role = "doctor"
        mock_auth.return_value = mock_user
        
        with patch('app.api.download.sanitize_filename') as mock_sanitize:
            mock_sanitize.return_value = "test.txt.age"
            
            with patch('app.api.download.ENCRYPTED_DIR') as mock_encrypted_dir:
                mock_file_path = Mock()
                mock_file_path.exists.return_value = True
                mock_file_path.is_file.return_value = True
                mock_encrypted_dir.__truediv__.return_value = mock_file_path
                
                with patch('app.api.download.uuid.uuid4') as mock_uuid:
                    mock_uuid.return_value = uuid.UUID('12345678-1234-5678-1234-567812345678')
                    
                    with patch('app.api.download.DECRYPTED_DIR') as mock_decrypted_dir:
                        mock_decrypted_path = Mock()
                        mock_decrypted_path.exists.return_value = True
                        mock_decrypted_path.stat.return_value.st_size = 512
                        mock_decrypted_dir.__truediv__.return_value = mock_decrypted_path
                        
                        with patch('app.api.download.crypto_manager') as mock_crypto:
                            mock_crypto.decrypt_file = AsyncMock()
                            
                            with patch('app.api.download.PRIVATE_KEY_PATH') as mock_key_path:
                                mock_key_path.exists.return_value = True
                                
                                with patch('app.api.download.audit_logger') as mock_logger:
                                    with patch('builtins.print') as mock_print:
                                        response = client.post("/api/download", data={
                                            "filename": "test.txt.age"
                                        })
                                        
                                        assert response.status_code == 200
                                        # Проверяем что был вызов print с информацией о пользователе
                                        mock_print.assert_any_call("Upload от пользователя: doctor1 (doctor)")
                                        
                                        # Проверяем аудит-логирование
                                        mock_logger.log_operation.assert_called_once_with(
                                            action="download",
                                            filename="test.txt.age",
                                            user="api_user",
                                            reason="Успешное скачивание и расшифровка",
                                            success=True,
                                            metadata={"original_name": "test.txt"}
                                        )


def test_download_file_post_invalid_filename(client):
    """Тест POST скачивания с недопустимым именем файла"""
    with patch('app.api.download.get_current_doctor') as mock_auth:
        mock_user = Mock()
        mock_user.sub = "doctor1"
        mock_auth.return_value = mock_user
        
        # Имя файла содержит путь
        with patch('app.api.download.sanitize_filename') as mock_sanitize:
            mock_sanitize.return_value = "../../etc/passwd.age"
            
            response = client.post("/api/download", data={
                "filename": "../../etc/passwd.age"
            })
            
            assert response.status_code == 400
            data = response.json()
            assert "detail" in data
            assert "недопустимые символы" in data["detail"].lower() or "invalid" in data["detail"].lower()


def test_download_file_post_missing_age_extension(client):
    """Тест POST скачивания файла без .age расширения"""
    with patch('app.api.download.get_current_doctor') as mock_auth:
        mock_user = Mock()
        mock_user.sub = "doctor1"
        mock_auth.return_value = mock_user
        
        with patch('app.api.download.sanitize_filename') as mock_sanitize:
            mock_sanitize.return_value = "test.txt"  # Без .age
            
            response = client.post("/api/download", data={
                "filename": "test.txt"
            })
            
            assert response.status_code == 400
            data = response.json()
            assert "detail" in data
            assert ".age" in data["detail"]


def test_download_file_post_not_found(client):
    """Тест POST скачивания несуществующего файла"""
    with patch('app.api.download.get_current_doctor') as mock_auth:
        mock_user = Mock()
        mock_user.sub = "doctor1"
        mock_auth.return_value = mock_user
        
        with patch('app.api.download.sanitize_filename') as mock_sanitize:
            mock_sanitize.return_value = "nonexistent.txt.age"
            
            with patch('app.api.download.ENCRYPTED_DIR') as mock_encrypted_dir:
                mock_file_path = Mock()
                mock_file_path.exists.return_value = False
                mock_file_path.is_file.return_value = False
                mock_encrypted_dir.__truediv__.return_value = mock_file_path
                
                response = client.post("/api/download", data={
                    "filename": "nonexistent.txt.age"
                })
                
                assert response.status_code == 404
                data = response.json()
                assert "detail" in data
                assert "не найден" in data["detail"].lower() or "not found" in data["detail"].lower()


def test_download_file_post_decryption_empty_file(client):
    """Тест когда дешифрованный файл пустой"""
    with patch('app.api.download.get_current_doctor') as mock_auth:
        mock_user = Mock()
        mock_user.sub = "doctor1"
        mock_auth.return_value = mock_user
        
        with patch('app.api.download.sanitize_filename') as mock_sanitize:
            mock_sanitize.return_value = "test.txt.age"
            
            with patch('app.api.download.ENCRYPTED_DIR') as mock_encrypted_dir:
                mock_file_path = Mock()
                mock_file_path.exists.return_value = True
                mock_file_path.is_file.return_value = True
                mock_encrypted_dir.__truediv__.return_value = mock_file_path
                
                with patch('app.api.download.uuid.uuid4'):
                    with patch('app.api.download.DECRYPTED_DIR') as mock_decrypted_dir:
                        mock_decrypted_path = Mock()
                        mock_decrypted_path.exists.return_value = True
                        mock_decrypted_path.stat.return_value.st_size = 0  # Пустой файл
                        mock_decrypted_dir.__truediv__.return_value = mock_decrypted_path
                        
                        with patch('app.api.download.crypto_manager') as mock_crypto:
                            mock_crypto.decrypt_file = AsyncMock()
                            
                            with patch('app.api.download.audit_logger') as mock_logger:
                                response = client.post("/api/download", data={
                                    "filename": "test.txt.age"
                                })
                                
                                assert response.status_code == 500
                                data = response.json()
                                assert "detail" in data
                                assert "расшифровка не удалась" in data["detail"].lower() or "failed" in data["detail"].lower()
                                
                                # Проверяем что ошибка была залогирована
                                mock_logger.log_operation.assert_called_once_with(
                                    action="download",
                                    filename="test.txt.age",
                                    user="api_user",
                                    reason=mock.ANY,
                                    success=False
                                )


def test_download_file_post_cleanup_on_error(client):
    """Тест что временный файл удаляется при ошибке"""
    with patch('app.api.download.get_current_doctor') as mock_auth:
        mock_user = Mock()
        mock_user.sub = "doctor1"
        mock_auth.return_value = mock_user
        
        with patch('app.api.download.sanitize_filename') as mock_sanitize:
            mock_sanitize.return_value = "test.txt.age"
            
            with patch('app.api.download.ENCRYPTED_DIR') as mock_encrypted_dir:
                mock_file_path = Mock()
                mock_file_path.exists.return_value = True
                mock_file_path.is_file.return_value = True
                mock_encrypted_dir.__truediv__.return_value = mock_file_path
                
                with patch('app.api.download.uuid.uuid4'):
                    with patch('app.api.download.DECRYPTED_DIR') as mock_decrypted_dir:
                        mock_decrypted_path = Mock()
                        mock_decrypted_path.exists.return_value = True
                        mock_decrypted_dir.__truediv__.return_value = mock_decrypted_path
                        
                        with patch('app.api.download.crypto_manager') as mock_crypto:
                            mock_crypto.decrypt_file = AsyncMock(side_effect=Exception("Decryption failed"))
                            
                            # Мокаем unlink для проверки что файл удаляется
                            unlink_called = False
                            def mock_unlink():
                                nonlocal unlink_called
                                unlink_called = True
                            
                            mock_decrypted_path.unlink = Mock(side_effect=mock_unlink)
                            
                            response = client.post("/api/download", data={
                                "filename": "test.txt.age"
                            })
                            
                            assert response.status_code == 500
                            # Проверяем что unlink был вызван
                            assert unlink_called is True


def test_delete_file_after_response_function():
    """Тест функции удаления файла после ответа"""
    from app.api.download import delete_file_after_response
    
    # Тест успешного удаления
    with patch('app.api.download.Path') as mock_path_class:
        mock_path = Mock()
        mock_path.exists.return_value = True
        mock_path_class.return_value = mock_path
        
        delete_file_after_response("/test/path")
        
        mock_path.unlink.assert_called_once()
    
    # Тест когда файл не существует
    with patch('app.api.download.Path') as mock_path_class:
        mock_path = Mock()
        mock_path.exists.return_value = False
        mock_path_class.return_value = mock_path
        
        delete_file_after_response("/test/path")
        
        mock_path.unlink.assert_not_called()
    
    # Тест с ошибкой при удалении
    with patch('app.api.download.Path') as mock_path_class:
        mock_path = Mock()
        mock_path.exists.return_value = True
        mock_path.unlink.side_effect = PermissionError("Permission denied")
        mock_path_class.return_value = mock_path
        
        # Не должно вызывать исключение
        delete_file_after_response("/test/path")


def test_download_by_token_link_deletion_on_max_downloads(client, mock_file, mock_file_link):
    """Тест что ссылка удаляется при достижении максимального количества скачиваний"""
    with patch('app.api.download.get_db') as mock_get_db:
        mock_db = AsyncMock()
        mock_get_db.return_value = mock_db
        
        # Настраиваем ссылку на последнее скачивание
        mock_file_link.downloads_count = 4  # Уже 4 скачивания
        mock_file_link.max_downloads = 5    # Максимум 5
        
        mock_db.execute.return_value.scalar_one_or_none.side_effect = [
            mock_file_link,  # Для поиска ссылки
            mock_file        # Для поиска файла
        ]
        
        with patch('app.api.download.Path'):
            with patch('app.api.download.DECRYPTED_DIR'):
                with patch('app.api.download.uuid.uuid4'):
                    with patch('app.api.download.crypto_manager') as mock_crypto:
                        mock_crypto.decrypt_file = AsyncMock()
                        
                        with patch('app.api.download.PRIVATE_KEY_PATH'):
                            # Мокаем удаление ссылки
                            mock_db.delete = AsyncMock()
                            
                            response = client.get("/api/download?token=test_token_123")
                            
                            # После этого скачивания должно быть 5, ссылка должна быть удалена
                            assert mock_file_link.downloads_count == 5
                            # Проверяем что delete был вызван для ссылки
                            mock_db.delete.assert_called_once_with(mock_file_link)


def test_download_by_token_link_not_deleted_before_max(client, mock_file, mock_file_link):
    """Тест что ссылка НЕ удаляется до достижения максимального количества скачиваний"""
    with patch('app.api.download.get_db') as mock_get_db:
        mock_db = AsyncMock()
        mock_get_db.return_value = mock_db
        
        # Настраиваем ссылку НЕ на последнее скачивание
        mock_file_link.downloads_count = 2  # Только 2 скачивания
        mock_file_link.max_downloads = 5    # Максимум 5
        
        mock_db.execute.return_value.scalar_one_or_none.side_effect = [
            mock_file_link,  # Для поиска ссылки
            mock_file        # Для поиска файла
        ]
        
        with patch('app.api.download.Path'):
            with patch('app.api.download.DECRYPTED_DIR'):
                with patch('app.api.download.uuid.uuid4'):
                    with patch('app.api.download.crypto_manager') as mock_crypto:
                        mock_crypto.decrypt_file = AsyncMock()
                        
                        with patch('app.api.download.PRIVATE_KEY_PATH'):
                            # Мокаем удаление ссылки
                            mock_db.delete = AsyncMock()
                            
                            response = client.get("/api/download?token=test_token_123")
                            
                            # После этого скачивания должно быть 3, ссылка НЕ должна быть удалена
                            assert mock_file_link.downloads_count == 3
                            # Проверяем что delete НЕ был вызван для ссылки
                            mock_db.delete.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__])
