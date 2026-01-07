# app/api/upload.py
import os
from fastapi import APIRouter, File, UploadFile, Form, HTTPException
from app.core import UPLOAD_DIR, ENCRYPTED_DIR, crypto_manager, API_KEYS, get_public_key
from pathlib import Path
import re
import uuid
import unicodedata

router = APIRouter()

# app/api/upload.py - исправленная функция sanitize_filename
def sanitize_filename(filename: str) -> str:
    """Создание безопасного имени файла с транслитерацией русских букв"""
    from pathlib import Path
    import re
    import uuid
    
    # Берем только имя файла (без пути)
    filename = Path(filename).name
    
    # Словарь для транслитерации русских букв
    translit_dict = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
        'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ё': 'Yo',
        'Ж': 'Zh', 'З': 'Z', 'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L', 'М': 'M',
        'Н': 'N', 'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U',
        'Ф': 'F', 'Х': 'H', 'Ц': 'Ts', 'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Shch',
        'Ъ': '', 'Ы': 'Y', 'Ь': '', 'Э': 'E', 'Ю': 'Yu', 'Я': 'Ya'
    }
    
    # Транслитерируем русские буквы
    transliterated = []
    for char in filename:
        if char in translit_dict:
            transliterated.append(translit_dict[char])
        else:
            transliterated.append(char)
    
    filename = ''.join(transliterated)
    
    # Заменяем пробелы на подчеркивания
    filename = filename.replace(' ', '_')
    
    # Заменяем другие проблемные символы
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    
    # Убираем множественные подчеркивания
    filename = re.sub(r'_+', '_', filename)
    
    # Убираем подчеркивания в начале и конце
    filename = filename.strip('_')
    
    # Если имя файла пустое или состоит только из точек
    if not filename or filename == '.' or filename == '..':
        filename = f"file_{uuid.uuid4().hex[:8]}"
    
    # Ограничиваем длину имени файла (макс 255 символов)
    if len(filename) > 255:
        name, ext = os.path.splitext(filename)
        filename = name[:250] + ext
    
    return filename

@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...), 
    api_key: str = Form(..., alias="x-api-key")
):
    """Загрузить и зашифровать файл"""
    if api_key not in API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    
    original_filename = file.filename
    safe_filename = sanitize_filename(original_filename)
    
    print(f"📤 Загрузка файла")
    print(f"   Оригинальное имя: {original_filename}")
    print(f"   Безопасное имя: {safe_filename}")
    
    try:
        public_key = get_public_key()
        print(f"   Публичный ключ: {public_key[:30]}...")
    except ValueError as e:
        print(f"   ❌ ОШИБКА: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    upload_path = UPLOAD_DIR / safe_filename
    encrypted_path = ENCRYPTED_DIR / f"{safe_filename}.age"
    
    print(f"   📍 Путь для оригинала: {upload_path}")
    print(f"   📍 Путь для зашифрованного: {encrypted_path}")
    
    try:
        # 1. Сохраняем оригинальный файл с безопасным именем
        print(f"   💾 Сохранение оригинала...")
        with open(upload_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        file_size = upload_path.stat().st_size
        print(f"   ✅ Оригинал сохранен: {file_size} байт")
        
        # 2. Шифруем файл
        print(f"   🔐 Шифрование...")
        await crypto_manager.encrypt_file(upload_path, encrypted_path, public_key)
        
        encrypted_size = encrypted_path.stat().st_size
        print(f"   ✅ Файл зашифрован: {encrypted_size} байт")
        
        # 3. Вычисляем хеш для проверки целостности
        file_hash = crypto_manager.calculate_hash(upload_path)
        print(f"   🔢 Хеш файла: {file_hash[:20]}...")
        
        # 4. Удаляем оригинал
        print(f"   🗑️  Удаление оригинала...")
        if upload_path.exists():
            upload_path.unlink()
            print(f"   ✅ Оригинал удален")
        
        # 5. Проверяем что зашифрованный файл остался
        if encrypted_path.exists():
            print(f"   ✅ Зашифрованный файл сохранен: {encrypted_path.name}")
            print(f"   📊 Статистика: {file_size} → {encrypted_size} байт")
        else:
            print(f"   ❌ ОШИБКА: Зашифрованный файл не найден!")
            raise Exception("Зашифрованный файл не сохранен")
        
        return {
            "message": "✅ Файл успешно загружен и зашифрован",
            "original_name": original_filename,
            "safe_name": safe_filename,
            "encrypted_file": encrypted_path.name,
            "hash": file_hash,
            "original_size": file_size,
            "encrypted_size": encrypted_size
        }
        
    except Exception as e:
        print(f"   ❌ ОШИБКА: {type(e).__name__}: {e}")
        
        # Очистка при ошибке
        if upload_path.exists():
            print(f"   🗑️  Удаление оригинала из-за ошибки...")
            upload_path.unlink()
        
        raise HTTPException(status_code=500, detail=str(e))
    
    