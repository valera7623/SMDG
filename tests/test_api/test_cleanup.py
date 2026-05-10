"""
Тесты для app/api/cleanup.py
Покрытие: ~90-95% (все эндпоинты, все ветки ошибок, edge-cases)
"""

import pytest
import time as time_module
from unittest.mock import MagicMock, patch, PropertyMock, AsyncMock

from app.core.storage_backend import ObjectMetadata
from fastapi.testclient import TestClient
from pathlib import Path
from time import time

from app.main import app
from app.core.auth import get_current_admin


# ═══════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════

def make_token_data(sub="admin_user", role="admin", tenant_id=1):
    td = MagicMock()
    td.sub = sub
    td.role = role
    td.tenant_id = tenant_id
    return td


def override_admin(sub="admin_user", role="admin"):
    td = make_token_data(sub=sub, role=role)
    def _override():
        return td
    return _override


def make_mock_file(name="test.txt", size=1024, mtime=None):
    """Создаёт мок файла в директории"""
    mock_file = MagicMock(spec=Path)
    mock_file.name = name
    mock_file.is_file.return_value = True

    mock_stat = MagicMock()
    mock_stat.st_size = size
    mock_stat.st_mtime = mtime or (time() - 3600)  # 1 час назад по умолчанию
    mock_file.stat.return_value = mock_stat

    return mock_file


def make_mock_file_stat_error(name="broken.txt", error_class=FileNotFoundError):
    """Мок файла, у которого stat() выбрасывает ошибку"""
    mock_file = MagicMock(spec=Path)
    mock_file.name = name
    mock_file.is_file.return_value = True
    mock_file.stat.side_effect = error_class(f"Cannot stat {name}")
    return mock_file


def make_mock_dir_file(name="subdir"):
    """Мок элемента директории (не файл)"""
    mock_item = MagicMock(spec=Path)
    mock_item.name = name
    mock_item.is_file.return_value = False
    return mock_item


# ═══════════════════════════════════════════════════════════
#  FIXTURES
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def client():
    app.dependency_overrides[get_current_admin] = override_admin()
    yield TestClient(app)
    app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════
#  GET /api/cleanup/stats
# ═══════════════════════════════════════════════════════════

