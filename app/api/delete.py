# app/api/delete.py
import asyncio

from fastapi import APIRouter, HTTPException, Form, Query, Request, Depends
from app.core import ENCRYPTED_DIR, audit_logger
from app.core.auth import TokenData, get_current_admin
from app.core.utils import calculate_hash_async, sanitize_filename
from pathlib import Path
import os
import hashlib

router = APIRouter()

@router.post("/delete")
async def delete_file(
    filename: str = Form(...), 
    current_user: TokenData = Depends(get_current_admin), 
    
    confirm: str = Form("false"),  # Изменим на строку для простоты
    reason: str = Form("")
):
    """Удалить зашифрованный файл"""
    print(f"🗑️  Запрос на удаление файла: {filename}")
    print(f"   API Key: {get_current_admin}")
    print(f"   Confirm: {confirm}")
    print(f"   Reason: {reason}")
    
    
    
    # Безопасное имя файла
    safe_filename = sanitize_filename(filename)
    file_path = ENCRYPTED_DIR / safe_filename
    
    print(f"   Безопасное имя: {safe_filename}")
    print(f"   Путь к файлу: {file_path}")
    print(f"   Файл существует: {file_path.exists()}")
    
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
                raise HTTPException(status_code=404, detail=f"File not found: {safe_filename}")
        else:
            print(f"   ❌ Файл не найден: {safe_filename}")
            raise HTTPException(status_code=404, detail=f"File not found: {safe_filename}")
    
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
    print(f"   Хеш файла: {file_info['hash'][:20]}...")
    
    # Преобразуем confirm в boolean
    is_confirmed = confirm.lower() in ["true", "yes", "1", "on", "confirmed"]
    
    # Требуется подтверждение для удаления
    if not is_confirmed:
        print(f"   ⚠️  Требуется подтверждение")
        return {
            "message": "⚠️ Требуется подтверждение удаления",
            "file_info": {
                "name": safe_filename,
                "size": file_info["size"],
                "hash": file_info["hash"][:20] + "...",
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
        print(f"   ✅ Файл удален")
        
        # Логируем успешное удаление
        audit_logger.log_operation(
            action="delete",
            filename=safe_filename,
            user="admin",
            reason=reason or "Ручное удаление администратором",
            metadata=file_info,
            success=True
        )
        print(f"   📝 Операция залогирована")
        
        return {
            "message": "✅ Файл успешно удален",
            "filename": safe_filename,
            "hash": file_hash,
            "size": file_info["size"],
            "audit_logged": True,
            "timestamp": os.path.getmtime(str(file_path)) if os.path.exists(str(file_path)) else None
        }
        
    except Exception as e:
        print(f"   ❌ Ошибка удаления: {str(e)}")
        # Логируем неудачное удаление
        audit_logger.log_operation(
            action="delete",
            filename=safe_filename,
            user="admin",
            reason=reason or "Ручное удаление",
            metadata=file_info,
            success=False
        )
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")

@router.get("/delete")
async def delete_file_get(
    filename: str = Query(...),
    api_key: str = Query(..., alias="x-api-key"),
    confirm: str = Query("false"),
    reason: str = Query("")
):
    """Удалить зашифрованный файл (GET версия)"""
    print(f"🗑️  GET запрос на удаление: {filename}")
    # Используем ту же логику что и в POST
    return await delete_file(filename, api_key, confirm, reason)



