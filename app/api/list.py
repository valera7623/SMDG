# app/api/list.py
from fastapi import APIRouter, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core import ENCRYPTED_DIR, audit_logger
from app.core.auth import get_current_doctor
from app.core.rate_limiter import limiter
from app.models.file import File
from app.models.file_link import FileLink
from datetime import datetime, timezone
from pathlib import Path

router = APIRouter()

@router.get("/list")
@limiter.limit("10/minute")
async def list_files(
    request: Request,
    current_user=Depends(get_current_doctor),
    db: AsyncSession = Depends(get_db)
):
    """Получить список зашифрованных файлов + активную ссылку для скачивания (если есть)"""
    
    print(f"📋 Запрос списка файлов из {ENCRYPTED_DIR} от {current_user.sub} ({current_user.role})")
    
    files = []
    if ENCRYPTED_DIR.exists():
        for file_path in ENCRYPTED_DIR.iterdir():
            if file_path.is_file() and file_path.suffix == '.age':
                try:
                    stat = file_path.stat()
                    
                    # 1. Находим File по encrypted_name (имя файла в БД)
                    file_stmt = select(File).where(File.encrypted_name == file_path.name)
                    file_result = await db.execute(file_stmt)
                    db_file = file_result.scalar_one_or_none()
                    
                    if not db_file:
                        print(f"Файл {file_path.name} не найден в БД — пропускаем")
                        continue
                    
                    # 2. Ищем активную ссылку по реальному file_id (integer)
                    token_stmt = select(FileLink.token).where(
                        FileLink.file_id == db_file.id,
                        FileLink.expires_at > datetime.now(timezone.utc),
                        FileLink.downloads_count < FileLink.max_downloads
                    ).order_by(FileLink.expires_at.desc()).limit(1)
                    
                    token_result = await db.execute(token_stmt)
                    active_token = token_result.scalar()
                    
                    files.append({
                        "id": db_file.id,
                        "name": file_path.name,
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                        "original_name": db_file.original_name,
                        "download_token": active_token or None,
                        "download_url": f"/api/download?token={active_token}" if active_token else None
                    })
                except Exception as e:
                    print(f"Ошибка обработки файла {file_path}: {e}")
                    audit_logger.log_operation(
                        action="list_error",
                        filename=file_path.name,
                        user=current_user.sub,
                        reason=str(e),
                        success=False
                    )
                    # Продолжаем цикл, чтобы не ломать весь ответ
    
    # Сортируем по времени изменения (новые сверху)
    files.sort(key=lambda x: x["modified"], reverse=True)
    
    print(f"📋 Найдено {len(files)} файлов")
    
    return {
        "count": len(files),
        "files": files
    }