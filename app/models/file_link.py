# app/models/file_link.py
from sqlalchemy import String, Integer, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
from typing import Optional
from app.core.database import Base
import uuid

class FileLink(Base):
    __tablename__ = "file_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True, default=lambda: str(uuid.uuid4()))
    file_id: Mapped[int] = mapped_column(Integer, ForeignKey("files.id"), nullable=False)
    max_downloads: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    downloads_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Связь с файлом (опционально, если нужно)
    file = relationship("File", back_populates="links")

    def __repr__(self):
        return f"<FileLink token={self.token} file_id={self.file_id} downloads={self.downloads_count}/{self.max_downloads}>"