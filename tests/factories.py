# tests/factories.py - обновляем FileFactory
import uuid
from datetime import datetime, timezone, timedelta
import factory
from factory import Faker, LazyFunction, LazyAttribute, post_generation
from factory.alchemy import SQLAlchemyModelFactory

from app.models.user import User
from app.models.file import File
from app.models.file_link import FileLink
from app.core.security import get_password_hash


class AsyncSQLAlchemyModelFactory(SQLAlchemyModelFactory):
    """Базовый класс для асинхронных фабрик"""
    
    @classmethod
    async def create_async(cls, **kwargs):
        """Асинхронное создание объекта"""
        obj = cls.build(**kwargs)
        session = cls._meta.sqlalchemy_session
        session.add(obj)
        await session.commit()
        await session.refresh(obj)
        return obj
    
    @classmethod
    async def create_batch_async(cls, size, **kwargs):
        """Асинхронное создание нескольких объектов"""
        objs = [cls.build(**kwargs) for _ in range(size)]
        session = cls._meta.sqlalchemy_session
        session.add_all(objs)
        await session.commit()
        for obj in objs:
            await session.refresh(obj)
        return objs


class UserFactory(AsyncSQLAlchemyModelFactory):
    """Фабрика для создания пользователей"""
    
    class Meta:
        model = User
        sqlalchemy_session = None
        sqlalchemy_session_persistence = "flush"
    
    username = LazyAttribute(lambda obj: f"user_{uuid.uuid4().hex[:8]}")
    email = LazyAttribute(lambda obj: f"{obj.username}@example.com")
    hashed_password = LazyFunction(lambda: get_password_hash("testpass123"))
    role = "user"
    is_active = True
    otp_secret = None
    
    class Params:
        doctor = factory.Trait(role="doctor")
        admin = factory.Trait(
            role="admin",
            username="admin",
            email="admin@example.com"
        )
        inactive = factory.Trait(is_active=False)
        with_otp = factory.Trait(
            otp_secret=LazyFunction(lambda: uuid.uuid4().hex)
        )
    
    @post_generation
    def set_password(self, create, extracted, **kwargs):
        if extracted:
            self.hashed_password = get_password_hash(extracted)


class FileFactory(AsyncSQLAlchemyModelFactory):
    """Фабрика для создания файлов"""
    
    class Meta:
        model = File
        sqlalchemy_session = None
        sqlalchemy_session_persistence = "flush"
    
    # id - автоинкремент
    user_id = None  # может быть None
    original_name = Faker("file_name", extension="pdf")
    encrypted_name = LazyAttribute(lambda obj: f"{uuid.uuid4().hex}.enc")
    encrypted_path = LazyAttribute(lambda obj: f"/tmp/uploads/{obj.encrypted_name}")
    original_size = Faker("random_int", min=1000, max=10_000_000)
    encrypted_size = LazyAttribute(lambda obj: int(obj.original_size * 1.1))  # чуть больше
    original_hash = Faker("sha256")
    mime_type = "application/pdf"
    patient_id = None
    medical_metadata = {}
    uploaded_at = LazyFunction(lambda: datetime.now(timezone.utc))
    expires_at = LazyFunction(lambda: datetime.now(timezone.utc) + timedelta(days=7))
    
    class Params:
        expired = factory.Trait(
            expires_at=LazyFunction(lambda: datetime.now(timezone.utc) - timedelta(days=1))
        )
        with_patient = factory.Trait(
            patient_id=LazyFunction(lambda: f"PAT-{uuid.uuid4().hex[:8].upper()}")
        )
        with_metadata = factory.Trait(
            medical_metadata={
                "diagnosis": "Test diagnosis",
                "doctor": "Dr. Smith",
                "date": datetime.now(timezone.utc).isoformat()
            }
        )
        image = factory.Trait(
            original_name=Faker("file_name", extension="jpg"),
            mime_type="image/jpeg"
        )
    
    @post_generation
    def with_uploader(self, create, extracted, **kwargs):
        """Связываем файл с конкретным пользователем"""
        if extracted:
            self.user_id = extracted.id


class FileLinkFactory(AsyncSQLAlchemyModelFactory):
    """Фабрика для создания ссылок на файлы"""
    
    class Meta:
        model = FileLink
        sqlalchemy_session = None
        sqlalchemy_session_persistence = "flush"
    
    # id - автоинкремент
    token = LazyFunction(lambda: str(uuid.uuid4()))
    file_id = LazyFunction(lambda: 0)
    max_downloads = 1
    downloads_count = 0
    expires_at = None
    
    class Params:
        expired = factory.Trait(
            expires_at=LazyFunction(lambda: datetime.now(timezone.utc) - timedelta(days=1))
        )
        with_limit = factory.Trait(
            max_downloads=5
        )
        used_up = factory.Trait(
            downloads_count=5,
            max_downloads=5
        )
    
    @post_generation
    def for_file(self, create, extracted, **kwargs):
        """Связываем ссылку с конкретным файлом"""
        if extracted:
            self.file_id = extracted.id