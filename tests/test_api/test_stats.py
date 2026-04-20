# tests/test_stats.py
"""
Тесты для app/api/stats.py
Переписаны под реальную структуру модуля.
"""

import pytest
import time
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, call
from fastapi.testclient import TestClient

from app.main import app
from app.core.auth import get_current_user
from app.core.auth_utils import TokenData


# ============================================================================
# ФИКСТУРЫ
# ============================================================================

@pytest.fixture
def admin_token_data():
    """TokenData для администратора."""
    return TokenData(sub="admin-uuid-123", role="admin")


@pytest.fixture
def doctor_token_data():
    """TokenData для врача (не-админ)."""
    return TokenData(sub="doctor-uuid-456", role="doctor")


@pytest.fixture
def stats_client(admin_token_data):
    """
    TestClient с подменённой зависимостью get_current_admin.
    Не конфликтует с глобальным client из conftest.
    """
    from app.core.auth import get_current_admin  # импортируем то, что используется в stats.py

    app.dependency_overrides[get_current_admin] = lambda: admin_token_data

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    app.dependency_overrides.pop(get_current_admin, None)


@pytest.fixture
def stats_client_no_auth():
    """TestClient без подмены зависимостей."""
    app.dependency_overrides.clear()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def mock_dir_with_files(tmp_path):
    """Временная директория с несколькими файлами."""
    d = tmp_path / "storage"
    d.mkdir()
    (d / "file1.txt").write_text("hello")
    (d / "file2.pdf").write_bytes(b"x" * 2048)
    sub = d / "sub"
    sub.mkdir()
    (sub / "nested.age").write_bytes(b"y" * 512)
    return d


@pytest.fixture
def mock_empty_dir(tmp_path):
    """Пустая временная директория."""
    d = tmp_path / "empty"
    d.mkdir()
    return d


# ============================================================================
# ТЕСТЫ ВСПОМОГАТЕЛЬНОЙ ФУНКЦИИ _safe_directory_stats
# ============================================================================

class TestSafeDirectoryStats:
    """Тесты для _safe_directory_stats."""

    def test_existing_directory_with_files(self, mock_dir_with_files):
        from app.api.stats import _safe_directory_stats

        result = _safe_directory_stats(mock_dir_with_files)

        assert result["exists"] is True
        assert result["file_count"] == 3        # 2 в корне + 1 вложенный
        assert result["size_bytes"] > 0
        assert "path" in result

    def test_nonexistent_directory(self, tmp_path):
        from app.api.stats import _safe_directory_stats

        missing = tmp_path / "does_not_exist"
        result = _safe_directory_stats(missing)

        assert result["exists"] is False
        assert result["size_bytes"] == 0
        assert result["file_count"] == 0

    def test_empty_directory(self, mock_empty_dir):
        from app.api.stats import _safe_directory_stats

        result = _safe_directory_stats(mock_empty_dir)

        assert result["exists"] is True
        assert result["file_count"] == 0
        assert result["size_bytes"] == 0

    def test_returns_absolute_path(self, mock_dir_with_files):
        from app.api.stats import _safe_directory_stats

        result = _safe_directory_stats(mock_dir_with_files)

        assert "path" in result
        assert Path(result["path"]).is_absolute()

    def test_rglob_exception_returns_partial(self):
        """Когда rglob падает — возвращаем что успели."""
        from app.api.stats import _safe_directory_stats

        mock_dir = Mock(spec=Path)
        mock_dir.exists.return_value = True
        mock_dir.absolute.return_value = Path("/fake/path")

        # Один файл до исключения
        good_file = Mock()
        good_file.is_file.return_value = True
        good_file.stat.return_value.st_size = 100

        bad_file = Mock()
        bad_file.is_file.return_value = True
        bad_file.stat.side_effect = OSError("permission denied")

        mock_dir.rglob.return_value = iter([good_file, bad_file])

        result = _safe_directory_stats(mock_dir)

        # Первый файл посчитан, второй пропущен
        assert result["exists"] is True
        assert result["size_bytes"] == 100
        assert result["file_count"] == 1

    def test_rglob_complete_failure_returns_defaults(self):
        """Когда rglob полностью падает — возвращаем нули."""
        from app.api.stats import _safe_directory_stats

        mock_dir = Mock(spec=Path)
        mock_dir.exists.return_value = True
        mock_dir.absolute.return_value = Path("/fake/path")
        mock_dir.rglob.side_effect = PermissionError("no access")

        result = _safe_directory_stats(mock_dir)

        assert result["exists"] is True
        assert result["size_bytes"] == 0
        assert result["file_count"] == 0


