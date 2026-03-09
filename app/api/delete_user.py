# app/api/delete_user.py
import asyncio
from fastapi import APIRouter, HTTPException, Form, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core import ENCRYPTED_DIR, audit_logger
from app.core.auth import get_current_user, TokenData
from app.core.database import get_db
from app.core.utils import calculate_hash_async, sanitize_filename
from app.models.file import File
from pathlib import Path
import os
import shutil

from app.models.user import User

router = APIRouter()

@router.post("/delete-user-file")
async def delete_user_file(
    filename: str = Form(...),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    confirm: str = Form("false")
):
    """Удалить свой зашифрованный файл (только для владельца)"""
    
    print(f"🗑️  Запрос пользователя {current_user.sub} на удаление файла: {filename}")
    
    # Безопасное имя файла
    safe_filename = sanitize_filename(filename)
    file_path = ENCRYPTED_DIR / safe_filename
    
    print(f"   Путь к файлу: {file_path}")
    
    if not file_path.exists():
        # Попробуем найти файл без .age расширения если нужно
        if not safe_filename.endswith('.age'):
            file_path_with_age = ENCRYPTED_DIR / f"{safe_filename}.age"
            if file_path_with_age.exists():
                file_path = file_path_with_age
                safe_filename = f"{safe_filename}.age"
                print(f"   ⚠️  Файл найден с .age: {safe_filename}")
            else:
                print(f"   ❌ Файл не найден: {safe_filename}")
                raise HTTPException(status_code=404, detail=f"Файл не найден: {safe_filename}")
        else:
            print(f"   ❌ Файл не найден: {safe_filename}")
            raise HTTPException(status_code=404, detail=f"Файл не найден: {safe_filename}")
    
    # Находим запись в БД
    result = await db.execute(
        select(File).where(File.encrypted_name == safe_filename)
    )
    db_file = result.scalar_one_or_none()
    
    if db_file:
        print(f"   Найдена запись в БД: id={db_file.id}, user_id={db_file.user_id}")
        
        # Проверяем права доступа
        if db_file.user_id:
            # Проверяем, что пользователь является владельцем
            result = await db.execute(
                select(User).where(User.username == current_user.sub)
            )
            user = result.scalar_one_or_none()
            
            if not user or user.id != db_file.user_id:
                if current_user.role != "admin":  # Админ может удалять любые файлы
                    print(f"   ❌ Нет прав: пользователь {current_user.sub} (id={user.id if user else None}) не владелец файла (user_id={db_file.user_id})")
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="У вас нет прав на удаление этого файла"
                    )
    else:
        print(f"   ⚠️  Запись в БД не найдена для {safe_filename}")
    
    # Информация о файле перед удалением (асинхронно)
    file_info = {
        "filename": safe_filename,
        "path": str(file_path),
        "size": "unknown",
        "hash": "unknown"
    }

    loop = asyncio.get_running_loop()

    try:
        # stat() асинхронно
        stat_result = await loop.run_in_executor(None, file_path.stat)
        file_info["size"] = stat_result.st_size

        # Хэш асинхронно (самый тяжёлый вызов)
        file_info["hash"] = await calculate_hash_async(file_path)

    except FileNotFoundError:
        file_info["size"] = 0
        file_info["hash"] = "file_not_found_before_delete"
    except PermissionError:
        file_info["size"] = "permission_denied"
        file_info["hash"] = "permission_denied"
    except Exception as e:
        file_info["size"] = f"error: {str(e)}"
        file_info["hash"] = f"error: {str(e)}"

    print(f" Размер файла: {file_info['size']} байт")
    print(f" Хеш файла: {file_info['hash'][:20]}...")
    
    print(f"   Размер файла: {file_info['size']} байт")
    
    # Требуется подтверждение для удаления
    is_confirmed = confirm.lower() in ["true", "yes", "1", "on", "confirmed"]
    
    if not is_confirmed:
        print(f"   ⚠️  Требуется подтверждение")
        return {
            "message": "⚠️ Требуется подтверждение удаления",
            "file_info": {
                "name": safe_filename,
                "size": file_info["size"],
                "original_name": db_file.original_name if db_file else safe_filename,
                "requires_confirmation": True
            },
            "confirmation_required": True
        }
    
    try:
        # Сохраняем хеш для аудита
        file_hash = file_info["hash"]
        
        print(f"   🗑️  Удаление файла...")
        
        # Удаляем файл
        os.remove(file_path)
        
        # Удаляем запись из БД если она есть
        if db_file:
            await db.delete(db_file)
            await db.commit()
            print(f"   ✅ Запись в БД удалена")
        
        print(f"   ✅ Файл удален")
        
        # Логируем успешное удаление
        audit_logger.log_operation(
            action="user_delete_file",
            filename=safe_filename,
            user=current_user.sub,
            reason="Удаление файла пользователем",
            metadata={
                **file_info,
                "original_name": db_file.original_name if db_file else None,
                "user_role": current_user.role
            },
            success=True
        )
        
        return {
            "message": "✅ Файл успешно удален",
            "filename": safe_filename,
            "original_name": db_file.original_name if db_file else safe_filename,
            "success": True
        }
        
    except Exception as e:
        print(f"   ❌ Ошибка удаления: {str(e)}")
        # Логируем неудачное удаление
        audit_logger.log_operation(
            action="user_delete_file",
            filename=safe_filename,
            user=current_user.sub,
            reason=f"Ошибка удаления: {str(e)}",
            metadata=file_info,
            success=False
        )
        raise HTTPException(status_code=500, detail=f"Ошибка удаления: {str(e)}")


