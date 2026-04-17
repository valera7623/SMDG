# app/models/user.py
from sqlalchemy import String, Integer, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

class User(Base):
    __tablename__ = 'users'
    __table_args__ = {'extend_existing': True}
    
    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    username: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    hashed_password: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(30), nullable=False, default='user'
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    otp_secret: Mapped[str] = mapped_column(
        Text, nullable=True, default=None
    )
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id"), nullable=False, index=True, default=1
    )

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'