# ============================================================================
# ТЕСТЫ _get_system_stats
# ============================================================================

class TestGetSystemStats:
    """Тесты для синхронной _get_system_stats."""

    def _patch_all(self):
        """Контекстный менеджер-хелпер — патчим всё разом."""
        return {
            "cpu_percent": patch("psutil.cpu_percent", return_value=42.0),
            "cpu_count":   patch("psutil.cpu_count",   return_value=4),
            "virtual_memory": patch("psutil.virtual_memory"),
            "disk_usage":     patch("psutil.disk_usage"),
            "boot_time":      patch("psutil.boot_time", return_value=time.time() - 3600),
            "platform_system":  patch("platform.system",  return_value="Linux"),
            "platform_version": patch("platform.python_version", return_value="3.12.0"),
            "platform_node":    patch("platform.node",   return_value="test-host"),
        }

    def test_returns_dict_with_required_keys(self):
        from app.api.stats import _get_system_stats

        result = _get_system_stats()

        assert isinstance(result, dict)
        assert "platform" in result
        assert "python_version" in result
        assert "hostname" in result
        # cpu/memory/disk могут быть "unavailable_in_container" — это OK
        assert "cpu" in result
        assert "memory" in result
        assert "disk" in result

    def test_normal_psutil_data(self):
        from app.api.stats import _get_system_stats

        mem = MagicMock()
        mem.total     = 16 * 1024**3
        mem.available =  8 * 1024**3
        mem.percent   = 50.0

        disk = MagicMock()
        disk.total   = 100 * 1024**3
        disk.free    =  50 * 1024**3
        disk.percent = 50.0

        with patch("psutil.cpu_percent", return_value=25.0), \
             patch("psutil.cpu_count",   return_value=8), \
             patch("psutil.virtual_memory", return_value=mem), \
             patch("psutil.disk_usage",     return_value=disk), \
             patch("psutil.boot_time",      return_value=time.time() - 7200):

            result = _get_system_stats()

        assert result["cpu"]["percent"] == 25.0
        assert result["cpu"]["count"]   == 8
        assert result["memory"]["total_gb"]     == 16.0
        assert result["memory"]["available_gb"] == 8.0
        assert result["memory"]["percent"]      == 50.0
        assert result["disk"]["total_gb"] == 100.0
        assert result["disk"]["free_gb"]  == 50.0
        assert result["uptime_seconds"] > 0

    def test_cpu_unavailable(self):
        from app.api.stats import _get_system_stats

        with patch("psutil.cpu_percent", side_effect=Exception("docker")), \
             patch("psutil.cpu_count",   side_effect=Exception("docker")):

            result = _get_system_stats()

        assert result["cpu"] == {"status": "unavailable_in_container"}

    def test_memory_unavailable(self):
        from app.api.stats import _get_system_stats

        with patch("psutil.virtual_memory", side_effect=Exception("no mem")):
            result = _get_system_stats()

        assert result["memory"] == {"status": "unavailable_in_container"}

    def test_disk_unavailable(self):
        from app.api.stats import _get_system_stats

        with patch("psutil.disk_usage", side_effect=Exception("no disk")):
            result = _get_system_stats()

        assert result["disk"] == {"status": "unavailable_in_container"}

    def test_uptime_unavailable(self):
        from app.api.stats import _get_system_stats

        with patch("psutil.boot_time", side_effect=Exception("no boot")):
            result = _get_system_stats()

        assert result["uptime_seconds"] == "unavailable"


# ============================================================================
# ТЕСТЫ _get_storage_stats
# ============================================================================

