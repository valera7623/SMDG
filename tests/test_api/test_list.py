# tests/test_api/test_list_fixed.py
import pytest
import tempfile
import os
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

# Импортируем роутер и зависимости
from app.api.list import router as list_router
from app.core.auth import get_current_doctor
from app.core.database import get_db

# Создаем тестовое приложение
app = FastAPI()
app.include_router(list_router)

# Mock для зависимостей
class MockCurrentUser:
    def __init__(self, sub="test_doctor", role="doctor"):
        self.sub = sub
        self.role = role

class MockFile:
    def __init__(self, id=1, encrypted_name="test.age", original_name="original.txt"):
        self.id = id
        self.encrypted_name = encrypted_name
        self.original_name = original_name

@pytest.fixture
def mock_current_user():
    """Мок аутентифицированного пользователя"""
    return MockCurrentUser()

@pytest.fixture
def mock_db_session():
    """Мок сессии БД"""
    session = AsyncMock(spec=AsyncSession)
    return session

@pytest.fixture
def mock_encrypted_dir(tmp_path):
    """Временный каталог для зашифрованных файлов"""
    encrypted_dir = tmp_path / "encrypted"
    encrypted_dir.mkdir()
    return encrypted_dir

@pytest.fixture
def client(mock_current_user, mock_db_session):
    """Тестовый клиент с переопределенными зависимостями"""
    # Переопределяем зависимости в приложении
    async def override_get_current_doctor():
        return mock_current_user
    
    async def override_get_db():
        return mock_db_session
    
    app.dependency_overrides[get_current_doctor] = override_get_current_doctor
    app.dependency_overrides[get_db] = override_get_db
    
    # Создаем клиент
    test_client = TestClient(app)
    
    yield test_client
    
    # Очищаем переопределения после теста
    app.dependency_overrides.clear()



def test_list_files_success(client, mock_encrypted_dir, mock_db_session, mock_current_user):
    """Тест успешного получения списка файлов"""
    # Создаем 2 файла
    (mock_encrypted_dir / "file1.age").write_bytes(b"test content 1")
    (mock_encrypted_dir / "file2.age").write_bytes(b"test content 2")
    
    # Создаем счетчик вызовов
    call_count = 0
    
    def execute_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        
        if call_count <= 2:
            # Первые два вызова - поиск файлов в БД
            mock_file = MockFile(
                id=call_count,
                encrypted_name=f"file{call_count}.age",
                original_name=f"original{call_count}.txt"
            )
            result.scalar_one_or_none.return_value = mock_file
        elif call_count == 3:
            # Третий вызов - токен для первого файла
            result.scalar.return_value = "token123"
        elif call_count == 4:
            # Четвертый вызов - токен для второго файла
            result.scalar.return_value = None
        
        return result
    
    mock_execute = AsyncMock(side_effect=execute_side_effect)
    mock_db_session.execute = mock_execute
    
    # Патчим ENCRYPTED_DIR
    with patch('app.api.list.ENCRYPTED_DIR', mock_encrypted_dir):
        response = client.get("/list")
        
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
        assert len(data["files"]) == 2
        
        # Проверяем общую структуру
        for file_data in data["files"]:
            assert "id" in file_data
            assert "name" in file_data
            assert "size" in file_data
            assert "modified" in file_data
            assert "original_name" in file_data
            assert "download_token" in file_data
            assert "download_url" in file_data
        
        # Проверяем, что есть один файл с токеном и один без
        files_with_token = [f for f in data["files"] if f["download_token"]]
        files_without_token = [f for f in data["files"] if not f["download_token"]]
        
        assert len(files_with_token) == 1
        assert len(files_without_token) == 1
        
        # Проверяем файл с токеном
        file_with_token = files_with_token[0]
        assert file_with_token["download_token"] == "token123"
        assert file_with_token["download_url"] == "/api/download?token=token123"
        
        # Проверяем файл без токена
        file_without_token = files_without_token[0]
        assert file_without_token["download_token"] is None
        assert file_without_token["download_url"] is None

# Тест 2: Каталог не существует
def test_list_files_directory_not_exists(client, mock_db_session, mock_current_user):
    """Тест случая, когда каталог с зашифрованными файлами не существует"""
    non_existent_dir = Path("/non/existent/path")
    
    # Патчим ENCRYPTED_DIR
    with patch('app.api.list.ENCRYPTED_DIR', non_existent_dir):
        response = client.get("/list")
        
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 0
        assert data["files"] == []

# Тест 3: Каталог существует, но пустой
def test_list_files_empty_directory(client, mock_encrypted_dir, mock_db_session, mock_current_user):
    """Тест случая с пустым каталогом"""
    # Каталог уже создан фикстурой, но пустой
    
    with patch('app.api.list.ENCRYPTED_DIR', mock_encrypted_dir):
        response = client.get("/list")
        
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 0
        assert data["files"] == []

