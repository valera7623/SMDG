# tests/test_api/test_download.py
import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock, call, mock_open
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException, FastAPI, BackgroundTasks
from fastapi.testclient import TestClient
from pathlib import Path
import tempfile
import shutil
import uuid
import os
from starlette.requests import Request
from app.api.download import delete_file_after_response, download_by_token
from app.core import audit_logger, file_storage 
from app.crypto.crypto import crypto_manager
from app.core.auth import get_current_admin, get_current_doctor

# Создаем тестовое приложение
app = FastAPI()

# Импортируем роутер с моками для предотвращения циклических импортов
# Нужно замокать лимитер перед импортом
mock_limiter = MagicMock()
mock_limiter.limit = lambda x: lambda f: f  # Декоратор который ничего не делает

with patch('app.api.download.limiter', mock_limiter):
    with patch('app.api.download.ENCRYPTED_DIR', Path("/tmp/encrypted")):
        with patch('app.api.download.DECRYPTED_DIR', Path("/tmp/decrypted")):
            with patch('app.api.download.PRIVATE_KEY_PATH', Path("/tmp/private.key")):
                with patch('app.api.download.audit_logger', MagicMock()):
                    from app.api.download import router as download_router

app.include_router(download_router, prefix="/api")
client = TestClient(app)