class TestGetStorageStats:
    """Тесты для _get_storage_stats."""

    def test_returns_required_keys(self):
        from app.api.stats import _get_storage_stats_sync as _get_storage_stats

        result = _get_storage_stats()

        assert "directories" in result
        assert "total_size_bytes" in result
        assert "total_size_mb" in result
        assert "total_size_gb" in result

    def test_aggregates_directory_sizes(self, tmp_path):
        from app.api.stats import _get_storage_stats_sync as _get_storage_stats

        enc_dir  = tmp_path / "enc";  enc_dir.mkdir()
        dec_dir  = tmp_path / "dec";  dec_dir.mkdir()
        upl_dir  = tmp_path / "upl";  upl_dir.mkdir()
        keys_dir = tmp_path / "keys"; keys_dir.mkdir()

        (enc_dir / "a.age").write_bytes(b"x" * 1024)
        (dec_dir / "b.txt").write_bytes(b"y" * 2048)

        with patch("app.api.stats.ENCRYPTED_DIR", enc_dir), \
             patch("app.api.stats.DECRYPTED_DIR", dec_dir), \
             patch("app.api.stats.UPLOAD_DIR",    upl_dir), \
             patch("app.api.stats.Path", side_effect=lambda p: {
                 "keys": keys_dir,
                 "audit_logs": tmp_path / "audit_logs",
             }.get(p, Path(p))):

            result = _get_storage_stats()

        assert result["total_size_bytes"] >= 3072  # 1024 + 2048
        assert result["total_size_mb"] >= 0

    def test_nonexistent_dirs_count_as_zero(self, tmp_path):
        from app.api.stats import _get_storage_stats_sync as _get_storage_stats

        missing = tmp_path / "no_such_dir"

        with patch("app.api.stats.ENCRYPTED_DIR", missing), \
             patch("app.api.stats.DECRYPTED_DIR", missing), \
             patch("app.api.stats.UPLOAD_DIR",    missing), \
             patch("app.api.stats.Path", return_value=missing):

            result = _get_storage_stats()

        assert result["total_size_bytes"] == 0

    def test_directory_names_present(self):
        from app.api.stats import _get_storage_stats_sync as _get_storage_stats

        result = _get_storage_stats()

        expected = {"encrypted", "decrypted", "uploads", "keys", "audit_logs"}
        assert expected.issubset(result["directories"].keys())


# ============================================================================
# ТЕСТЫ _get_files_stats
# ============================================================================

class TestGetFilesStats:
    """Тесты для _get_files_stats."""

    def _make_mock_file(self, name: str, size: int = 1024, mtime_offset: int = 86400):
        f = Mock()
        f.is_file.return_value  = True
        f.name                  = name
        s = Mock()
        s.st_size               = size
        s.st_mtime              = time.time() - mtime_offset
        f.stat.return_value     = s
        return f

    def test_encrypted_dir_not_exists(self, tmp_path):
        from app.api.stats import _get_files_stats_sync as _get_files_stats

        missing = tmp_path / "missing"

        with patch("app.api.stats.ENCRYPTED_DIR", missing), \
             patch("app.api.stats.file_storage") as mock_storage:
            mock_storage.get_stats.return_value = {}
            result = _get_files_stats()

        assert result["encrypted"]["count"] == 0
        assert result["encrypted"]["total_size_bytes"] == 0

    def test_counts_encrypted_files(self, tmp_path):
        from app.api.stats import _get_files_stats_sync as _get_files_stats

        enc_dir = tmp_path / "enc"; enc_dir.mkdir()
        (enc_dir / "a.age").write_bytes(b"A" * 100)
        (enc_dir / "b.age").write_bytes(b"B" * 200)

        with patch("app.api.stats.ENCRYPTED_DIR", enc_dir), \
             patch("app.api.stats.file_storage") as mock_storage:
            mock_storage.get_stats.return_value = {}
            result = _get_files_stats()

        assert result["encrypted"]["count"] == 2
        assert result["encrypted"]["total_size_bytes"] == 300

    def test_skips_non_files(self, tmp_path):
        from app.api.stats import _get_files_stats_sync as _get_files_stats

        enc_dir = tmp_path / "enc"; enc_dir.mkdir()
        subdir = enc_dir / "subdir"; subdir.mkdir()
        (enc_dir / "real.age").write_bytes(b"x" * 50)

        with patch("app.api.stats.ENCRYPTED_DIR", enc_dir), \
             patch("app.api.stats.file_storage") as mock_storage:
            mock_storage.get_stats.return_value = {}
            result = _get_files_stats()

        # Директории не считаются
        assert result["encrypted"]["count"] == 1

    def test_files_in_recent_list(self, tmp_path):
        """Последние 10 файлов в списке."""
        from app.api.stats import _get_files_stats_sync as _get_files_stats

        enc_dir = tmp_path / "enc"; enc_dir.mkdir()
        for i in range(15):
            (enc_dir / f"file{i:02d}.age").write_bytes(b"x")

        with patch("app.api.stats.ENCRYPTED_DIR", enc_dir), \
             patch("app.api.stats.file_storage") as mock_storage:
            mock_storage.get_stats.return_value = {}
            result = _get_files_stats()

        assert result["encrypted"]["count"] == 15
        # Список файлов ограничен 10-ю последними
        assert len(result["encrypted"]["files"]) <= 10

    def test_stat_exception_skips_file(self):
        from app.api.stats import _get_files_stats_sync as _get_files_stats

        mock_enc_dir = Mock(spec=Path)
        mock_enc_dir.exists.return_value = True

        bad_file = Mock()
        bad_file.is_file.return_value = True
        bad_file.stat.side_effect     = OSError("no access")

        good_file = Mock()
        good_file.is_file.return_value = True
        s = Mock(); s.st_size = 512; s.st_mtime = time.time()
        good_file.stat.return_value  = s
        good_file.name               = "good.age"

        mock_enc_dir.iterdir.return_value = [bad_file, good_file]

        with patch("app.api.stats.ENCRYPTED_DIR", mock_enc_dir), \
             patch("app.api.stats.file_storage") as mock_storage:
            mock_storage.get_stats.return_value = {}
            result = _get_files_stats()

        assert result["encrypted"]["count"] == 1
        assert result["encrypted"]["total_size_bytes"] == 512

    def test_temporary_stats_included(self, tmp_path):
        from app.api.stats import _get_files_stats_sync as _get_files_stats

        enc_dir = tmp_path / "enc"; enc_dir.mkdir()

        with patch("app.api.stats.ENCRYPTED_DIR", enc_dir), \
             patch("app.api.stats.file_storage") as mock_storage:
            mock_storage.get_stats.return_value = {"temp_count": 7}
            result = _get_files_stats()

        assert result["temporary"] == {"temp_count": 7}

    def test_file_storage_no_get_stats(self, tmp_path):
        """Если у file_storage нет get_stats — возвращаем {}."""
        from app.api.stats import _get_files_stats_sync as _get_files_stats

        enc_dir = tmp_path / "enc"; enc_dir.mkdir()

        with patch("app.api.stats.ENCRYPTED_DIR", enc_dir), \
             patch("app.api.stats.file_storage", Mock(spec=[])):  # нет методов
            result = _get_files_stats()

        assert result["temporary"] == {}


