# app/api/download.py
from fastapi import APIRouter, Form, Query, HTTPException, Response
from typing import Optional
from app.core import ENCRYPTED_DIR, DECRYPTED_DIR, PRIVATE_KEY_PATH, crypto_manager, API_KEYS, file_storage
from pathlib import Path
import uuid
import os
import urllib.parse

router = APIRouter()

@router.post("/download")
async def download_file_post(
    filename: str = Form(...), 
    api_key: str = Form(..., alias="x-api-key")
):
    """Скачать и расшифровать файл (POST запрос)"""
    return await _download_file(filename, api_key)

@router.get("/download")
async def download_file_get(
    filename: str = Query(...),
    api_key: str = Query(..., alias="x-api-key")
):
    """Скачать и расшифровать файл (GET запрос)"""
    # Декодируем URL-encoded имя файла
    decoded_filename = urllib.parse.unquote(filename)
    return await _download_file(decoded_filename, api_key)

async def _download_file(filename: str, api_key: str):
    """Общая логика скачивания файла"""
    if api_key not in API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    
    # Очищаем имя файла от потенциально опасных символов
    safe_filename = _sanitize_filename(filename)
    encrypted_path = ENCRYPTED_DIR / safe_filename
    
    print(f"📥 Скачивание файла")
    print(f"   Запрошенное имя: {filename}")
    print(f"   Очищенное имя: {safe_filename}")
    print(f"   Полный путь: {encrypted_path}")
    
    if not encrypted_path.exists():
        # Попробуем найти файл альтернативными способами
        found_file = _find_encrypted_file(filename)
        if not found_file:
            raise HTTPException(
                status_code=404, 
                detail=f"Encrypted file not found: {filename}. Available files: {_list_available_files()}"
            )
        encrypted_path = found_file
        print(f"   ⚠️  Файл найден по альтернативному пути: {encrypted_path}")

    # Генерируем уникальное имя для расшифрованного файла
    unique_name = f"{uuid.uuid4()}_{safe_filename.replace('.age', '')}"
    decrypted_path = DECRYPTED_DIR / unique_name

    print(f"   Выходной файл: {decrypted_path}")

    try:
        # Дешифруем
        print(f"   🔓 Дешифрование...")
        await crypto_manager.decrypt_file(
            encrypted_path, 
            decrypted_path, 
            PRIVATE_KEY_PATH
        )
        
        decrypted_size = decrypted_path.stat().st_size
        print(f"   ✅ Файл дешифрован: {decrypted_size} байт")
        
        # Сохраняем в хранилище с TTL
        await file_storage.save_file(decrypted_path)
        
        # Читаем содержимое файла
        with open(decrypted_path, "rb") as f:
            content = f.read()
        
        # Безопасное имя для заголовка Content-Disposition
        original_filename = safe_filename.replace('.age', '')
        safe_original_name = _safe_filename_header(original_filename)
        
        return Response(
            content=content,
            media_type='application/octet-stream',
            headers={
                "Content-Disposition": f"attachment; filename=\"{safe_original_name}\"",
                "Content-Type": "application/octet-stream",
                "X-File-Size": str(decrypted_size),
                "X-Original-Name": safe_original_name
            }
        )
        
    except Exception as e:
        print(f"   ❌ Ошибка дешифрования: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Decryption failed: {str(e)}")

def _sanitize_filename(filename: str) -> str:
    """Очистка имени файла от опасных символов"""
    # Убираем путь, оставляем только имя файла
    filename = Path(filename).name
    
    # Заменяем проблемные символы
    import re
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    
    # Ограничиваем длину
    if len(filename) > 255:
        name, ext = os.path.splitext(filename)
        filename = name[:250] + ext
    
    return filename

def _safe_filename_header(filename: str) -> str:
    """Безопасное имя файла для заголовка HTTP"""
    # URL encode для безопасной передачи в заголовках
    import urllib.parse
    safe_name = urllib.parse.quote(filename)
    return safe_name

def _find_encrypted_file(requested_filename: str) -> Optional[Path]:
    """Поиск файла альтернативными способами"""
    requested_name = Path(requested_filename).name.lower()
    
    if ENCRYPTED_DIR.exists():
        for file_path in ENCRYPTED_DIR.iterdir():
            if file_path.is_file():
                # Проверяем точное совпадение
                if file_path.name == requested_filename:
                    return file_path
                
                # Проверяем совпадение без учета регистра
                if file_path.name.lower() == requested_name:
                    return file_path
                
                # Проверяем совпадение после декодирования URL
                decoded_requested = urllib.parse.unquote(requested_filename)
                if file_path.name == decoded_requested:
                    return file_path
    
    return None

def _list_available_files() -> list:
    """Список доступных файлов для отладки"""
    files = []
    if ENCRYPTED_DIR.exists():
        for file_path in ENCRYPTED_DIR.iterdir():
            if file_path.is_file():
                files.append({
                    "name": file_path.name,
                    "size": file_path.stat().st_size
                })
    return files