class TestDownloadAPI:
    """Тесты для API скачивания файлов"""

    @pytest.fixture
    def temp_dirs(self):
        """Создает временные директории для тестов"""
        encrypted_dir = Path(tempfile.mkdtemp())
        decrypted_dir = Path(tempfile.mkdtemp())
        
        with patch('app.api.download.ENCRYPTED_DIR', encrypted_dir):
            with patch('app.api.download.DECRYPTED_DIR', decrypted_dir):
                yield encrypted_dir, decrypted_dir
        
        # Очистка
        shutil.rmtree(encrypted_dir, ignore_errors=True)
        shutil.rmtree(decrypted_dir, ignore_errors=True)

    @pytest.fixture
    def mock_crypto_manager(self):
        """Мокает crypto_manager"""
        with patch('app.api.download.crypto_manager') as mock_crypto:
            mock_crypto.decrypt_file = AsyncMock()
            yield mock_crypto

    @pytest.fixture
    def mock_db_session(self):
        """Мокает асинхронную сессию БД"""
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.delete = AsyncMock()
        mock_session.commit = AsyncMock()
        return mock_session

    @pytest.fixture
    def mock_get_db(self, mock_db_session):
        """Мокает зависимость get_db"""
        async def mock_get_db_func():
            return mock_db_session
        
        # Важно: нужно замокать до импорта функций
        with patch('app.api.download.get_db'):
            # Возвращаем корутину
            yield mock_get_db_func

    @pytest.fixture
    def mock_auth_doctor(self):
        """Мокает аутентификацию врача"""
        mock_token_data = MagicMock()
        mock_token_data.sub = "doctor_user"
        mock_token_data.role = "doctor"
        
        async def mock_get_current_doctor():
            return mock_token_data
        
        with patch('app.api.download.get_current_doctor', mock_get_current_doctor):
            yield

    @pytest.fixture
    def mock_audit_logger(self):
        """Мокает аудит-логгер"""
        with patch('app.api.download.audit_logger') as mock_logger:
            mock_logger.log_operation = MagicMock()
            yield mock_logger

    @pytest.fixture
    def mock_background_tasks(self):
        """Мокает BackgroundTasks"""
        mock_tasks = MagicMock(spec=BackgroundTasks)
        mock_tasks.add_task = MagicMock()
        return mock_tasks

    @pytest.fixture
    def mock_request(self):
        """Создает мок Request объекта для SlowAPI"""
        mock_req = MagicMock(spec=Request)
        mock_req.scope = {"type": "http"}
        mock_req.client = MagicMock()
        mock_req.client.host = "127.0.0.1"
        return mock_req

    # ====== Тесты для download_by_token (GET с токеном) ======

    @pytest.mark.asyncio
    async def test_download_by_token_success(self, mock_db_session, mock_crypto_manager, temp_dirs, mock_audit_logger, mock_request):
        """Тест успешного скачивания по токену"""
        encrypted_dir, decrypted_dir = temp_dirs
        
        # Создаем тестовые данные
        test_token = "test-token-123"
        test_file_id = 1
        test_original_name = "test_document.pdf"
        test_encrypted_name = "test_document.pdf.age"
        
        # Мокаем FileLink
        mock_link = MagicMock()
        mock_link.token = test_token
        mock_link.file_id = test_file_id
        mock_link.max_downloads = 5
        mock_link.downloads_count = 2
        mock_link.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        
        # Мокаем File
        mock_file = MagicMock()
        mock_file.id = test_file_id
        mock_file.original_name = test_original_name
        mock_file.encrypted_path = str(encrypted_dir / test_encrypted_name)
        
        # Создаем тестовый зашифрованный файл
        encrypted_file = encrypted_dir / test_encrypted_name
        encrypted_file.write_bytes(b"encrypted content")
        
        # Настраиваем моки БД
        mock_result_link = MagicMock()
        mock_result_link.scalar_one_or_none.return_value = mock_link
        mock_result_file = MagicMock()
        mock_result_file.scalar_one_or_none.return_value = mock_file
        mock_db_session.execute.side_effect = [mock_result_link, mock_result_file]
        
        # Настраиваем мок crypto_manager
        mock_crypto_manager.decrypt_file.return_value = None
        
        # Вызываем функцию напрямую (но нужно импортировать с правильным моком лимитера)
        # Временно убираем декоратор лимитера
        with patch('app.api.download.limiter.limit', lambda x: lambda f: f):
            from app.api.download import download_by_token
            
            mock_background_tasks = MagicMock()
            mock_background_tasks.add_task = MagicMock()
            
            response = await download_by_token(
                request=mock_request,
                background_tasks=mock_background_tasks,
                token=test_token,
                db=mock_db_session
            )
        
        # Проверяем вызовы
        mock_crypto_manager.decrypt_file.assert_called_once()
        mock_db_session.commit.assert_called_once()
        
        # Проверяем что счетчик загрузок увеличился
        assert mock_link.downloads_count == 3
        
        # Проверяем что задача на удаление добавлена
        mock_background_tasks.add_task.assert_called_once()
        
        # Проверяем что возвращается FileResponse
        assert hasattr(response, 'filename')
        assert response.filename == test_original_name

    @pytest.mark.asyncio
    async def test_download_by_token_link_not_found(self, mock_db_session, mock_request):
        """Тест скачивания с несуществующим токеном"""
        # Настраиваем мок БД для возврата None (ссылка не найдена)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result
        
        # Временно убираем декоратор лимитера
        with patch('app.api.download.limiter.limit', lambda x: lambda f: f):
            from app.api.download import download_by_token
            
            with pytest.raises(HTTPException) as exc_info:
                await download_by_token(
                    request=mock_request,
                    background_tasks=MagicMock(),
                    token="invalid-token",
                    db=mock_db_session
                )
        
        assert exc_info.value.status_code == 404
        assert "Ссылка не найдена" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_download_by_token_expired(self, mock_db_session, mock_request):
        """Тест скачивания с истекшим токеном"""
        # Создаем просроченную ссылку
        mock_link = MagicMock()
        mock_link.token = "expired-token"
        mock_link.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_link
        mock_db_session.execute.return_value = mock_result
        
        # Временно убираем декоратор лимитера
        with patch('app.api.download.limiter.limit', lambda x: lambda f: f):
            from app.api.download import download_by_token
            
            with pytest.raises(HTTPException) as exc_info:
                await download_by_token(
                    request=mock_request,
                    background_tasks=MagicMock(),
                    token="expired-token",
                    db=mock_db_session
                )
        
        assert exc_info.value.status_code == 410
        assert "Ссылка истекла" in str(exc_info.value.detail)
        mock_db_session.delete.assert_called_once_with(mock_link)
        mock_db_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_download_by_token_limit_exceeded(self, mock_db_session, mock_request):
        """Тест скачивания с исчерпанным лимитом"""
        # Создаем ссылку с исчерпанным лимитом
        mock_link = MagicMock()
        mock_link.token = "limit-exceeded-token"
        mock_link.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        mock_link.max_downloads = 3
        mock_link.downloads_count = 3  # Достигнут лимит
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_link
        mock_db_session.execute.return_value = mock_result
        
        # Временно убираем декоратор лимитера
        with patch('app.api.download.limiter.limit', lambda x: lambda f: f):
            from app.api.download import download_by_token
            
            with pytest.raises(HTTPException) as exc_info:
                await download_by_token(
                    request=mock_request,
                    background_tasks=MagicMock(),
                    token="limit-exceeded-token",
                    db=mock_db_session
                )
        
        assert exc_info.value.status_code == 410
        assert "Лимит скачиваний исчерпан" in str(exc_info.value.detail)
        mock_db_session.delete.assert_called_once_with(mock_link)
        mock_db_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_download_by_token_file_not_found(self, mock_db_session, mock_request):
        """Тест когда файл не найден в БД"""
        # Создаем валидную ссылку
        mock_link = MagicMock()
        mock_link.token = "valid-token"
        mock_link.file_id = 999  # Несуществующий ID
        mock_link.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        mock_link.max_downloads = 5
        mock_link.downloads_count = 0
        
        # Первый запрос находит ссылку, второй - не находит файл
        mock_result_link = MagicMock()
        mock_result_link.scalar_one_or_none.return_value = mock_link
        mock_result_file = MagicMock()
        mock_result_file.scalar_one_or_none.return_value = None
        
        mock_db_session.execute.side_effect = [mock_result_link, mock_result_file]
        
        # Временно убираем декоратор лимитера
        with patch('app.api.download.limiter.limit', lambda x: lambda f: f):
            from app.api.download import download_by_token
            
            with pytest.raises(HTTPException) as exc_info:
                await download_by_token(
                    request=mock_request,
                    background_tasks=MagicMock(),
                    token="valid-token",
                    db=mock_db_session
                )
        
        assert exc_info.value.status_code == 404
        assert "Файл не найден" in str(exc_info.value.detail)

    # ====== Тесты для download_file_post (POST с авторизацией) ======

    @pytest.mark.asyncio
    async def test_download_file_post_success(
        self,
        mock_auth_doctor,
        mock_crypto_manager,
        temp_dirs,
        mock_audit_logger,
        mock_background_tasks,
        mock_request,
    ):
        """Тест успешного скачивания через POST"""
        encrypted_dir, decrypted_dir = temp_dirs

        test_filename = "medical_report.pdf.age"
    
        # Создаём реальный зашифрованный файл
        encrypted_file = encrypted_dir / test_filename
        encrypted_file.write_bytes(b"encrypted medical data")

        # mock_crypto_manager.decrypt_file не пишет файл на диск —
        # создаём расшифрованный файл вручную ДО вызова, используя side_effect
        original_name = "medical_report.pdf"

        async def fake_decrypt(encrypted_path, private_key_path, output_path):
            """Симулируем расшифровку: создаём выходной файл"""
            Path(output_path).write_bytes(b"decrypted medical data")

        mock_crypto_manager.decrypt_file.side_effect = fake_decrypt

        with patch("app.api.download.limiter.limit", lambda x: lambda f: f):
            from app.api.download import download_file_post

            response = await download_file_post(
                request=mock_request,
                background_tasks=mock_background_tasks,
                filename=test_filename,
                current_user=MagicMock(sub="doctor_user", role="doctor"),
            )

        # Проверяем вызов decrypt
        mock_crypto_manager.decrypt_file.assert_called_once()

        # Проверяем аудит-логирование
        mock_audit_logger.log_operation.assert_called_once_with(
            action="download",
            filename=test_filename,
            user="api_user",
            reason="Успешное скачивание и расшифровка",
            success=True,
            metadata={"original_name": original_name},
        )

        # Проверяем что задача на удаление добавлена
        mock_background_tasks.add_task.assert_called_once()

        # Проверяем ответ
        assert hasattr(response, "filename")
        assert response.filename == original_name


    @pytest.mark.asyncio
    async def test_download_file_post_missing_extension(self, mock_auth_doctor, mock_request):
        """Тест скачивания файла без .age расширения"""
        # Временно убираем декоратор лимитера
        with patch('app.api.download.limiter.limit', lambda x: lambda f: f):
            from app.api.download import download_file_post
            
            with pytest.raises(HTTPException) as exc_info:
                await download_file_post(
                    request=mock_request,
                    background_tasks=MagicMock(),
                    filename="medical_report.pdf",  # Без .age
                    current_user=MagicMock(sub="doctor_user", role="doctor")
                )
        
        assert exc_info.value.status_code == 400
        assert "должно заканчиваться на .age" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_download_file_post_invalid_filename(self, mock_auth_doctor, mock_request):
        """Тест скачивания с небезопасным именем файла"""
        # Временно убираем декоратор лимитера
        with patch('app.api.download.limiter.limit', lambda x: lambda f: f):
            from app.api.download import download_file_post
            
            # Мокаем sanitize_filename чтобы она возвращала то же имя (для теста)
            with patch('app.api.download.sanitize_filename', return_value="passwd.age"):
                with pytest.raises(HTTPException) as exc_info:
                    await download_file_post(
                        request=mock_request,
                        background_tasks=MagicMock(),
                        filename="../../../etc/passwd.age",  # Path traversal попытка
                        current_user=MagicMock(sub="doctor_user", role="doctor")
                    )
        
        # После санитизации имя будет "passwd.age", что пройдет проверку имени
        # Но файла не будет существовать, поэтому будет 404
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_download_file_post_file_not_found(self, mock_auth_doctor, temp_dirs, mock_request):
        """Тест скачивания несуществующего файла"""
        encrypted_dir, _ = temp_dirs
        
        # Временно убираем декоратор лимитера
        with patch('app.api.download.limiter.limit', lambda x: lambda f: f):
            from app.api.download import download_file_post
            
            with pytest.raises(HTTPException) as exc_info:
                await download_file_post(
                    request=mock_request,
                    background_tasks=MagicMock(),
                    filename="nonexistent.pdf.age",
                    current_user=MagicMock(sub="doctor_user", role="doctor")
                )
        
        assert exc_info.value.status_code == 404
        assert "Файл не найден" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_download_file_post_decryption_error(self, mock_auth_doctor, mock_crypto_manager, temp_dirs, mock_audit_logger, mock_request):
        """Тест ошибки расшифровки файла"""
        encrypted_dir, decrypted_dir = temp_dirs
        
        # Создаем тестовый файл
        test_filename = "test.pdf.age"
        encrypted_file = encrypted_dir / test_filename
        encrypted_file.write_bytes(b"encrypted data")
        
        # Временно убираем декоратор лимитера
        with patch('app.api.download.limiter.limit', lambda x: lambda f: f):
            from app.api.download import download_file_post
            
            # Мокаем ошибку расшифровки
            mock_crypto_manager.decrypt_file.side_effect = Exception("Decryption failed: invalid key")
            
            with pytest.raises(HTTPException) as exc_info:
                await download_file_post(
                    request=mock_request,
                    background_tasks=MagicMock(),
                    filename=test_filename,
                    current_user=MagicMock(sub="doctor_user", role="doctor")
                )
        
        assert exc_info.value.status_code == 500
        assert "Ошибка скачивания" in str(exc_info.value.detail)
        
        # Проверяем что ошибка залогирована
        mock_audit_logger.log_operation.assert_called_once_with(
            action="download",
            filename=test_filename,
            user="api_user",
            reason="Decryption failed: invalid key",
            success=False
        )

    # ====== Тесты для delete_file_after_response ======

    def test_delete_file_after_response_success(self):
        """Тест успешного удаления временного файла"""
        # Создаем временный файл
        import tempfile
        from pathlib import Path
        from app.api.download import delete_file_after_response
        
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(b"test content")
        
        # Мокаем print
        with patch('app.api.download.print') as mock_print:
            delete_file_after_response(tmp_path)
        
        # Проверяем что файл удален
        assert not tmp_path.exists()

    def test_delete_file_after_response_not_exists(self):
        """Тест удаления несуществующего файла"""
        from app.api.download import delete_file_after_response
        from unittest.mock import MagicMock
        
        non_existent = MagicMock(spec=Path)
        non_existent.exists.return_value = False
        
        # Мокаем print
        with patch('app.api.download.print') as mock_print:
            # Должно завершиться без ошибок
            delete_file_after_response(non_existent)
        
        # Проверяем что exists был вызван
        non_existent.exists.assert_called_once()
        # unlink не должен быть вызван
        non_existent.unlink.assert_not_called()

    def test_delete_file_after_response_permission_error(self):
        """Тест ошибки удаления файла (например, нет прав)"""
        from app.api.download import delete_file_after_response
        from unittest.mock import MagicMock
        
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True
        mock_path.unlink.side_effect = PermissionError("Permission denied")
        
        with patch('app.api.download.print') as mock_print:
            # Должно перехватить исключение и напечатать сообщение
            delete_file_after_response(mock_path)
        
        # Проверяем что сообщение об ошибке было напечатано
        error_printed = any("Ошибка удаления" in str(call) or "Permission denied" in str(call) 
                           for call in mock_print.call_args_list)
        assert error_printed, "Error message should be printed"

    # ====== Интеграционные тесты с TestClient ======

    def test_download_post_integration_unauthorized(self):
        """Интеграционный тест POST /api/download без авторизации"""
        # Без мока аутентификации должна быть ошибка 401/403
        response = client.post(
            "/api/download",
            data={"filename": "test.pdf.age"}
        )
        
        # Должна быть ошибка авторизации (401 или 403)
        assert response.status_code in [401, 403, 422]

    # ====== Тесты для _download_file (внутренняя функция) ======

    @pytest.mark.asyncio
    async def test_download_file_internal_success(
        self, mock_crypto_manager, temp_dirs, mock_audit_logger, mock_background_tasks
    ):
        """Тест внутренней функции _download_file"""
        encrypted_dir, decrypted_dir = temp_dirs

        test_filename = "test.pdf.age"
        encrypted_file = encrypted_dir / test_filename
        encrypted_file.write_bytes(b"encrypted content")

        # side_effect создаёт реальный расшифрованный файл
        async def fake_decrypt(encrypted_path, private_key_path, output_path):
            Path(output_path).write_bytes(b"decrypted content")

        mock_crypto_manager.decrypt_file.side_effect = fake_decrypt

        from app.api.download import _download_file

        response = await _download_file(
            filename=test_filename,
            background_tasks=mock_background_tasks,
        )

        assert response.filename == "test.pdf"