# ============================================================================
# ТЕСТЫ _get_cleanup_stats
# ============================================================================

class TestGetCleanupStats:
    """Тесты для _get_cleanup_stats."""

    def test_returns_dict(self):
        import asyncio
        from app.api.stats import _get_cleanup_stats

        result = asyncio.run(_get_cleanup_stats())

        assert isinstance(result, dict)

    def test_includes_cleanup_manager_stats(self):
        import asyncio
        from app.api.stats import _get_cleanup_stats

        with patch("app.api.stats.cleanup_manager") as mock_cm:
            mock_cm.get_cleanup_stats.return_value = {"cleaned": 5}
            with patch("app.api.stats.file_storage") as mock_fs:
                mock_fs.get_stats.return_value = {}
                result = asyncio.run(_get_cleanup_stats())

        assert result["cleanup_manager"] == {"cleaned": 5}

    def test_includes_temporary_files_stats(self):
        import asyncio
        from app.api.stats import _get_cleanup_stats

        with patch("app.api.stats.cleanup_manager") as mock_cm:
            mock_cm.get_cleanup_stats.return_value = {}
            with patch("app.api.stats.file_storage") as mock_fs:
                mock_fs.get_stats.return_value = {"total": 3}
                result = asyncio.run(_get_cleanup_stats())

        assert result["temporary_files"] == {"total": 3}

    def test_cleanup_manager_no_method_returns_empty(self):
        import asyncio
        from app.api.stats import _get_cleanup_stats

        # Объект без get_cleanup_stats
        cm_mock = Mock(spec=[])  # пустой spec — нет атрибутов
        fs_mock = Mock(spec=[])

        with patch("app.api.stats.cleanup_manager", cm_mock), \
             patch("app.api.stats.file_storage",    fs_mock):
            result = asyncio.run(_get_cleanup_stats())

        assert result["cleanup_manager"] == {}
        assert result["temporary_files"] == {}

    def test_exception_returns_error_dict(self):
        import asyncio
        from app.api.stats import _get_cleanup_stats

        with patch("app.api.stats.cleanup_manager") as mock_cm:
            mock_cm.get_cleanup_stats.side_effect = RuntimeError("boom")
            result = asyncio.run(_get_cleanup_stats())

        assert "error" in result
        assert "boom" in result["error"]


