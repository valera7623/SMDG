# tests/test_api/test_cleanup.py
"""
Тесты для /api/cleanup/*
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from pathlib import Path

from app.main import app
from app.api.cleanup import get_cleanup_stats, force_cleanup, list_temp_files
from app.core import file_storage, audit_logger
from app.core.auth import get_current_admin
import app.core.constants as core_constants  # ← ключевой импорт


@pytest.fixture
def mock_admin():
    user = MagicMock()
    user.sub = "admin_test"
    user.role = "admin"
    return user


def test_get_cleanup_stats_success(client, mock_admin):
    app.dependency_overrides[get_current_admin] = lambda: mock_admin

    mock_stats = {"total_files": 3, "ttl_seconds": 3600}

    with patch.object(file_storage, "get_stats", return_value=mock_stats):
        with patch.object(audit_logger, "log_operation") as mock_log:
            response = client.get("/api/cleanup/stats")

            assert response.status_code == 200
            assert response.json() == mock_stats

            mock_log.assert_any_call(
                action="cleanup_stats_viewed",
                filename="",
                user="admin_test",
                reason="Просмотр статистики временных файлов",
                success=True
            )

    app.dependency_overrides.clear()


def test_force_cleanup_success(client, mock_admin):
    app.dependency_overrides[get_current_admin] = lambda: mock_admin

    mock_result = {"deleted": 5}

    with patch.object(file_storage, "force_cleanup", return_value=mock_result):
        with patch.object(audit_logger, "log_operation") as mock_log:
            response = client.post("/api/cleanup/force")

            assert response.status_code == 200
            assert response.json() == mock_result

            mock_log.assert_any_call(
                action="cleanup_force",
                filename="",
                user="admin_test",
                reason="Принудительная очистка временных файлов",
                success=True,
                metadata={"deleted_count": 0}
            )

    app.dependency_overrides.clear()


def test_list_temp_files_success(client, mock_admin, temp_dirs):
    app.dependency_overrides[get_current_admin] = lambda: mock_admin

    decrypted = temp_dirs["decrypted"]
    (decrypted / "file1.txt").write_text("data")
    (decrypted / "file2.txt").write_text("data2")

    # Патчим DECRYPTED_DIR внутри модуля cleanup (где он импортирован)
    with patch("app.api.cleanup.DECRYPTED_DIR", decrypted):
        with patch.object(audit_logger, "log_operation") as mock_log:
            response = client.get("/api/cleanup/files?limit=10")

            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 2, f"Count {data['count']}, files {data.get('files')}"
            assert len(data["files"]) == 2

            mock_log.assert_any_call(
                action="cleanup_files_listed",
                filename="",
                user="admin_test",
                reason="Просмотр списка временных файлов (limit=10)",
                success=True,
                metadata={"count_returned": 2}
            )

    app.dependency_overrides.clear()


def test_list_temp_files_no_dir(client, mock_admin):
    app.dependency_overrides[get_current_admin] = lambda: mock_admin

    # Патчим метод exists на уровне класса Path
    with patch("pathlib.Path.exists", return_value=False):
        response = client.get("/api/cleanup/files")

        assert response.status_code == 200
        assert response.json()["count"] == 0

    app.dependency_overrides.clear()


def test_list_temp_files_limit(client, mock_admin, temp_dirs):
    app.dependency_overrides[get_current_admin] = lambda: mock_admin

    decrypted = temp_dirs["decrypted"]
    for i in range(5):
        (decrypted / f"f{i}.txt").write_text("x")

    with patch("app.api.cleanup.DECRYPTED_DIR", decrypted):
        response = client.get("/api/cleanup/files?limit=3")

        assert response.status_code == 200
        assert len(response.json()["files"]) == 3

    app.dependency_overrides.clear()


# Unit-тесты

@pytest.mark.asyncio
async def test_list_temp_files_direct(mock_admin, temp_dirs):
    decrypted = temp_dirs["decrypted"]

    # Очищаем директорию перед тестом (удаляем все файлы)
    for item in decrypted.iterdir():
        if item.is_file():
            item.unlink()

    (decrypted / "test.txt").write_text("data")

    with patch("app.api.cleanup.DECRYPTED_DIR", decrypted):
        result = await list_temp_files(current_user=mock_admin, limit=10)
        assert result["count"] == 1, f"Found {result['count']} files: {result.get('files')}"


@pytest.mark.asyncio
async def test_list_temp_files_limit_direct(mock_admin, temp_dirs):
    decrypted = temp_dirs["decrypted"]

    # Очищаем директорию перед тестом
    for item in decrypted.iterdir():
        if item.is_file():
            item.unlink()

    for i in range(5):
        (decrypted / f"f{i}.txt").write_text("x")

    with patch("app.api.cleanup.DECRYPTED_DIR", decrypted):
        result = await list_temp_files(current_user=mock_admin, limit=2)
        assert result["count"] == 2, f"Found {result['count']} files: {result.get('files')}"



def test_get_cleanup_stats_unauthorized(client):
    response = client.get("/api/cleanup/stats")
    assert response.status_code in (401, 403)


def test_force_cleanup_unauthorized(client):
    response = client.post("/api/cleanup/force")
    assert response.status_code in (401, 403)