# Упрощенные тесты которые точно работают
class TestDownloadSimple:
    """Упрощенные тесты которые не требуют сложных моков"""
    
    def test_delete_file_after_response_basic(self):
        """Базовый тест удаления файла"""
        from app.api.download import delete_file_after_response
        
        # Создаем временный файл
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as f:
            filepath = Path(f.name)
            f.write(b"test")
        
        # Замокаем print чтобы не засорять вывод
        with patch('app.api.download.print'):
            # Удаляем файл
            delete_file_after_response(filepath)
        
        # Проверяем что файл удален
        assert not filepath.exists()
    
    def test_sanitize_filename_integration(self):
        """Интеграционный тест sanitize_filename"""
        from app.core.utils import sanitize_filename
        
        # Тест что функция работает
        result = sanitize_filename("test.pdf.age")
        assert result == "test.pdf.age"
        
        # Тест транслитерации
        result = sanitize_filename("документ.pdf.age")
        assert "pdf.age" in result
    
    @pytest.mark.asyncio
    async def test_download_by_token_simple_mocks(self):
        """Упрощенный тест с минимальными моками"""
        # Мокаем все что нужно
        with patch('app.api.download.limiter.limit', lambda x: lambda f: f):
            with patch('app.api.download.get_db'):
                with patch('app.api.download.crypto_manager') as mock_crypto:
                    with patch('app.api.download.ENCRYPTED_DIR', Path("/tmp")):
                        with patch('app.api.download.DECRYPTED_DIR', Path("/tmp")):
                            with patch('app.api.download.PRIVATE_KEY_PATH', Path("/tmp/key")):
                                
                                mock_crypto.decrypt_file = AsyncMock()
                                
                                # Импортируем после всех моков
                                from app.api.download import download_by_token
                                
                                # Создаем мок сессии БД
                                mock_session = AsyncMock()
                                mock_result = MagicMock()
                                mock_result.scalar_one_or_none.return_value = None  # Ссылка не найдена
                                mock_session.execute.return_value = mock_result
                                
                                # Создаем мок Request
                                mock_request = MagicMock(spec=Request)
                                mock_request.scope = {"type": "http"}
                                mock_request.client = MagicMock(host="127.0.0.1")
                                
                                # Должно выбросить 404
                                with pytest.raises(HTTPException) as exc_info:
                                    await download_by_token(
                                        request=mock_request,
                                        background_tasks=MagicMock(),
                                        token="invalid",
                                        db=mock_session
                                    )
                                
                                assert exc_info.value.status_code == 404
                                
