"""
Тесты для app/api/upload.py - финальная исправленная версия
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from fastapi.testclient import TestClient
import io
import uuid

from app.main import app


# ============================================================================
# ГЛОБАЛЬНОЕ ОТКЛЮЧЕНИЕ RATE LIMITING
# ============================================================================

# Импортируем router и временно убираем декоратор limiter
from app.api.upload import router as upload_router

# Сохраняем оригинальную функцию
original_upload_function = upload_router.routes[0].endpoint

# Создаем копию функции без декоратора limiter
from app.api.upload import upload_file as original_upload

# Создаем новую функцию без декоратора limiter
async def upload_file_no_limits(*args, **kwargs):
    return await original_upload(*args, **kwargs)

# Заменяем endpoint в router
upload_router.routes[0].endpoint = upload_file_no_limits


# ============================================================================
# ФИКСТУРЫ
# ============================================================================

@pytest.fixture
def client():
    """Тестовый клиент FastAPI"""
    return TestClient(app)


@pytest.fixture
def mock_auth_user():
    """Мок аутентифицированного пользователя"""
    mock_user = Mock()
    mock_user.sub = "test_user"
    mock_user.role = "user"
    return mock_user


@pytest.fixture
def mock_db_session():
    """Мок сессии базы данных"""
    mock_session = AsyncMock()
    
    # Мок для выполнения запросов
    mock_execute_result = Mock()
    mock_execute_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_execute_result
    
    # Мок для коммита и refresh
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()
    
    return mock_session


@pytest.fixture
def client_with_auth(mock_auth_user, mock_db_session):
    """Клиент с замоканной аутентификацией и БД"""
    from app.api.upload import get_current_user
    from app.core.database import get_db
    
    # Переопределяем зависимости
    app.dependency_overrides[get_current_user] = lambda: mock_auth_user
    app.dependency_overrides[get_db] = lambda: mock_db_session
    
    client = TestClient(app)
    yield client
    
    # Очищаем переопределения
    app.dependency_overrides.clear()


# ============================================================================
# ОСНОВНЫЕ ТЕСТЫ (ИСПРАВЛЕННЫЕ)
# ============================================================================

def test_upload_basic_success(client_with_auth, mock_db_session):
    """Базовый тест успешной загрузки файла - ИСПРАВЛЕННЫЙ"""
    # Настраиваем мок для пользователя в БД
    mock_user = Mock()
    mock_user.id = 1
    mock_db_session.execute.return_value.scalar_one_or_none.return_value = mock_user
    
    # Настраиваем моки для всех зависимостей
    with patch('app.api.upload.magic.Magic') as mock_magic:
        mock_magic.return_value.from_buffer.return_value = "application/pdf"
        
        with patch('app.api.upload.clamd.ClamdNetworkSocket') as mock_clamd:
            mock_clamd_instance = Mock()
            mock_clamd_instance.ping.return_value = "PONG"
            mock_clamd_instance.instream.return_value = {'stream': ['OK']}
            mock_clamd.return_value = mock_clamd_instance
            
            with patch('app.api.upload.crypto_manager') as mock_crypto:
                mock_crypto.encrypt_file = AsyncMock(return_value="encrypted_hash")
                
                with patch('app.api.upload.get_public_key', return_value="test_public_key"):
                    with patch('app.api.upload.calculate_hash', return_value="file_hash"):
                        with patch('app.api.upload.uuid.uuid4') as mock_uuid:
                            # Возвращаем реальный UUID для пути файла
                            test_uuid = uuid.UUID('12345678-1234-5678-1234-567812345678')
                            mock_uuid.return_value = test_uuid
                            
                            # Мокаем файловые операции
                            mock_file = Mock()
                            mock_file.write = Mock()
                            mock_file.__enter__ = Mock(return_value=mock_file)
                            mock_file.__exit__ = Mock(return_value=None)
                            
                            with patch('builtins.open', return_value=mock_file):
                                # Мокаем пути
                                with patch('app.api.upload.UPLOAD_DIR') as mock_upload_dir:
                                    mock_temp_path = Mock()
                                    mock_temp_path.exists.return_value = False
                                    mock_upload_dir.__truediv__.return_value = mock_temp_path
                                    
                                with patch('app.api.upload.ENCRYPTED_DIR') as mock_encrypted_dir:
                                    mock_encrypted_path = Mock()
                                    mock_encrypted_path.stat.return_value.st_size = 1234
                                    mock_encrypted_dir.__truediv__.return_value = mock_encrypted_path
                                    
                                    # Тестовый файл
                                    file_content = b"%PDF-1.4\ntest"
                                    files = {
                                        'file': ('test.pdf', io.BytesIO(file_content), 'application/pdf')
                                    }
                                    
                                    response = client_with_auth.post("/api/upload", files=files, data={
                                        'ttl_days': '30',
                                        'max_downloads': '1'
                                    })
                                    
                                    assert response.status_code == 200
                                    data = response.json()
                                    assert "message" in data
                                    assert "download_url" in data


def test_upload_virus_detected_fixed(client_with_auth, mock_db_session):
    """Тест обнаружения вируса - ИСПРАВЛЕННЫЙ"""
    mock_user = Mock()
    mock_user.id = 1
    mock_db_session.execute.return_value.scalar_one_or_none.return_value = mock_user
    
    with patch('app.api.upload.magic.Magic') as mock_magic:
        mock_magic.return_value.from_buffer.return_value = "application/pdf"
        
        with patch('app.api.upload.clamd.ClamdNetworkSocket') as mock_clamd:
            mock_clamd_instance = Mock()
            mock_clamd_instance.ping.return_value = "PONG"
            mock_clamd_instance.instream.return_value = {'stream': ['FOUND', 'Test.Virus']}
            mock_clamd.return_value = mock_clamd_instance
            
            # Мокаем файловые операции
            mock_file = Mock()
            mock_file.write = Mock()
            mock_file.__enter__ = Mock(return_value=mock_file)
            mock_file.__exit__ = Mock(return_value=None)
            
            with patch('builtins.open', return_value=mock_file):
                file_content = b"%PDF-1.4\ntest"
                files = {
                    'file': ('infected.pdf', io.BytesIO(file_content), 'application/pdf')
                }
                
                response = client_with_auth.post("/api/upload", files=files)
                
                assert response.status_code == 400
                # Исправленная проверка для русского текста
                detail = response.json()["detail"].lower()
                assert "вредоносный" in detail or "вирус" in detail or "malicious" in detail


def test_upload_clamav_error_in_dev_mode_fixed(client_with_auth, mock_db_session):
    """Тест ошибки ClamAV в dev mode - ИСПРАВЛЕННЫЙ"""
    mock_user = Mock()
    mock_user.id = 1
    mock_db_session.execute.return_value.scalar_one_or_none.return_value = mock_user
    
    with patch('app.api.upload.magic.Magic') as mock_magic:
        mock_magic.return_value.from_buffer.return_value = "application/pdf"
        
        with patch('app.api.upload.clamd.ClamdNetworkSocket') as mock_clamd:
            mock_clamd.side_effect = Exception("ClamAV error")
            
            # Мокаем settings правильно
            with patch('app.api.upload.settings') as mock_settings:
                # Создаем объект с нужными атрибутами
                mock_settings.dev_mode = True
                mock_settings.ALLOWED_MIME_TYPES = ["application/pdf"]  # Реальный список, не Mock
                mock_settings.MAX_UPLOAD_SIZE_MB = 50
                mock_settings.CLAMAV_HOST = "clamav"
                mock_settings.CLAMAV_PORT = 3310
                mock_settings.CLAMAV_TIMEOUT = 60
                mock_settings.DICOM_MAGIC = b'DICM'
                
                with patch('app.api.upload.crypto_manager') as mock_crypto:
                    mock_crypto.encrypt_file = AsyncMock(return_value="encrypted_hash")
                    
                    with patch('app.api.upload.get_public_key', return_value="test_public_key"):
                        with patch('app.api.upload.calculate_hash', return_value="file_hash"):
                            with patch('app.api.upload.uuid.uuid4'):
                                # Мокаем файловые операции
                                mock_file = Mock()
                                mock_file.write = Mock()
                                mock_file.__enter__ = Mock(return_value=mock_file)
                                mock_file.__exit__ = Mock(return_value=None)
                                
                                with patch('builtins.open', return_value=mock_file):
                                    # Мокаем пути
                                    with patch('app.api.upload.UPLOAD_DIR'):
                                        with patch('app.api.upload.ENCRYPTED_DIR'):
                                            file_content = b"%PDF-1.4\ntest"
                                            files = {
                                                'file': ('test.pdf', io.BytesIO(file_content), 'application/pdf')
                                            }
                                            
                                            response = client_with_auth.post("/api/upload", files=files)
                                            
                                            # В dev mode должен разрешить
                                            assert response.status_code == 200


def test_upload_clamav_error_in_prod_mode_fixed(client_with_auth, mock_db_session):
    """Тест ошибки ClamAV в prod mode - ИСПРАВЛЕННЫЙ"""
    with patch('app.api.upload.magic.Magic') as mock_magic:
        mock_magic.return_value.from_buffer.return_value = "application/pdf"
        
        with patch('app.api.upload.clamd.ClamdNetworkSocket') as mock_clamd:
            mock_clamd.side_effect = Exception("ClamAV error")
            
            # Мокаем settings правильно
            with patch('app.api.upload.settings') as mock_settings:
                mock_settings.dev_mode = False
                mock_settings.ALLOWED_MIME_TYPES = ["application/pdf"]  # Реальный список
                mock_settings.MAX_UPLOAD_SIZE_MB = 50
                mock_settings.CLAMAV_HOST = "clamav"
                mock_settings.CLAMAV_PORT = 3310
                mock_settings.CLAMAV_TIMEOUT = 60
                mock_settings.DICOM_MAGIC = b'DICM'
                
                # Мокаем файловые операции
                mock_file = Mock()
                mock_file.write = Mock()
                mock_file.__enter__ = Mock(return_value=mock_file)
                mock_file.__exit__ = Mock(return_value=None)
                
                with patch('builtins.open', return_value=mock_file):
                    file_content = b"%PDF-1.4\ntest"
                    files = {
                        'file': ('test.pdf', io.BytesIO(file_content), 'application/pdf')
                    }
                    
                    response = client_with_auth.post("/api/upload", files=files)
                    
                    # В prod mode должен запретить
                    assert response.status_code == 503


def test_upload_dicom_file_fixed(client_with_auth, mock_db_session):
    """Тест загрузки DICOM файла - ИСПРАВЛЕННЫЙ"""
    mock_user = Mock()
    mock_user.id = 1
    mock_db_session.execute.return_value.scalar_one_or_none.return_value = mock_user
    
    # Создаем DICOM контент
    dicom_content = bytearray(200)
    dicom_content[128:132] = b'DICM'  # DICOM magic bytes
    
    with patch('app.api.upload.magic.Magic') as mock_magic:
        # DICOM часто определяется как octet-stream
        mock_magic.return_value.from_buffer.return_value = "application/octet-stream"
        
        with patch('app.api.upload.clamd.ClamdNetworkSocket') as mock_clamd:
            mock_clamd_instance = Mock()
            mock_clamd_instance.ping.return_value = "PONG"
            mock_clamd_instance.instream.return_value = {'stream': ['OK']}
            mock_clamd.return_value = mock_clamd_instance
            
            with patch('app.api.upload.crypto_manager') as mock_crypto:
                mock_crypto.encrypt_file = AsyncMock(return_value="encrypted_hash")
                
                with patch('app.api.upload.get_public_key', return_value="test_public_key"):
                    with patch('app.api.upload.calculate_hash', return_value="file_hash"):
                        with patch('app.api.upload.uuid.uuid4') as mock_uuid:
                            # Возвращаем конкретный UUID
                            test_uuid = uuid.UUID('87654321-4321-8765-4321-876543218765')
                            mock_uuid.return_value = test_uuid
                            
                            # Мокаем файловые операции
                            mock_file = Mock()
                            mock_file.write = Mock()
                            mock_file.__enter__ = Mock(return_value=mock_file)
                            mock_file.__exit__ = Mock(return_value=None)
                            
                            with patch('builtins.open', return_value=mock_file):
                                # Мокаем settings для DICOM проверки
                                with patch('app.api.upload.settings') as mock_settings:
                                    mock_settings.DICOM_MAGIC = b'DICM'
                                    
                                    # Мокаем пути
                                    with patch('app.api.upload.UPLOAD_DIR'):
                                        with patch('app.api.upload.ENCRYPTED_DIR'):
                                            files = {
                                                'file': ('scan.dcm', io.BytesIO(bytes(dicom_content)), 'application/octet-stream')
                                            }
                                            
                                            response = client_with_auth.post("/api/upload", files=files)
                                            
                                            # Должен определить как DICOM и разрешить
                                            assert response.status_code == 200


# ============================================================================
# ДОПОЛНИТЕЛЬНЫЕ ТЕСТЫ ДЛЯ ПОКРЫТИЯ ОСТАВШИХСЯ СТРОК
# ============================================================================

def test_upload_file_user_not_found_in_db(client_with_auth, mock_db_session):
    """Тест когда пользователь не найден в БД"""
    # Возвращаем None при поиске пользователя
    mock_db_session.execute.return_value.scalar_one_or_none.return_value = None
    
    with patch('app.api.upload.magic.Magic') as mock_magic:
        mock_magic.return_value.from_buffer.return_value = "application/pdf"
        
        with patch('app.api.upload.clamd.ClamdNetworkSocket') as mock_clamd:
            mock_clamd_instance = Mock()
            mock_clamd_instance.ping.return_value = "PONG"
            mock_clamd_instance.instream.return_value = {'stream': ['OK']}
            mock_clamd.return_value = mock_clamd_instance
            
            with patch('app.api.upload.crypto_manager') as mock_crypto:
                mock_crypto.encrypt_file = AsyncMock(return_value="encrypted_hash")
                
                with patch('app.api.upload.get_public_key', return_value="test_public_key"):
                    with patch('app.api.upload.calculate_hash', return_value="file_hash"):
                        with patch('app.api.upload.uuid.uuid4'):
                            # Мокаем файловые операции
                            mock_file = Mock()
                            mock_file.write = Mock()
                            mock_file.__enter__ = Mock(return_value=mock_file)
                            mock_file.__exit__ = Mock(return_value=None)
                            
                            with patch('builtins.open', return_value=mock_file):
                                with patch('app.api.upload.settings') as mock_settings:
                                    mock_settings.dev_mode = False
                                    mock_settings.ALLOWED_MIME_TYPES = ["application/pdf"]
                                    mock_settings.MAX_UPLOAD_SIZE_MB = 50
                                    mock_settings.CLAMAV_HOST = "clamav"
                                    mock_settings.CLAMAV_PORT = 3310
                                    mock_settings.CLAMAV_TIMEOUT = 60
                                    mock_settings.DICOM_MAGIC = b'DICM'
                                    
                                    # Мокаем пути
                                    with patch('app.api.upload.UPLOAD_DIR'):
                                        with patch('app.api.upload.ENCRYPTED_DIR'):
                                            file_content = b"%PDF-1.4\ntest"
                                            files = {
                                                'file': ('test.pdf', io.BytesIO(file_content), 'application/pdf')
                                            }
                                            
                                            response = client_with_auth.post("/api/upload", files=files)
                                            
                                            # Должен успешно завершиться даже без user_id
                                            assert response.status_code == 200


def test_upload_file_db_error(client_with_auth, mock_db_session):
    """Тест ошибки базы данных"""
    mock_user = Mock()
    mock_user.id = 1
    mock_db_session.execute.return_value.scalar_one_or_none.return_value = mock_user
    
    # Симулируем ошибку при коммите
    mock_db_session.commit.side_effect = Exception("Database error")
    
    with patch('app.api.upload.magic.Magic') as mock_magic:
        mock_magic.return_value.from_buffer.return_value = "application/pdf"
        
        with patch('app.api.upload.clamd.ClamdNetworkSocket') as mock_clamd:
            mock_clamd_instance = Mock()
            mock_clamd_instance.ping.return_value = "PONG"
            mock_clamd_instance.instream.return_value = {'stream': ['OK']}
            mock_clamd.return_value = mock_clamd_instance
            
            with patch('app.api.upload.crypto_manager') as mock_crypto:
                mock_crypto.encrypt_file = AsyncMock(return_value="encrypted_hash")
                
                with patch('app.api.upload.get_public_key', return_value="test_public_key"):
                    with patch('app.api.upload.calculate_hash', return_value="file_hash"):
                        with patch('app.api.upload.uuid.uuid4'):
                            # Мокаем файловые операции
                            mock_file = Mock()
                            mock_file.write = Mock()
                            mock_file.__enter__ = Mock(return_value=mock_file)
                            mock_file.__exit__ = Mock(return_value=None)
                            
                            with patch('builtins.open', return_value=mock_file):
                                with patch('app.api.upload.settings') as mock_settings:
                                    mock_settings.dev_mode = False
                                    mock_settings.ALLOWED_MIME_TYPES = ["application/pdf"]
                                    mock_settings.MAX_UPLOAD_SIZE_MB = 50
                                    mock_settings.CLAMAV_HOST = "clamav"
                                    mock_settings.CLAMAV_PORT = 3310
                                    mock_settings.CLAMAV_TIMEOUT = 60
                                    mock_settings.DICOM_MAGIC = b'DICM'
                                    
                                    # Мокаем пути
                                    with patch('app.api.upload.UPLOAD_DIR'):
                                        with patch('app.api.upload.ENCRYPTED_DIR'):
                                            file_content = b"%PDF-1.4\ntest"
                                            files = {
                                                'file': ('test.pdf', io.BytesIO(file_content), 'application/pdf')
                                            }
                                            
                                            response = client_with_auth.post("/api/upload", files=files)
                                            
                                            # Должна быть ошибка БД
                                            assert response.status_code == 500
                                            assert "upload failed" in response.json()["detail"].lower() or "ошибка" in response.json()["detail"].lower()


# ============================================================================
# ВОССТАНОВЛЕНИЕ ОРИГИНАЛЬНОЙ ФУНКЦИИ
# ============================================================================

def teardown_module(module):
    """Восстанавливаем оригинальную функцию после тестов"""
    upload_router.routes[0].endpoint = original_upload_function


if __name__ == "__main__":
    pytest.main([__file__, "-v"])