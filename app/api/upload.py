# app/api/upload.py
import os
import uuid
import magic
from fastapi import APIRouter, File, UploadFile, Form, HTTPException, Query
from app.core.utils import sanitize_filename
from app.core import (
    UPLOAD_DIR, ENCRYPTED_DIR, crypto_manager,
    API_KEYS, get_public_key, audit_logger
)
from pathlib import Path
import re

router = APIRouter()

mime = magic.Magic(mime=True)


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    api_key: str = Form(..., alias="x-api-key")
):
    """Загрузка и шифрование файла с проверкой MIME-типа"""
    if api_key not in API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    
    original_filename = file.filename or "unknown_file"
    safe_filename = sanitize_filename(original_filename)
    
    if not safe_filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    # === НОВАЯ ВАЛИДАЦИЯ MIME-ТИПА ===
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Empty file")
    
    file_mime = mime.from_buffer(contents[:1024])  # проверяем первые 1024 байта
    
    allowed_mimes = [
        'application/pdf',
        'image/jpeg', 'image/jpg',
        'image/png',
        'image/tiff', 'image/dicom',  # DICOM — стандарт для медицинских снимков
        'text/plain',
        'application/rtf',
        'application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # .docx
    ]
    
    if file_mime not in allowed_mimes:
        audit_logger.log_operation(
            action="upload_rejected",
            filename=original_filename,
            user="api_user",
            reason=f"Forbidden MIME type: {file_mime}",
            success=False
        )
        raise HTTPException(
            status_code=400,
            detail=f"Запрещённый тип файла: {file_mime}. "
                   "Разрешены только медицинские документы: PDF, JPG, PNG, TIFF, DICOM, TXT, RTF, Word."
        )
    # === КОНЕЦ НОВОЙ ВАЛИДАЦИИ ===
    
    unique_id = uuid.uuid4().hex[:8]
    final_name = f"{unique_id}_{safe_filename}.age"
    
    upload_path = UPLOAD_DIR / f"tmp_{unique_id}_{safe_filename}"
    encrypted_path = ENCRYPTED_DIR / final_name
    
    try:
        upload_path.write_bytes(contents)
        original_size = upload_path.stat().st_size
        
        public_key = get_public_key()
        await crypto_manager.encrypt_file(
            input_path=upload_path,
            output_path=encrypted_path,
            public_key=public_key
        )
        
        encrypted_size = encrypted_path.stat().st_size
        file_hash = crypto_manager.calculate_hash(upload_path)
        
        audit_logger.log_operation(
            action="upload",
            filename=final_name,
            user="api_user",
            reason="File uploaded and encrypted",
            success=True,
            metadata={
                "original_name": original_filename,
                "mime_type": file_mime,
                "size_original": original_size,
                "size_encrypted": encrypted_size,
                "hash": file_hash
            }
        )
        
        return {
            "message": "Файл успешно загружен и зашифрован",
            "original_name": original_filename,
            "encrypted_file": final_name,
            "original_size": original_size,
            "encrypted_size": encrypted_size,
            "hash": file_hash
        }
        
    except Exception as e:
        print(f"Ошибка при загрузке файла {original_filename}: {e}")
        audit_logger.log_operation(
            action="upload",
            filename=original_filename,
            user="api_user",
            reason=str(e),
            success=False
        )
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")
    
    finally:
        if upload_path.exists():
            try:
                upload_path.unlink()
            except Exception:
                pass