# tests/test_api/test_download.py
"""
Тесты для роутера /api/download
"""




@pytest.fixture
def mock_user():
    user = MagicMock()
    user.sub = "test_doctor"
    user.role = "doctor"
    return user


@pytest.fixture
def mock_admin():
    user = MagicMock()
    user.sub = "test_admin"
    user.role = "admin"
    return user


@pytest.fixture
def client_with_doctor(client, mock_user):
    app.dependency_overrides[get_current_doctor] = lambda: mock_user
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def client_with_admin(client, mock_admin):
    app.dependency_overrides[get_current_admin] = lambda: mock_admin
    yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_download_by_token_success(mock_user, mock_db_session, temp_dirs):
    """GET /download?token=... — успех"""
    token = str(uuid.uuid4())
    file_id = 1
    original_name = "test.pdf"

    mock_link = MagicMock()
    mock_link.token = token
    mock_link.file_id = file_id
    mock_link.max_downloads = 5
    mock_link.downloads_count = 2
    mock_link.expires_at = datetime.now(timezone.utc) + timedelta(days=10)

    mock_file = MagicMock()
    mock_file.id = file_id
    mock_file.original_name = original_name
    mock_file.encrypted_path = str(temp_dirs["encrypted"] / "enc_test.age")

    decrypted_path = temp_dirs["decrypted"] / f"{uuid.uuid4()}_{original_name}"

    # Очищаем decrypted перед тестом
    for item in temp_dirs["decrypted"].iterdir():
        if item.is_file():
            item.unlink()

    with patch("app.api.download.DECRYPTED_DIR", temp_dirs["decrypted"]):
        with patch("app.api.download.PRIVATE_KEY_PATH", temp_dirs["keys"] / "age.key"):
            with patch.object(crypto_manager, "decrypt_file", AsyncMock()) as mock_decrypt:
                with patch.object(mock_db_session, "execute") as mock_execute:
                    mock_execute.side_effect = [
                        MagicMock(scalar_one_or_none=MagicMock(return_value=mock_link)),
                        MagicMock(scalar_one_or_none=MagicMock(return_value=mock_file))
                    ]

                    with patch.object(mock_db_session, "commit", AsyncMock()):
                        with patch.object(mock_db_session, "refresh", AsyncMock()):
                            response = await download_by_token(
                                request=MagicMock(),
                                background_tasks=MagicMock(),
                                token=token,
                                db=mock_db_session
                            )

                            assert response.filename == original_name
                            assert response.media_type == "application/octet-stream"
                            mock_decrypt.assert_called_once()
                            assert mock_link.downloads_count == 3