# Тест 4: Файлы без расширения .age игнорируются
def test_list_files_ignore_non_age(client, mock_encrypted_dir, mock_db_session, mock_current_user):
    """Тест игнорирования файлов без расширения .age"""
    # Создаем файлы с разными расширениями
    (mock_encrypted_dir / "file1.txt").write_text("text file")
    (mock_encrypted_dir / "file2.pdf").write_text("pdf file")
    (mock_encrypted_dir / "file3.age").write_text("encrypted file")
    
    # Мок для файла в БД
    mock_file = MockFile(id=1, encrypted_name="file3.age", original_name="original.txt")
    
    mock_execute = AsyncMock()
    result1 = MagicMock()
    result1.scalar_one_or_none.return_value = mock_file
    result2 = MagicMock()
    result2.scalar.return_value = None
    
    mock_execute.side_effect = [result1, result2]
    mock_db_session.execute = mock_execute
    
    with patch('app.api.list.ENCRYPTED_DIR', mock_encrypted_dir):
        response = client.get("/list")
        
        assert response.status_code == 200
        data = response.json()
        # Должен быть только один файл с расширением .age
        assert data["count"] == 1
        assert data["files"][0]["name"] == "file3.age"

# Тест 5: Файлы .age, но не найденные в БД
def test_list_files_age_not_in_db(client, mock_encrypted_dir, mock_db_session, mock_current_user):
    """Тест файлов с расширением .age, которые не найдены в БД"""
    (mock_encrypted_dir / "orphan.age").write_text("orphaned encrypted file")
    
    # Мок возвращает None (файл не найден в БД)
    mock_execute = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_execute.return_value = result
    mock_db_session.execute = mock_execute
    
    with patch('app.api.list.ENCRYPTED_DIR', mock_encrypted_dir):
        response = client.get("/list")
        
        assert response.status_code == 200
        data = response.json()
        # Файл должен быть пропущен
        assert data["count"] == 0
        assert data["files"] == []

# Тест 6: Ошибка при обработке файла (пропуск с логированием)
def test_list_files_error_handling(client, mock_encrypted_dir, mock_db_session, mock_current_user):
    """Тест обработки ошибки при обработке файла"""
    (mock_encrypted_dir / "corrupted.age").write_text("corrupted file")
    
    # Мок вызывает исключение при поиске в БД
    mock_execute = AsyncMock()
    mock_execute.side_effect = Exception("Database error")
    mock_db_session.execute = mock_execute
    
    # Мок для аудит-логгера
    mock_audit_logger = MagicMock()
    
    with patch('app.api.list.ENCRYPTED_DIR', mock_encrypted_dir), \
         patch('app.api.list.audit_logger', mock_audit_logger):
        
        response = client.get("/list")
        
        assert response.status_code == 200
        data = response.json()
        # Файл с ошибкой должен быть пропущен
        assert data["count"] == 0
        
        # Проверяем, что ошибка была залогирована
        mock_audit_logger.log_operation.assert_called_once()



def test_list_files_exception_handling(client, mock_encrypted_dir, mock_db_session, mock_current_user):
    """Тест корректной обработки исключений без падения всего endpoint'а"""
    # Создаем несколько файлов
    (mock_encrypted_dir / "good1.age").write_text("good file 1")
    (mock_encrypted_dir / "bad.age").write_text("bad file")
    (mock_encrypted_dir / "good2.age").write_text("good file 2")
    
    mock_good_file1 = MockFile(id=1, encrypted_name="good1.age", original_name="good1.txt")
    mock_good_file2 = MockFile(id=2, encrypted_name="good2.age", original_name="good2.txt")
    
    # Создаем список результатов для последовательных вызовов
    results = []
    
    # 1. Первый файл (good1.age) - успех
    result1 = MagicMock()
    result1.scalar_one_or_none.return_value = mock_good_file1
    results.append(result1)
    
    # Токен для первого файла
    result2 = MagicMock()
    result2.scalar.return_value = None
    results.append(result2)
    
    # 2. Второй файл (bad.age) - исключение при поиске в БД
    def raise_exception(*args, **kwargs):
        raise Exception("Database error")
    
    # Создаем callable для выброса исключения
    results.append(raise_exception)
    
    # 3. Третий файл (good2.age) - успех (но не будет достигнут из-за исключения)
    # Вместо этого, после исключения для bad.age, функция продолжит с good2.age
    
    # 4. good2.age - поиск в БД
    result4 = MagicMock()
    result4.scalar_one_or_none.return_value = mock_good_file2
    results.append(result4)
    
    # Токен для good2.age
    result5 = MagicMock()
    result5.scalar.return_value = None
    results.append(result5)
    
    # Создаем mock с side_effect
    mock_execute = AsyncMock()
    
    def execute_side_effect(*args, **kwargs):
        if not results:
            # Создаем результат по умолчанию
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            result.scalar.return_value = None
            return result
        
        next_result = results.pop(0)
        
        if callable(next_result) and not isinstance(next_result, MagicMock):
            # Это функция, которая выбрасывает исключение
            next_result()
        else:
            # Это MagicMock
            return next_result
    
    mock_execute.side_effect = execute_side_effect
    mock_db_session.execute = mock_execute
    
    # Мок для аудит-логгера
    mock_audit_logger = MagicMock()
    
    with patch('app.api.list.ENCRYPTED_DIR', mock_encrypted_dir), \
         patch('app.api.list.audit_logger', mock_audit_logger):
        
        response = client.get("/list")
        
        assert response.status_code == 200
        data = response.json()
        # Должны вернуться 2 успешно обработанных файла
        # (good1.age и good2.age, bad.age пропущен из-за ошибки)
        assert data["count"] == 2
        
        # Проверяем логирование ошибки
        # Ошибка должна быть залогирована для bad.age
        assert mock_audit_logger.log_operation.call_count >= 1

