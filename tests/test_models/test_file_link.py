# tests/test_models/test_file_link.py
import pytest
import sys
from pathlib import Path
import uuid

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

def test_file_link_model():
    """Тест модели FileLink"""
    from app.models.file_link import FileLink
    from datetime import datetime
    
    test_uuid = str(uuid.uuid4())
    expires_at = datetime.now()
    
    file_link = FileLink(
        token=test_uuid,
        file_id=1,
        max_downloads=5,
        downloads_count=0,
        expires_at=expires_at
    )
    
    assert file_link.token == test_uuid
    assert file_link.file_id == 1
    assert file_link.max_downloads == 5
    assert file_link.downloads_count == 0
    assert file_link.expires_at == expires_at

def test_file_link_defaults():
    """Тест значений по умолчанию FileLink"""
    from app.models.file_link import FileLink
    
    file_link = FileLink(
        file_id=1
    )
    
    assert file_link.token is not None  # Должен быть сгенерирован
    assert file_link.max_downloads == 1
    assert file_link.downloads_count == 0
    assert file_link.expires_at is None

def test_file_link_repr():
    """Тест строкового представления FileLink"""
    from app.models.file_link import FileLink
    
    file_link = FileLink(
        token="test-token-123",
        file_id=1,
        downloads_count=3,
        max_downloads=5
    )
    
    repr_str = repr(file_link)
    assert "FileLink" in repr_str
    assert "test-token-123" in repr_str
    assert "file_id=1" in repr_str
    assert "downloads=3/5" in repr_str