@router.delete("/delete-user-file/{file_id}")
async def delete_user_file_by_id(
    file_id: int,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    confirm: bool = False
):
    """Удалить свой файл по ID (только для владельца)"""
    
    print(f"🗑️  Запрос пользователя {current_user.sub} на удаление файла ID={file_id}")
    
    # Находим запись в БД
    result = await db.execute(
        select(File).where(File.id == file_id)
    )
    db_file = result.scalar_one_or_none()
    
    if not db_file:
        raise HTTPException(status_code=404, detail=f"Файл с ID {file_id} не найден")
    
    # Проверяем права доступа
    if db_file.user_id:
        result = await db.execute(
            select(User).where(User.username == current_user.sub)
        )
        user = result.scalar_one_or_none()
        
        if not user or user.id != db_file.user_id:
            if current_user.role != "admin":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="У вас нет прав на удаление этого файла"
                )
    
    file_path = ENCRYPTED_DIR / db_file.encrypted_name
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Файл на диске не найден: {db_file.encrypted_name}")
    
    if not confirm:
        return {
            "message": "⚠️ Требуется подтверждение удаления",
            "file_info": {
                "id": db_file.id,
                "name": db_file.encrypted_name,
                "original_name": db_file.original_name,
                "size": db_file.original_size,
                "requires_confirmation": True
            }
        }
    
    try:
        # Удаляем файл
        os.remove(file_path)
        
        # Удаляем запись из БД
        await db.delete(db_file)
        await db.commit()
        
        audit_logger.log_operation(
            action="user_delete_file",
            filename=db_file.encrypted_name,
            user=current_user.sub,
            reason=f"Удаление файла по ID {file_id}",
            metadata={
                "file_id": file_id,
                "original_name": db_file.original_name
            },
            success=True
        )
        
        return {
            "message": "✅ Файл успешно удален",
            "id": file_id,
            "original_name": db_file.original_name,
            "success": True
        }
        
    except Exception as e:
        audit_logger.log_operation(
            action="user_delete_file",
            filename=db_file.encrypted_name,
            user=current_user.sub,
            reason=f"Ошибка удаления: {str(e)}",
            success=False
        )
        raise HTTPException(status_code=500, detail=f"Ошибка удаления: {str(e)}")