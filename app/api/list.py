# app/api/list.py
from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional, Dict, Any
import logging
from datetime import datetime, timezone

from app.core.auth import get_current_user
from app.core.auth_utils import TokenData
from app.core.database import get_db
from app.core import ENCRYPTED_DIR, audit_logger
from app.core.rate_limiter import limiter
from app.models.file import File
from app.models.file_link import FileLink
from app.models.user import User
from pathlib import Path

router = APIRouter()
logger = logging.getLogger(__name__)


# ==================== Pydantic V2 Модели ответа ====================

class FileItem(BaseModel):
    id: int
    name: str
    size: int
    modified: str
    original_name: str
    patient_id: Optional[str] = None
    medical_metadata: Dict[str, Any] = Field(default_factory=dict)
    download_token: Optional[str] = None
    download_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class FileListResponse(BaseModel):
    count: int
    files: List[FileItem]

    model_config = ConfigDict(extra='ignore')


# ==================== Эндпоинт ====================

@router.get("/list")
@limiter.limit("10/minute")
async def list_files(
    request: Request,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> FileListResponse:
    """Получить список файлов текущего пользователя (или всех для doctor/admin)"""
    logger.info(f"📋 Запрос списка файлов от {current_user.sub} (роль: {current_user.role})")

    files: List[FileItem] = []

    # Базовый запрос
    stmt = select(File).order_by(File.uploaded_at.desc())

    # Ограничение по правам
    if current_user.role not in {"doctor", "admin"}:
        # Обычный пользователь видит только свои файлы
        user_result = await db.execute(
            select(User.id).where(User.username == current_user.sub)
        )
        user_id = user_result.scalar()

        if user_id is None:
            logger.warning(f"⚠️ Пользователь {current_user.sub} не найден в БД")
            return FileListResponse(count=0, files=[])

        stmt = stmt.where(File.user_id == user_id)

    # Выполняем запрос
    result = await db.execute(stmt)
    db_files = result.scalars().all()

    for db_file in db_files:
        file_path = ENCRYPTED_DIR / db_file.encrypted_name

        if not file_path.exists():
            logger.debug(f"Файл {db_file.encrypted_name} есть в БД, но отсутствует на диске — пропускаем")
            continue

        try:
            stat = file_path.stat()

            # Ищем активную ссылку (самую свежую)
            token_result = await db.execute(
                select(FileLink.token)
                .where(
                    FileLink.file_id == db_file.id,
                    FileLink.expires_at > datetime.now(timezone.utc),
                    FileLink.downloads_count < FileLink.max_downloads
                )
                .order_by(FileLink.expires_at.desc())
                .limit(1)
            )
            active_token = token_result.scalar()

            files.append(FileItem(
                id=db_file.id,
                name=db_file.encrypted_name,
                size=db_file.encrypted_size or stat.st_size,
                modified=db_file.uploaded_at.isoformat(),
                original_name=db_file.original_name,
                patient_id=db_file.patient_id,
                medical_metadata=db_file.medical_metadata or {},
                download_token=active_token,
                download_url=f"/api/download?token={active_token}" if active_token else None
            ))

        except Exception as e:
            logger.error(f"Ошибка обработки файла {db_file.encrypted_name}: {e}")
            audit_logger.log_operation(
                action="list_error",
                filename=db_file.encrypted_name,
                user=current_user.sub,
                reason=str(e),
                success=False
            )

    logger.info(f"📋 Найдено {len(files)} файлов для пользователя {current_user.sub}")

    # Аудит успешного запроса
    audit_logger.log_operation(
        action="list_files",
        filename="",
        user=current_user.sub,
        reason=f"Просмотр списка файлов ({len(files)} шт.)",
        success=True,
        metadata={"count": len(files), "role": current_user.role}
    )

    return FileListResponse(count=len(files), files=files)