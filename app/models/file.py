# app/models/file.py
from sqlalchemy import String, Integer, ForeignKey, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
from typing import Optional
from app.core.database import Base

class File(Base):
    __tablename__ = "files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Кто загрузил файл (опционально, если нужна привязка к пользователю)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Раскомментировать relationship и использовать string для User (без импорта класса User)
    #user = relationship("User", back_populates="files")

    # Оригинальное имя файла (как было у пользователя)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # Имя зашифрованного файла на диске
    encrypted_name: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # Путь к зашифрованному файлу
    encrypted_path: Mapped[str] = mapped_column(String(512), nullable=False)
    
    # Размер оригинального файла
    original_size: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Размер зашифрованного файла
    encrypted_size: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Хэш оригинального файла (для проверки целостности)
    original_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    
    # MIME-тип оригинального файла
    mime_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # Когда файл был загружен
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default="CURRENT_TIMESTAMP")
    
    # Когда файл будет автоматически удалён (если используешь TTL)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Связи с одноразовыми ссылками
    links = relationship("FileLink", back_populates="file", cascade="all, delete-orphan")
    
    #files = relationship("File", back_populates="file")

    def __repr__(self):
        return f"<File id={self.id} original_name={self.original_name} encrypted_name={self.encrypted_name}>"