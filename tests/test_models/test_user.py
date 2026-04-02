# tests/test_models/test_user.py
import pytest
from tests.factories import UserFactory
from sqlalchemy.exc import IntegrityError
import uuid


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
    # Генерируем уникальный суффикс чтобы избежать UniqueViolationError
    # если тест запускается несколько раз или БД не очищается между тестами
    unique_suffix = uuid.uuid4().hex[:8]

    admin = await UserFactory.create_async(
        admin=True,
        username=f"admin_{unique_suffix}",
        email=f"admin_{unique_suffix}@example.com",
    )

    assert admin.role == "admin"
    # Проверяем роль, а не конкретный username — он уникален, но не фиксирован
    assert admin.is_active is True


@pytest.mark.asyncio
async def test_create_user_with_custom_password(db_session):
    """Тест создания пользователя с кастомным паролем"""
    unique_suffix = uuid.uuid4().hex[:8]

    user = await UserFactory.create_async(
        email=f"test_{unique_suffix}@example.com",
        username=f"testuser_{unique_suffix}",
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
    unique_suffix = uuid.uuid4().hex[:8]
    email = f"unique_{unique_suffix}@example.com"
    username = f"unique_{unique_suffix}"

    await UserFactory.create_async(email=email, username=username)

    # Дублируем email — должен быть IntegrityError
    with pytest.raises(IntegrityError):
        await UserFactory.create_async(
            email=email,
            username=f"another_{unique_suffix}"
        )

    await db_session.rollback()

    # Дублируем username — должен быть IntegrityError
    with pytest.raises(IntegrityError):
        await UserFactory.create_async(
            email=f"another_{unique_suffix}@example.com",
            username=username
        )
