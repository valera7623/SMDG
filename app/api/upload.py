# app/api/upload.py
from fastapi import APIRouter, File, UploadFile, HTTPException, Depends
import magic  
import uuid

from app.core import (
    UPLOAD_DIR,
    ENCRYPTED_DIR,
    crypto_manager,
    audit_logger,
    get_public_key
)
from app.core.utils import sanitize_filename, calculate_hash
from app.core.auth import get_current_user, get_current_doctor, get_current_admin

router = APIRouter()

# Разрешённые mime-типы (можно расширить под нужды медицинских файлов)
ALLOWED_MIME_PREFIXES = [
    "application/pdf",                                           # PDF
    "image/",                                                    # Все изображения (jpeg, png, tiff, dicom и т.д.)
    "text/plain",                                                # Текстовые файлы
    "application/msword",                                        # .doc
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "application/vnd.ms-excel",                                  # .xls
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",       # .xlsx
    "application/rtf",                                           # RTF
    # Добавьте другие при необходимости, например DICOM: "application/dicom"
]

@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    current_user: str = Depends(get_current_doctor)  
):
    print(f"Upload от пользователя: {current_user.sub} ({current_user.role})")
    """
    Загрузка файла с проверкой типа, шифрованием и аудитом.
    """
    original_filename = file.filename or "unknown_file"
    
    # === Проверка mime-type ===
    # Читаем первые 4KB — достаточно для определения типа
    header_bytes = await file.read(4096)
    mime_type = magic.from_buffer(header_bytes, mime=True)
    await file.seek(0)  # Возвращаем указатель в начало для дальнейшего чтения
    
    if not any(mime_type.startswith(prefix) for prefix in ALLOWED_MIME_PREFIXES):
        raise HTTPException(
            status_code=415,
            detail=f"Недопустимый тип файла: {mime_type}. "
                   f"Разрешены: PDF, изображения, офисные документы."
        )
    
    # === Санитизация имени и подготовка путей ===
    safe_filename = sanitize_filename(original_filename)
    
    if not safe_filename:
        raise HTTPException(status_code=400, detail="Невозможно обработать имя файла")
    
    # Добавляем уникальный префикс для избежания коллизий
    unique_id = uuid.uuid4().hex[:8]
    final_encrypted_name = f"{unique_id}_{safe_filename}.age"
    
    temp_upload_path = UPLOAD_DIR / f"tmp_{unique_id}_{safe_filename}"
    encrypted_path = ENCRYPTED_DIR / final_encrypted_name
    
    try:
        # Сохраняем загруженный файл временно
        contents = await file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="Пустой файл")
        
        temp_upload_path.write_bytes(contents)
        original_size = temp_upload_path.stat().st_size
        
        # Получаем публичный ключ для шифрования
        public_key = get_public_key()
        
        # Асинхронное шифрование
        await crypto_manager.encrypt_file(
            input_path=temp_upload_path,
            output_path=encrypted_path,
            public_key=public_key
        )
        
        encrypted_size = encrypted_path.stat().st_size
        
        # Вычисляем хеш оригинального файла
        file_hash = calculate_hash(temp_upload_path)
        
        # Аудит успешной загрузки
        audit_logger.log_operation(
            action="upload",
            filename=final_encrypted_name,
            user="api_user",
            ip="unknown",  # можно добавить Request для реального IP
            reason="File successfully uploaded and encrypted",
            success=True,
            metadata={
                "original_name": original_filename,
                "safe_name": safe_filename,
                "mime_type": mime_type,
                "original_size": original_size,
                "encrypted_size": encrypted_size,
                "hash": file_hash,
                "hash_algorithm": "sha256"
            }
        )
        
        return {
            "message": "Файл успешно загружен и зашифрован",
            "original_name": original_filename,
            "encrypted_file": final_encrypted_name,
            "original_size": original_size,
            "encrypted_size": encrypted_size,
            "hash": file_hash
        }
        
    except HTTPException:
        # Перебрасываем известные ошибки дальше
        raise
    except Exception as e:
        print(f"Ошибка загрузки файла '{original_filename}': {e}")
        audit_logger.log_operation(
            action="upload",
            filename=original_filename,
            user="api_user",
            reason=f"Upload failed: {str(e)}",
            success=False,
            metadata={"mime_type": mime_type if 'mime_type' in locals() else "unknown"}
        )
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")
    
    finally:
        # Удаляем временный оригинал в любом случае
        if temp_upload_path.exists():
            try:
                temp_upload_path.unlink()
            except Exception as cleanup_error:
                print(f"Не удалось удалить временный файл {temp_upload_path}: {cleanup_error}")