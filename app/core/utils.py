# app/core/utils.py
import os
import re
import hashlib
from pathlib import Path
import unicodedata
import uuid


def sanitize_filename(filename: str, max_length: int = 200) -> str:
    """
    Максимально безопасная очистка имени файла:
    - транслитерация
    - удаление опасных символов
    - ограничение длины
    - замена на safe если пусто
    """
    if not filename or not filename.strip():
        return "unnamed_file"

    # Берём только имя (без пути)
    filename = Path(filename).name.strip()

    # Нормализация Unicode (NFKD → разбивает лигатуры)
    filename = unicodedata.normalize("NFKD", filename)
    
    # Словарь транслитерации русских букв в латиницу
    translit_map = {
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
    
    filename = ''.join(translit_map.get(c.lower(), c) for c in filename)

    # Оставляем только разрешённые символы
    filename = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)

    # Убираем множественные подчёркивания и точки
    filename = re.sub(r'_+', '_', filename)
    filename = re.sub(r'\.+', '.', filename)
    filename = filename.strip('_.- ')

    # Ограничение длины (оставляем место для расширения и уникального суффикса)
    if len(filename) > max_length:
        name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
        ext = f".{ext}" if ext else ''
        trunc_len = max_length - len(ext) - 10  # запас на _uuid
        filename = name[:trunc_len] + ext

    # Финальная проверка
    if not filename or filename == '.' or filename == '..':
        filename = f"file_{uuid.uuid4().hex[:8]}"

    return filename

def calculate_hash(file_path: Path, algorithm: str = "sha256", chunk_size: int = 4096) -> str:
    
    if not file_path.exists():
        return f"hash_error: file_not_found ({file_path})"
    
    try:
        hasher = hashlib.new(algorithm)
        
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                hasher.update(chunk)
        
        return hasher.hexdigest()
        
    except PermissionError:
        return f"hash_error: permission_denied ({file_path})"
    except OSError as e:
        return f"hash_error: os_error ({str(e)})"
    except Exception as e:
        return f"hash_error: unknown ({str(e)})"


def check_path_exists(path: Path) -> bool:
    """Проверяет существование файла или директории."""
    return path.exists()