@pytest.mark.asyncio
async def test_download_by_token_expired(mock_user, mock_db_session):
    token = str(uuid.uuid4())

    mock_link = MagicMock()
    mock_link.token = token
    mock_link.expires_at = datetime.now(timezone.utc) - timedelta(days=1)

    with patch.object(mock_db_session, "execute") as mock_execute:
        mock_execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=mock_link))

        with pytest.raises(HTTPException) as exc_info:
            await download_by_token(
                request=MagicMock(),
                background_tasks=MagicMock(),
                token=token,
                db=mock_db_session
            )

        assert exc_info.value.status_code == 410
        assert "Ссылка истекла" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_download_by_token_limit_reached(mock_user, mock_db_session):
    token = str(uuid.uuid4())

    mock_link = MagicMock()
    mock_link.token = token
    mock_link.downloads_count = 5
    mock_link.max_downloads = 5

    with patch.object(mock_db_session, "execute") as mock_execute:
        mock_execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=mock_link))

        with pytest.raises(HTTPException) as exc_info:
            await download_by_token(
                request=MagicMock(),
                background_tasks=MagicMock(),
                token=token,
                db=mock_db_session
            )

        assert exc_info.value.status_code == 410
        assert "Лимит скачиваний исчерпан" in str(exc_info.value.detail)


