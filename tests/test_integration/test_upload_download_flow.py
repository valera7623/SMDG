# tests/test_integration/test_upload_download_flow.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import json

@pytest.mark.integration
@pytest.mark.asyncio
@patch("app.api.upload.magic.Magic")
@patch("app.api.upload.crypto_manager")
@patch("app.api.upload.get_current_user")
async def test_full_upload_download_flow(
    mock_get_user, mock_crypto, mock_magic, 
    client, tmp_path, mock_audit
):
    """Полный тест: загрузка → получение ссылки → скачивание"""
    # --- ШАГ 1: Загрузка файла ---
    
    # Настраиваем моки для загрузки
    mock_get_user.return_value = MagicMock(sub="testuser", role="user")
    mock_crypto.encrypt_file = AsyncMock(return_value="encrypted_hash_123")
    
    magic_instance = MagicMock()
    magic_instance.from_buffer.return_value = "application/pdf"
    mock_magic.return_value = magic_instance
    
    # Мокаем ClamAV
    with patch("app.api.upload.clamd.ClamdNetworkSocket") as mock_clamd:
        clam_instance = MagicMock()
        clam_instance.ping.return_value = "PONG"
        clam_instance.instream.return_value = ("OK", None)
        mock_clamd.return_value = clam_instance
    
    # Создаем тестовый файл
    test_file = tmp_path / "document.pdf"
    test_file.write_bytes(b"PDF test content " * 100)
    
    # Выполняем загрузку
    upload_response = client.post(
        "/api/upload",
        files={"file": ("document.pdf", test_file.open('rb'), "application/pdf")},
        data={"ttl_days": "1", "max_downloads": "2"}
    )
    
    assert upload_response.status_code == 200
    upload_data = upload_response.json()
    
    # Проверяем ответ загрузки
    assert upload_data["message"] == "Файл успешно загружен и зашифрован"
    assert upload_data["original_name"] == "document.pdf"
    assert upload_data["max_downloads"] == 2
    assert "download_url" in upload_data
    
    # Извлекаем токен из URL
    download_url = upload_data["download_url"]
    # URL вида: http://testserver/api/download?token=uuid
    import urllib.parse
    parsed = urllib.parse.urlparse(download_url)
    query_params = urllib.parse.parse_qs(parsed.query)
    token = query_params.get("token", [None])[0]
    
    assert token is not None
    
    # --- ШАГ 2: Скачивание по токену ---
    
    # Настраиваем моки для скачивания
    mock_file_link = MagicMock(
        token=token,
        file_id=1,
        downloads_count=0,
        max_downloads=2,
        expires_at=MagicMock()  # Будущая дата
    )
    mock_file_link.expires_at.__gt__.return_value = True
    
    mock_file_data = MagicMock(
        id=1,
        original_name="document.pdf",
        encrypted_path=str(tmp_path / "encrypted_document.pdf.age"),
        user_id=1
    )
    
    # Мокаем криптографию для скачивания
    with patch("app.api.download.crypto_manager") as mock_download_crypto:
        mock_download_crypto.decrypt_file = AsyncMock()
        
        # Мокаем БД для скачивания
        with patch("app.api.download.select") as mock_select:
            mock_scalar = MagicMock()
            mock_scalar.scalar_one_or_none.side_effect = [mock_file_link, mock_file_data]
            mock_select.return_value.scalar_one_or_none = mock_scalar
            
            # Выполняем скачивание
            download_response = client.get(f"/api/download?token={token}")
            
            # Проверяем успешное скачивание
            assert download_response.status_code == 200
            
            # Проверяем увеличение счетчика
            assert mock_file_link.downloads_count == 1
    
    # --- ШАГ 3: Повторное скачивание (до лимита) ---
    
    with patch("app.api.download.crypto_manager") as mock_download_crypto:
        mock_download_crypto.decrypt_file = AsyncMock()
        
        with patch("app.api.download.select") as mock_select:
            mock_scalar = MagicMock()
            # Теперь downloads_count = 1
            mock_file_link.downloads_count = 1
            mock_scalar.scalar_one_or_none.side_effect = [mock_file_link, mock_file_data]
            mock_select.return_value.scalar_one_or_none = mock_scalar
            
            # Второе скачивание
            second_download = client.get(f"/api/download?token={token}")
            assert second_download.status_code == 200
            assert mock_file_link.downloads_count == 2
    
    # --- ШАГ 4: Попытка скачать после исчерпания лимита ---
    
    with patch("app.api.download.select") as mock_select:
        # Теперь downloads_count = 2, max_downloads = 2
        mock_file_link.downloads_count = 2
        mock_select.return_value.scalar_one_or_none.return_value = mock_file_link
        
        third_download = client.get(f"/api/download?token={token}")
        assert third_download.status_code == 410
        assert "лимит" in third_download.json()["detail"].lower()