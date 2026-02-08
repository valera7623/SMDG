# app/models/user.py - обновлённая версия
from sqlalchemy import String, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    username: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    hashed_password: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(30), nullable=False, default="user"
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    otp_secret: Mapped[str] = mapped_column(
        Text, nullable=True, default=None  # Новое поле для хранения OTP секрета
    )

    # Раскомментировать и использовать string для File (без импорта класса File)
    #files = relationship("File", back_populates="user")

    def __repr__(self):
        return f"<User {self.username} ({self.role})>"