# tests/test_models/test_user.py
import pytest
from tests.factories import UserFactory
from sqlalchemy.exc import IntegrityError


@pytest.mark.asyncio
async def test_create_user(db_session):
    """Тест создания обычного пользователя"""
    user = await UserFactory.create_async()
    
    assert user.id is not None
    assert isinstance(user.id, int)
    assert user.role == "user"
    assert user.is_active is True


@pytest.mark.asyncio
async def test_create_doctor(db_session):
    """Тест создания врача"""
    doctor = await UserFactory.create_async(doctor=True)
    assert doctor.role == "doctor"


@pytest.mark.asyncio
async def test_create_admin_user(db_session):
    """Тест создания администратора"""
    admin = await UserFactory.create_async(admin=True)
    assert admin.role == "admin"
    assert admin.username == "admin"


@pytest.mark.asyncio
async def test_create_user_with_custom_password(db_session):
    """Тест создания пользователя с кастомным паролем"""
    user = await UserFactory.create_async(
        email="test@example.com",
        username="testuser",
        set_password="mysecurepass123"
    )
    
    from app.core.security import verify_password
    assert verify_password("mysecurepass123", user.hashed_password) is True


@pytest.mark.asyncio
async def test_create_batch_users(db_session):
    """Тест создания нескольких пользователей"""
    users = await UserFactory.create_batch_async(3, doctor=True)
    assert len(users) == 3
    assert all(u.role == "doctor" for u in users)


@pytest.mark.asyncio
async def test_user_unique_constraints(db_session):
    """Тест уникальности email и username"""
    await UserFactory.create_async(email="unique@example.com", username="unique")
    
    with pytest.raises(IntegrityError):
        await UserFactory.create_async(email="unique@example.com", username="another")
    
    await db_session.rollback()
    
    with pytest.raises(IntegrityError):
        await UserFactory.create_async(email="another@example.com", username="unique")