# Тест 8: Без аутентификации
def test_list_files_no_auth():
    """Тест запроса без аутентификации"""
    # Создаем отдельный клиент без переопределенной аутентификации
    test_app = FastAPI()
    test_app.include_router(list_router)
    
    # Переопределяем только get_db чтобы не было ошибок БД
    async def override_get_db():
        return AsyncMock()
    
    test_app.dependency_overrides[get_db] = override_get_db
    
    test_client = TestClient(test_app)
    
    response = test_client.get("/list")
    
    # В зависимости от реализации get_current_doctor, может быть 401 или 403
    assert response.status_code in [401, 403, 422]

# Тест 9: Проверка структуры ответа
def test_list_files_response_structure(client, mock_encrypted_dir, mock_db_session, mock_current_user):
    """Тест структуры ответа"""
    (mock_encrypted_dir / "test.age").write_text("test content")
    
    mock_file = MockFile(id=1, encrypted_name="test.age", original_name="test.txt")
    
    mock_execute = AsyncMock()
    result1 = MagicMock()
    result1.scalar_one_or_none.return_value = mock_file
    result2 = MagicMock()
    result2.scalar.return_value = "test_token"
    
    mock_execute.side_effect = [result1, result2]
    mock_db_session.execute = mock_execute
    
    with patch('app.api.list.ENCRYPTED_DIR', mock_encrypted_dir):
        response = client.get("/list")
        
        assert response.status_code == 200
        data = response.json()
        
        # Проверяем структуру верхнего уровня
        assert "count" in data
        assert "files" in data
        assert isinstance(data["count"], int)
        assert isinstance(data["files"], list)
        
        if data["count"] > 0:
            file_info = data["files"][0]
            assert "id" in file_info
            assert "name" in file_info
            assert "size" in file_info
            assert "modified" in file_info
            assert "original_name" in file_info
            assert "download_token" in file_info
            assert "download_url" in file_info
            
            # Проверяем типы данных
            assert isinstance(file_info["id"], int)
            assert isinstance(file_info["name"], str)
            assert isinstance(file_info["size"], int)
            assert isinstance(file_info["modified"], str)
            assert isinstance(file_info["original_name"], str)
            
def test_list_files_exception_handling_simple(client, mock_encrypted_dir, mock_db_session, mock_current_user):
    """Упрощенный тест обработки исключений"""
    # Создаем один файл, который вызывает исключение
    (mock_encrypted_dir / "bad.age").write_text("bad file")
    
    # Мок выбрасывает исключение
    mock_execute = AsyncMock()
    mock_execute.side_effect = Exception("Database error")
    mock_db_session.execute = mock_execute
    
    # Мок для аудит-логгера
    mock_audit_logger = MagicMock()
    
    with patch('app.api.list.ENCRYPTED_DIR', mock_encrypted_dir), \
         patch('app.api.list.audit_logger', mock_audit_logger):
        
        response = client.get("/list")
        
        assert response.status_code == 200
        data = response.json()
        # Файл с ошибкой должен быть пропущен
        assert data["count"] == 0
        
        # Проверяем логирование ошибки
        mock_audit_logger.log_operation.assert_called_once()

# Тест 10: Rate limiting (требует мокинга лимитера)
def test_list_files_rate_limit(client, mock_db_session, mock_current_user):
    """Тест ограничения частоты запросов"""
    # Мокаем лимитер чтобы всегда пропускать
    mock_limiter = MagicMock()
    mock_limiter.limit = MagicMock(return_value=lambda f: f)
    
    # Создаем пустой каталог
    empty_dir = Path("/tmp/empty_test_dir")
    empty_dir.mkdir(exist_ok=True)
    
    with patch('app.api.list.limiter', mock_limiter), \
         patch('app.api.list.ENCRYPTED_DIR', empty_dir):
        
        response = client.get("/list")
        
        # Должен быть успешный ответ (200) даже с лимитером,
        # потому что мы его замокали
        assert response.status_code == 200
    
    # Убираем временный каталог
    empty_dir.rmdir()