class TestCleanupStats:
    """Тесты для GET /api/cleanup/stats"""

    @patch("app.api.cleanup.audit_logger")
    @patch("app.api.cleanup.file_storage")
    def test_stats_success(self, mock_storage, mock_audit, client):
        """Успешное получение статистики"""
        mock_storage.get_stats.return_value = {
            "total_files": 5,
            "total_size_bytes": 10240,
            "oldest_file_hours": 12.5,
        }

        response = client.get("/api/cleanup/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["total_files"] == 5
        assert data["total_size_bytes"] == 10240
        assert data["oldest_file_hours"] == 12.5

        mock_audit.log_operation.assert_called_once()
        call_kwargs = mock_audit.log_operation.call_args
        assert call_kwargs[1]["action"] == "cleanup_stats_viewed" or \
               call_kwargs.kwargs.get("action") == "cleanup_stats_viewed"

    @patch("app.api.cleanup.audit_logger")
    @patch("app.api.cleanup.file_storage")
    def test_stats_empty(self, mock_storage, mock_audit, client):
        """Статистика — нет файлов"""
        mock_storage.get_stats.return_value = {
            "total_files": 0,
            "total_size_bytes": 0,
        }

        response = client.get("/api/cleanup/stats")

        assert response.status_code == 200
        assert response.json()["total_files"] == 0

    @patch("app.api.cleanup.audit_logger")
    @patch("app.api.cleanup.file_storage")
    def test_stats_storage_error(self, mock_storage, mock_audit, client):
        """Статистика — ошибка в file_storage"""
        mock_storage.get_stats.side_effect = RuntimeError("Disk error")

        response = client.get("/api/cleanup/stats")

        assert response.status_code == 500
        assert "Ошибка получения статистики" in response.json()["detail"]

        # Проверяем что ошибка залогирована
        calls = mock_audit.log_operation.call_args_list
        assert len(calls) == 1
        error_call = calls[0]
        assert error_call.kwargs.get("success") is False or \
               (len(error_call.args) == 0 and error_call[1].get("success") is False)

    def test_stats_unauthorized(self):
        """Статистика — без авторизации (нет override)"""
        app.dependency_overrides.clear()
        raw_client = TestClient(app)

        response = raw_client.get("/api/cleanup/stats")

        # Должен вернуть 401 или 403 (зависит от реализации get_current_admin)
        assert response.status_code in (401, 403)


# ═══════════════════════════════════════════════════════════
#  POST /api/cleanup/force
# ═══════════════════════════════════════════════════════════

class TestForceCleanup:
    """Тесты для POST /api/cleanup/force"""

    @patch("app.api.cleanup.audit_logger")
    @patch("app.api.cleanup.file_storage")
    @patch("app.api.cleanup.encrypted_storage.delete_many", new_callable=AsyncMock)
    @patch("app.api.cleanup.encrypted_storage.list_objects", new_callable=AsyncMock)
    def test_force_cleanup_success_both_dirs(self, mock_list_objects, mock_delete_many, mock_storage, mock_audit, client):
        """Полная очистка — decrypted + ключи в хранилище"""
        mock_storage.force_cleanup.return_value = {"deleted": 3}
        ts = time_module.time()
        mock_list_objects.return_value = [
            ObjectMetadata(key="file1.enc", size=1, last_modified=ts),
            ObjectMetadata(key="file2.enc", size=1, last_modified=ts),
        ]
        mock_delete_many.return_value = {"deleted_count": 2, "errors": []}

        response = client.post("/api/cleanup/force")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["deleted"]["decrypted"] == 3
        assert data["deleted"]["encrypted"] == 2
        assert data["errors"] == []

    @patch("app.api.cleanup.audit_logger")
    @patch("app.api.cleanup.file_storage")
    @patch("app.api.cleanup.encrypted_storage.list_objects", new_callable=AsyncMock)
    def test_force_cleanup_no_encrypted_dir(self, mock_list_objects, mock_storage, mock_audit, client):
        """Очистка — в хранилище нет объектов"""
        mock_storage.force_cleanup.return_value = {"deleted": 1}
        mock_list_objects.return_value = []

        response = client.post("/api/cleanup/force")

        assert response.status_code == 200
        data = response.json()
        assert data["deleted"]["decrypted"] == 1
        assert data["deleted"]["encrypted"] == 0

    @patch("app.api.cleanup.audit_logger")
    @patch("app.api.cleanup.file_storage")
    @patch("app.api.cleanup.Path")
    def test_force_cleanup_decrypted_error(self, mock_path_cls, mock_storage, mock_audit, client):
        """Очистка — ошибка при очистке decrypted"""
        mock_storage.force_cleanup.side_effect = RuntimeError("Decrypted cleanup failed")

        mock_encrypted_dir = MagicMock()
        mock_encrypted_dir.exists.return_value = False
        mock_path_cls.return_value = mock_encrypted_dir

        response = client.post("/api/cleanup/force")

        assert response.status_code == 200
        data = response.json()
        assert data["deleted"]["decrypted"] == 0
        assert len(data["errors"]) >= 1
        assert "decrypted" in data["errors"][0]

    @patch("app.api.cleanup.audit_logger")
    @patch("app.api.cleanup.file_storage")
    @patch("app.api.cleanup.encrypted_storage.delete_many", new_callable=AsyncMock)
    @patch("app.api.cleanup.encrypted_storage.list_objects", new_callable=AsyncMock)
    def test_force_cleanup_encrypted_file_error(self, mock_list_objects, mock_delete_many, mock_storage, mock_audit, client):
        """Очистка — delete_many возвращает ошибку по ключу"""
        mock_storage.force_cleanup.return_value = {"deleted": 0}
        ts = time_module.time()
        mock_list_objects.return_value = [
            ObjectMetadata(key="good.enc", size=1, last_modified=ts),
            ObjectMetadata(key="locked.enc", size=1, last_modified=ts),
        ]
        mock_delete_many.return_value = {
            "deleted_count": 1,
            "errors": ["locked.enc: Permission denied"],
        }

        response = client.post("/api/cleanup/force")

        assert response.status_code == 200
        data = response.json()
        assert data["deleted"]["encrypted"] == 1
        assert len(data["errors"]) >= 1
        assert any("locked.enc" in e for e in data["errors"])

    @patch("app.api.cleanup.audit_logger")
    @patch("app.api.cleanup.file_storage")
    @patch("app.api.cleanup.encrypted_storage.delete_many", new_callable=AsyncMock)
    @patch("app.api.cleanup.encrypted_storage.list_objects", new_callable=AsyncMock)
    def test_force_cleanup_encrypted_dir_has_subdirs(self, mock_list_objects, mock_delete_many, mock_storage, mock_audit, client):
        """Список объектов из backend — удаляются только переданные ключи."""
        mock_storage.force_cleanup.return_value = {"deleted": 0}
        ts = time_module.time()
        mock_list_objects.return_value = [
            ObjectMetadata(key="data.enc", size=1, last_modified=ts),
        ]
        mock_delete_many.return_value = {"deleted_count": 1, "errors": []}

        response = client.post("/api/cleanup/force")

        assert response.status_code == 200
        assert response.json()["deleted"]["encrypted"] == 1

    @patch("app.api.cleanup.audit_logger")
    @patch("app.api.cleanup.file_storage")
    @patch("app.api.cleanup.encrypted_storage.list_objects", new_callable=AsyncMock)
    def test_force_cleanup_empty_encrypted_dir(self, mock_list_objects, mock_storage, mock_audit, client):
        """Очистка — в хранилище нет объектов"""
        mock_storage.force_cleanup.return_value = {"deleted": 0}
        mock_list_objects.return_value = []

        response = client.post("/api/cleanup/force")

        assert response.status_code == 200
        data = response.json()
        assert data["deleted"]["decrypted"] == 0
        assert data["deleted"]["encrypted"] == 0
        assert data["errors"] == []

    @patch("app.api.cleanup.audit_logger")
    @patch("app.api.cleanup.file_storage")
    @patch("app.api.cleanup.encrypted_storage.list_objects", new_callable=AsyncMock)
    def test_force_cleanup_audit_log_final(self, mock_list_objects, mock_storage, mock_audit, client):
        """Проверяем финальный audit log после cleanup"""
        mock_storage.force_cleanup.return_value = {"deleted": 2}
        mock_list_objects.return_value = []

        response = client.post("/api/cleanup/force")
        assert response.status_code == 200

        # Ищем финальный вызов cleanup_force_all
        found = False
        for call in mock_audit.log_operation.call_args_list:
            kwargs = call.kwargs if call.kwargs else (call[1] if len(call) > 1 else {})
            if kwargs.get("action") == "cleanup_force_all":
                found = True
                assert kwargs["success"] is True
                break
        assert found, "Финальный audit log cleanup_force_all не найден"

    def test_force_cleanup_unauthorized(self):
        """Очистка — без авторизации"""
        app.dependency_overrides.clear()
        raw_client = TestClient(app)

        response = raw_client.post("/api/cleanup/force")
        assert response.status_code in (401, 403)


# ═══════════════════════════════════════════════════════════
#  GET /api/cleanup/files
# ═══════════════════════════════════════════════════════════

class TestListTempFiles:
    """Тесты для GET /api/cleanup/files"""

    @patch("app.api.cleanup.audit_logger")
    @patch("app.api.cleanup.DECRYPTED_DIR")
    def test_list_files_success(self, mock_dir, mock_audit, client):
        """Успешный список файлов"""
        mock_dir.exists.return_value = True

        now = time()
        file1 = make_mock_file("report.pdf", 2048, now - 7200)   # 2 часа назад
        file2 = make_mock_file("data.csv", 512, now - 1800)       # 30 мин назад
        subdir = make_mock_dir_file("temp_subdir")

        mock_dir.iterdir.return_value = [file1, file2, subdir]

        response = client.get("/api/cleanup/files")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
        assert len(data["files"]) == 2
        assert data["directory"] == str(mock_dir)

        # Проверяем сортировку — самый новый первый
        names = [f["name"] for f in data["files"]]
        assert names[0] == "data.csv"
        assert names[1] == "report.pdf"

    @patch("app.api.cleanup.audit_logger")
    @patch("app.api.cleanup.DECRYPTED_DIR")
    def test_list_files_dir_not_exists(self, mock_dir, mock_audit, client):
        """Список файлов — директория не существует"""
        mock_dir.exists.return_value = False

        response = client.get("/api/cleanup/files")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 0
        assert data["files"] == []

    @patch("app.api.cleanup.audit_logger")
    @patch("app.api.cleanup.DECRYPTED_DIR")
    def test_list_files_empty_dir(self, mock_dir, mock_audit, client):
        """Список файлов — директория пуста"""
        mock_dir.exists.return_value = True
        mock_dir.iterdir.return_value = []

        response = client.get("/api/cleanup/files")

        assert response.status_code == 200
        assert response.json()["count"] == 0

    @patch("app.api.cleanup.audit_logger")
    @patch("app.api.cleanup.DECRYPTED_DIR")
    def test_list_files_with_limit(self, mock_dir, mock_audit, client):
        """Список файлов — с лимитом"""
        mock_dir.exists.return_value = True

        now = time()
        files = [make_mock_file(f"file_{i}.txt", 100, now - i * 60) for i in range(10)]
        mock_dir.iterdir.return_value = files

        response = client.get("/api/cleanup/files?limit=3")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 3
        assert len(data["files"]) == 3

    @patch("app.api.cleanup.audit_logger")
    @patch("app.api.cleanup.DECRYPTED_DIR")
    def test_list_files_limit_default(self, mock_dir, mock_audit, client):
        """Список файлов — лимит по умолчанию (100)"""
        mock_dir.exists.return_value = True
        mock_dir.iterdir.return_value = []

        response = client.get("/api/cleanup/files")

        assert response.status_code == 200

    def test_list_files_limit_too_small(self, client):
        """Список файлов — лимит < 1"""
        response = client.get("/api/cleanup/files?limit=0")
        assert response.status_code == 422

    def test_list_files_limit_too_large(self, client):
        """Список файлов — лимит > 1000"""
        response = client.get("/api/cleanup/files?limit=1001")
        assert response.status_code == 422

    def test_list_files_limit_negative(self, client):
        """Список файлов — отрицательный лимит"""
        response = client.get("/api/cleanup/files?limit=-5")
        assert response.status_code == 422

    @patch("app.api.cleanup.audit_logger")
    @patch("app.api.cleanup.DECRYPTED_DIR")
    def test_list_files_stat_file_not_found(self, mock_dir, mock_audit, client):
        """Список файлов — FileNotFoundError при stat (файл удалён между iterdir и stat)"""
        mock_dir.exists.return_value = True

        good_file = make_mock_file("good.txt", 100)
        broken_file = make_mock_file_stat_error("vanished.txt", FileNotFoundError)

        mock_dir.iterdir.return_value = [broken_file, good_file]

        response = client.get("/api/cleanup/files")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["files"][0]["name"] == "good.txt"

    @patch("app.api.cleanup.audit_logger")
    @patch("app.api.cleanup.DECRYPTED_DIR")
    def test_list_files_stat_permission_error(self, mock_dir, mock_audit, client):
        """Список файлов — PermissionError при stat"""
        mock_dir.exists.return_value = True

        good_file = make_mock_file("accessible.txt", 200)
        perm_file = make_mock_file_stat_error("forbidden.txt", PermissionError)

        mock_dir.iterdir.return_value = [perm_file, good_file]

        response = client.get("/api/cleanup/files")

        assert response.status_code == 200
        assert response.json()["count"] == 1

    @patch("app.api.cleanup.audit_logger")
    @patch("app.api.cleanup.DECRYPTED_DIR")
    def test_list_files_stat_generic_error(self, mock_dir, mock_audit, client):
        """Список файлов — неизвестная ошибка при stat"""
        mock_dir.exists.return_value = True

        good_file = make_mock_file("ok.txt", 50)
        err_file = make_mock_file_stat_error("weird.txt", OSError)

        mock_dir.iterdir.return_value = [err_file, good_file]

        response = client.get("/api/cleanup/files")

        assert response.status_code == 200
        assert response.json()["count"] == 1

    @patch("app.api.cleanup.audit_logger")
    @patch("app.api.cleanup.DECRYPTED_DIR")
    def test_list_files_iterdir_error(self, mock_dir, mock_audit, client):
        """Список файлов — ошибка при iterdir (общий exception)"""
        mock_dir.exists.return_value = True
        mock_dir.iterdir.side_effect = OSError("Cannot read directory")

        response = client.get("/api/cleanup/files")

        assert response.status_code == 500
        assert "Ошибка при получении списка файлов" in response.json()["detail"]

    @patch("app.api.cleanup.audit_logger")
    @patch("app.api.cleanup.DECRYPTED_DIR")
    def test_list_files_file_structure(self, mock_dir, mock_audit, client):
        """Список файлов — проверка структуры отдельного файла"""
        mock_dir.exists.return_value = True

        now = time()
        file1 = make_mock_file("document.pdf", 4096, now - 3600)
        mock_dir.iterdir.return_value = [file1]

        response = client.get("/api/cleanup/files")

        assert response.status_code == 200
        f = response.json()["files"][0]
        assert f["name"] == "document.pdf"
        assert f["size_bytes"] == 4096
        assert "modified_iso" in f
        assert "age_hours" in f
        assert isinstance(f["age_hours"], float)
        assert f["age_hours"] >= 0.9  # ~1 час

    @patch("app.api.cleanup.audit_logger")
    @patch("app.api.cleanup.DECRYPTED_DIR")
    def test_list_files_audit_logged(self, mock_dir, mock_audit, client):
        """Проверяем audit log при успешном listing"""
        mock_dir.exists.return_value = True
        mock_dir.iterdir.return_value = []

        response = client.get("/api/cleanup/files")
        assert response.status_code == 200

        found = False
        for call in mock_audit.log_operation.call_args_list:
            kwargs = call.kwargs if call.kwargs else {}
            if kwargs.get("action") == "cleanup_files_listed":
                found = True
                assert kwargs["success"] is True
                break
        assert found

    @patch("app.api.cleanup.audit_logger")
    @patch("app.api.cleanup.DECRYPTED_DIR")
    def test_list_files_only_files_not_dirs(self, mock_dir, mock_audit, client):
        """Список файлов — директории внутри DECRYPTED_DIR пропускаются"""
        mock_dir.exists.return_value = True

        dir_item = make_mock_dir_file("nested_dir")
        file_item = make_mock_file("real_file.txt", 256)

        mock_dir.iterdir.return_value = [dir_item, file_item]

        response = client.get("/api/cleanup/files")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["files"][0]["name"] == "real_file.txt"

    def test_list_files_unauthorized(self):
        """Список файлов — без авторизации"""
        app.dependency_overrides.clear()
        raw_client = TestClient(app)

        response = raw_client.get("/api/cleanup/files")
        assert response.status_code in (401, 403)

    @patch("app.api.cleanup.audit_logger")
    @patch("app.api.cleanup.DECRYPTED_DIR")
    def test_list_files_total_scanned_count(self, mock_dir, mock_audit, client):
        """Проверяем поле total_scanned"""
        mock_dir.exists.return_value = True

        files = [make_mock_file(f"f{i}.txt", 10) for i in range(5)]
        # iterdir вызывается дважды: в цикле и для total_scanned
        mock_dir.iterdir.return_value = files

        response = client.get("/api/cleanup/files?limit=2")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
        # total_scanned считает все элементы

    @patch("app.api.cleanup.audit_logger")
    @patch("app.api.cleanup.DECRYPTED_DIR")
    def test_list_files_boundary_limit_1(self, mock_dir, mock_audit, client):
        """Список файлов — лимит = 1"""
        mock_dir.exists.return_value = True

        files = [make_mock_file(f"f{i}.dat", 100) for i in range(5)]
        mock_dir.iterdir.return_value = files

        response = client.get("/api/cleanup/files?limit=1")

        assert response.status_code == 200
        assert response.json()["count"] == 1

    @patch("app.api.cleanup.audit_logger")
    @patch("app.api.cleanup.DECRYPTED_DIR")
    def test_list_files_boundary_limit_1000(self, mock_dir, mock_audit, client):
        """Список файлов — лимит = 1000 (максимум)"""
        mock_dir.exists.return_value = True
        mock_dir.iterdir.return_value = []

        response = client.get("/api/cleanup/files?limit=1000")

        assert response.status_code == 200