def test_delete_file_after_response(temp_dirs):
    decrypted = temp_dirs["decrypted"]
    temp_file = decrypted / "temp_test.txt"
    temp_file.write_text("data")

    delete_file_after_response(temp_file)

    assert not temp_file.exists()


# POST /download (doctor/admin)

def test_download_file_post_success(client_with_doctor, mock_user, temp_dirs):
    filename = "test.age"

    encrypted_path = temp_dirs["encrypted"] / filename
    encrypted_path.write_text("fake encrypted")

    decrypted_path = temp_dirs["decrypted"] / f"dec_{uuid.uuid4().hex[:12]}_test"

    with patch("app.api.download.ENCRYPTED_DIR", temp_dirs["encrypted"]):
        with patch("app.api.download.DECRYPTED_DIR", temp_dirs["decrypted"]):
            with patch.object(crypto_manager, "decrypt_file", AsyncMock()):
                with patch.object(audit_logger, "log_operation") as mock_log:
                    response = client_with_doctor.post(
                        "/api/download",
                        data={"filename": filename}
                    )

                    assert response.status_code == 200
                    assert response.headers["Content-Disposition"].startswith('attachment; filename="test"')
                    mock_log.assert_any_call(
                        action="download",
                        filename=filename,
                        user="api_user",
                        reason="Успешное скачивание и расшифровка",
                        success=True
                    )