# ============================================================================
# ТЕСТЫ HTTP ЭНДПОИНТОВ
# ============================================================================

class TestStatsEndpoint:
    """Тесты для GET /stats."""

    def test_returns_200_for_admin(self, stats_client):
        response = stats_client.get("/api/stats")
        assert response.status_code == 200

    def test_response_has_required_top_level_keys(self, stats_client):
        response = stats_client.get("/api/stats")
        data = response.json()

        for key in ("timestamp", "system", "storage", "files", "cleanup", "summary"):
            assert key in data, f"Отсутствует ключ: {key}"

    def test_summary_has_required_keys(self, stats_client):
        response = stats_client.get("/api/stats")
        summary = response.json()["summary"]

        assert "total_files" in summary
        assert "total_size_mb" in summary
        assert "health" in summary

    def test_health_is_string(self, stats_client):
        response = stats_client.get("/api/stats")
        assert isinstance(response.json()["summary"]["health"], str)

    def test_timestamp_is_present(self, stats_client):
        response = stats_client.get("/api/stats")
        data = response.json()
        assert data["timestamp"]  # не пустой

    def test_unauthenticated_returns_401_or_403(self, stats_client_no_auth):
        response = stats_client_no_auth.get("/api/stats")
        assert response.status_code in (401, 403)

    def test_internal_error_returns_500(self, stats_client):
        with patch("app.api.stats._get_system_stats", side_effect=Exception("boom")):
            response = stats_client.get("/api/stats")

        assert response.status_code == 500
        assert "detail" in response.json()

    def test_500_detail_contains_error_message(self, stats_client):
        with patch("app.api.stats._get_system_stats", side_effect=Exception("unique_err_xyz")):
            response = stats_client.get("/api/stats")

        assert "unique_err_xyz" in response.json()["detail"]

    def test_audit_logger_called_on_success(self, stats_client):
        with patch("app.api.stats.audit_logger") as mock_log:
            stats_client.get("/api/stats")
            mock_log.log_operation.assert_called_once()
            call_kwargs = mock_log.log_operation.call_args
            assert call_kwargs.kwargs.get("success") is True \
                   or call_kwargs[1].get("success") is True \
                   or (call_kwargs[0] and True in call_kwargs[0])

    def test_audit_logger_called_on_failure(self, stats_client):
        with patch("app.api.stats._get_system_stats", side_effect=Exception("fail")), \
             patch("app.api.stats.audit_logger") as mock_log:
            stats_client.get("/api/stats")
            mock_log.log_operation.assert_called_once()


class TestStatsSummaryEndpoint:
    """Тесты для GET /stats/summary."""

    def test_returns_200_for_admin(self, stats_client):
        response = stats_client.get("/api/stats/summary")
        assert response.status_code == 200

    def test_response_has_required_keys(self, stats_client):
        response = stats_client.get("/api/stats/summary")
        data = response.json()

        for key in ("timestamp", "total_files", "total_size_mb", "health"):
            assert key in data, f"Отсутствует ключ: {key}"

    def test_total_files_is_integer(self, stats_client):
        response = stats_client.get("/api/stats/summary")
        assert isinstance(response.json()["total_files"], int)

    def test_total_size_mb_is_number(self, stats_client):
        response = stats_client.get("/api/stats/summary")
        val = response.json()["total_size_mb"]
        assert isinstance(val, (int, float))

    def test_unauthenticated_returns_401_or_403(self, stats_client_no_auth):
        response = stats_client_no_auth.get("/api/stats/summary")
        assert response.status_code in (401, 403)

    def test_summary_delegates_to_get_system_stats(self, stats_client):
        """
        /stats/summary вызывает get_system_stats внутри.
        Проверяем, что ошибка наверху → 500 в summary тоже.
        """
        with patch("app.api.stats._get_system_stats", side_effect=Exception("cascade")):
            response = stats_client.get("/api/stats/summary")

        assert response.status_code == 500

    def test_health_value_is_healthy_or_degraded(self, stats_client):
        response = stats_client.get("/api/stats/summary")
        assert response.json()["health"] in ("healthy", "degraded", "unhealthy")


# ============================================================================
# ИНТЕГРАЦИОННЫЕ ТЕСТЫ (реальная файловая система)
# ============================================================================

