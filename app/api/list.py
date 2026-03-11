# app/api/list.py
from fastapi import APIRouter, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.auth_utils import TokenData
from app.core.database import get_db
from app.core import ENCRYPTED_DIR, audit_logger
from app.core.auth import get_current_user
from app.core.rate_limiter import limiter
from app.models.file import File
from app.models.file_link import FileLink
from datetime import datetime, timezone
from pathlib import Path

from app.models.user import User

router = APIRouter()

@router.get("/list")
@limiter.limit("10/minute")
async def list_files(
    request: Request,
    current_user: TokenData = Depends(get_current_user),  # ← любой авторизованный
    db: AsyncSession = Depends(get_db)
):
    """Получить список файлов + активные ссылки (для user — только свои)"""
    
    print(f"📋 Запрос списка файлов от {current_user.sub} ({current_user.role})")
    
    files = []

    # 1. Базовый запрос — все файлы, отсортированные по дате загрузки
    stmt = select(File).order_by(File.uploaded_at.desc())

    # 2. Ограничение по правам
    if current_user.role not in {"doctor", "admin"}:
        # Обычный user видит ТОЛЬКО свои файлы
        user_stmt = select(User.id).where(User.username == current_user.sub)
        user_result = await db.execute(user_stmt)
        user_id = user_result.scalar()

        if user_id is None:
            print(f"⚠️ Пользователь {current_user.sub} не найден в БД — пустой список")
            return {"count": 0, "files": [], "message": "Пользователь не найден в базе"}

        stmt = stmt.where(File.user_id == user_id)

    # 3. Выполняем запрос на файлы
    result = await db.execute(stmt)
    db_files = result.scalars().all()

    for db_file in db_files:
        file_path = ENCRYPTED_DIR / db_file.encrypted_name
        
        if not file_path.exists():
            print(f"Файл {db_file.encrypted_name} есть в БД, но отсутствует на диске — пропускаем")
            continue

        try:
            stat = file_path.stat()

            # Активная ссылка (одна, самая свежая)
            token_stmt = select(FileLink.token).where(
                FileLink.file_id == db_file.id,
                FileLink.expires_at > datetime.now(timezone.utc),
                FileLink.downloads_count < FileLink.max_downloads
            ).order_by(FileLink.expires_at.desc()).limit(1)

            token_result = await db.execute(token_stmt)
            active_token = token_result.scalar()

            files.append({
                "id": db_file.id,
                "name": db_file.encrypted_name,
                "size": db_file.encrypted_size or stat.st_size,  # из БД или stat
                "modified": db_file.uploaded_at.isoformat(),     # лучше из БД
                "original_name": db_file.original_name,
                "patient_id": db_file.patient_id,
                "medical_metadata": db_file.medical_metadata,
                "download_token": active_token,
                "download_url": f"/api/download?token={active_token}" if active_token else None
            })
        except Exception as e:
            print(f"Ошибка обработки файла {db_file.encrypted_name}: {e}")
            audit_logger.log_operation(
                action="list_error",
                filename=db_file.encrypted_name,
                user=current_user.sub,
                reason=str(e),
                success=False
            )

    print(f"📋 Найдено {len(files)} файлов")
    
    return {
        "count": len(files),
        "files": files
    }