# tests/test_models/test_file_link.py
import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.models.file_link import FileLink
from tests.factories import UserFactory, FileFactory, FileLinkFactory


@pytest.mark.asyncio
async def test_file_link_model(db_session):
    """Тест создания ссылки на файл"""
    # Создаём пользователя и файл
    user = await UserFactory.create_async()
    file = await FileFactory.create_async(with_uploader=user)
    
    # Создаём ссылку
    link = await FileLinkFactory.create_async(
        for_file=file,
        max_downloads=5,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1)
    )
    
    assert link.id is not None
    assert isinstance(link.id, int)
    assert link.file_id == file.id
    assert link.token is not None
    assert len(link.token) == 36  # UUID с дефисами
    assert link.max_downloads == 5
    assert link.downloads_count == 0
    assert link.expires_at is not None


@pytest.mark.asyncio
async def test_file_link_token_generation(db_session):
    """Тест автоматической генерации токена"""
    user = await UserFactory.create_async()
    file = await FileFactory.create_async(with_uploader=user)
    
    # Создаём две ссылки
    link1 = await FileLinkFactory.create_async(for_file=file)
    link2 = await FileLinkFactory.create_async(for_file=file)
    
    assert link1.token is not None
    assert link2.token is not None
    assert link1.token != link2.token


@pytest.mark.asyncio
async def test_file_link_default_values(db_session):
    """Тест значений по умолчанию"""
    user = await UserFactory.create_async()
    file = await FileFactory.create_async(with_uploader=user)
    
    # Создаём ссылку с минимальными данными
    link = await FileLinkFactory.create_async(for_file=file)
    
    assert link.max_downloads == 1
    assert link.downloads_count == 0
    assert link.token is not None
    assert link.expires_at is None


@pytest.mark.asyncio
async def test_file_link_repr(db_session):
    """Тест строкового представления"""
    user = await UserFactory.create_async()
    file = await FileFactory.create_async(with_uploader=user)
    
    link = await FileLinkFactory.create_async(
        for_file=file,
        max_downloads=10
    )
    
    repr_str = repr(link)
    assert "FileLink" in repr_str
    assert link.token in repr_str
    assert str(file.id) in repr_str
    assert "downloads=0/10" in repr_str


@pytest.mark.asyncio
async def test_file_link_unique_token(db_session):
    """Тест уникальности токена"""
    user = await UserFactory.create_async()
    file = await FileFactory.create_async(with_uploader=user)
    
    # Создаём первую ссылку
    link1 = await FileLinkFactory.create_async(for_file=file)
    
    # Пытаемся создать вторую с таким же токеном
    link2 = FileLinkFactory.build(for_file=file, token=link1.token)
    db_session.add(link2)
    
    with pytest.raises(IntegrityError):
        await db_session.commit()
    
    await db_session.rollback()


@pytest.mark.asyncio
async def test_file_link_expiration(db_session):
    """Тест истечения срока действия"""
    user = await UserFactory.create_async()
    file = await FileFactory.create_async(with_uploader=user)
    
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    link = await FileLinkFactory.create_async(
        for_file=file,
        expires_at=expires_at
    )
    
    assert link.expires_at is not None
    assert link.expires_at > datetime.now(timezone.utc)
    assert (link.expires_at - datetime.now(timezone.utc)).days <= 7


@pytest.mark.asyncio
async def test_file_link_no_expiration(db_session):
    """Тест ссылки без ограничения срока"""
    user = await UserFactory.create_async()
    file = await FileFactory.create_async(with_uploader=user)
    
    link = await FileLinkFactory.create_async(for_file=file, expires_at=None)
    assert link.expires_at is None


@pytest.mark.asyncio
async def test_file_link_increment_downloads(db_session):
    """Тест увеличения счётчика скачиваний"""
    user = await UserFactory.create_async()
    file = await FileFactory.create_async(with_uploader=user)
    
    link = await FileLinkFactory.create_async(
        for_file=file,
        max_downloads=5,
        downloads_count=0
    )
    
    # Увеличиваем счётчик
    link.downloads_count += 1
    await db_session.commit()
    await db_session.refresh(link)
    assert link.downloads_count == 1
    
    link.downloads_count += 1
    await db_session.commit()
    await db_session.refresh(link)
    assert link.downloads_count == 2


@pytest.mark.asyncio
async def test_file_link_max_downloads_limit(db_session):
    """Тест достижения лимита скачиваний"""
    user = await UserFactory.create_async()
    file = await FileFactory.create_async(with_uploader=user)
    
    link = await FileLinkFactory.create_async(
        for_file=file,
        max_downloads=3,
        downloads_count=3
    )
    
    assert link.downloads_count >= link.max_downloads


@pytest.mark.asyncio
async def test_file_link_multiple_links_for_file(db_session):
    """Тест множественных ссылок на один файл"""
    user = await UserFactory.create_async()
    file = await FileFactory.create_async(with_uploader=user)
    
    # Создаём несколько ссылок на один файл
    link1 = await FileLinkFactory.create_async(for_file=file, max_downloads=1)
    link2 = await FileLinkFactory.create_async(for_file=file, max_downloads=5)
    link3 = await FileLinkFactory.create_async(for_file=file, max_downloads=10)
    
    # Проверяем, что все ссылки созданы
    result = await db_session.execute(
        select(FileLink).where(FileLink.file_id == file.id)
    )
    links = result.scalars().all()
    
    assert len(links) == 3
    assert all(l.file_id == file.id for l in links)
    
    # Проверяем, что токены уникальны
    tokens = [l.token for l in links]
    assert len(set(tokens)) == 3


@pytest.mark.asyncio
async def test_file_link_relationship(db_session):
    """Тест связи с файлом"""
    user = await UserFactory.create_async()
    file = await FileFactory.create_async(with_uploader=user)
    
    link = await FileLinkFactory.create_async(for_file=file)
    await db_session.refresh(link)
    
    # Проверяем связь
    assert link.file is not None
    assert link.file.id == file.id
    assert link.file.original_name == file.original_name