class TestIntegration:
    """Интеграционные тесты с реальными файлами."""

    @pytest.mark.integration
    def test_full_stats_with_real_temp_dirs(self, tmp_path, stats_client):
        enc  = tmp_path / "enc";  enc.mkdir()
        dec  = tmp_path / "dec";  dec.mkdir()
        upl  = tmp_path / "upl";  upl.mkdir()
        keys = tmp_path / "keys"; keys.mkdir()

        (enc / "a.age").write_bytes(b"x" * 500)
        (enc / "b.age").write_bytes(b"y" * 300)

        with patch("app.api.stats.ENCRYPTED_DIR", enc), \
             patch("app.api.stats.DECRYPTED_DIR", dec), \
             patch("app.api.stats.UPLOAD_DIR",    upl), \
             patch("app.api.stats.Path", side_effect=lambda p: {
                 "keys": keys,
                 "audit_logs": tmp_path / "audit_logs",
             }.get(p, Path(p))):

            response = stats_client.get("/api/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["files"]["encrypted"]["count"] == 2

    @pytest.mark.integration
    def test_safe_directory_stats_with_nested_structure(self, tmp_path):
        from app.api.stats import _safe_directory_stats

        root = tmp_path / "root"; root.mkdir()
        l1   = root / "l1";      l1.mkdir()
        l2   = l1   / "l2";      l2.mkdir()

        (root / "f1.txt").write_bytes(b"a" * 100)
        (l1   / "f2.txt").write_bytes(b"b" * 200)
        (l2   / "f3.txt").write_bytes(b"c" * 300)

        result = _safe_directory_stats(root)

        assert result["file_count"] == 3
        assert result["size_bytes"] == 600

    @pytest.mark.integration
    def test_get_files_stats_with_mixed_extensions(self, tmp_path):
        from app.api.stats import _get_files_stats_sync as _get_files_stats

        enc = tmp_path / "enc"; enc.mkdir()
        files = [
            ("doc.txt",  100),
            ("img.jpg",  200),
            ("rep.pdf",  300),
            ("data.age", 400),
            ("noext",    500),
        ]
        for name, size in files:
            (enc / name).write_bytes(b"x" * size)

        with patch("app.api.stats.ENCRYPTED_DIR", enc), \
             patch("app.api.stats.file_storage") as mock_fs:
            mock_fs.get_stats.return_value = {}
            result = _get_files_stats()

        assert result["encrypted"]["count"] == 5
        assert result["encrypted"]["total_size_bytes"] == 1500


# ============================================================================
# ПАРАМЕТРИЗОВАННЫЕ ТЕСТЫ
# ============================================================================

@pytest.mark.parametrize("side_effect,expected_key", [
    (Exception("generic"),       "status"),
    (OSError("os error"),        "status"),
    (RuntimeError("runtime"),    "status"),
])
def test_system_stats_various_cpu_errors(side_effect, expected_key):
    """Любая ошибка psutil.cpu_percent → {"status": "unavailable_in_container"}."""
    from app.api.stats import _get_system_stats

    with patch("psutil.cpu_percent", side_effect=side_effect), \
         patch("psutil.cpu_count",   side_effect=side_effect):
        result = _get_system_stats()

    assert expected_key in result["cpu"]


@pytest.mark.parametrize("file_size", [0, 1, 1024, 1024 * 1024, 100 * 1024 * 1024])
def test_safe_directory_stats_various_file_sizes(tmp_path, file_size):
    """_safe_directory_stats корректно считает файлы разных размеров."""
    from app.api.stats import _safe_directory_stats

    d = tmp_path / "dir"; d.mkdir()
    (d / "file.bin").write_bytes(b"x" * file_size)

    result = _safe_directory_stats(d)

    assert result["size_bytes"] == file_size
    assert result["file_count"] == 1


@pytest.mark.parametrize("endpoint", ["/api/stats", "/api/stats/summary"])
def test_endpoints_require_authentication(endpoint, stats_client_no_auth):
    """Все stats-эндпоинты требуют аутентификации."""
    response = stats_client_no_auth.get(endpoint)
    assert response.status_code in (401, 403)


@pytest.mark.parametrize("error_class", [Exception, RuntimeError, ValueError, OSError])
def test_get_cleanup_stats_handles_various_exceptions(error_class):
    """_get_cleanup_stats перехватывает любые исключения."""
    import asyncio
    from app.api.stats import _get_cleanup_stats

    with patch("app.api.stats.cleanup_manager") as mock_cm:
        mock_cm.get_cleanup_stats.side_effect = error_class("test error")
        result = asyncio.run(_get_cleanup_stats())

    assert "error" in result
    assert isinstance(result["error"], str)
