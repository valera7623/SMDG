# app/core/utils.py
import os
import re
import hashlib
from pathlib import Path


def sanitize_filename(filename: str) -> str:
    """
    Безопасная очистка имени файла с транслитерацией русских букв.
    Возвращает безопасное имя без пути, опасных символов и с латинскими буквами.
    """
    # Берем только имя файла (без пути)
    filename = Path(filename).name.strip()
    
    if not filename:
        return "unknown_file"
    
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
    
    # Транслитерируем
    sanitized = []
    for char in filename:
        sanitized.append(translit_map.get(char, char))
    
    filename = ''.join(sanitized)
    
    # Удаляем опасные символы
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1F]', '_', filename)
    
    # Заменяем пробелы и множественные подчёркивания на одно
    filename = re.sub(r'\s+', '_', filename)
    filename = re.sub(r'_+', '_', filename)
    
    # Обрезаем слишком длинное имя (оставляем место для расширения)
    name, ext = os.path.splitext(filename)
    if len(name) > 200:
        name = name[:200]
    filename = name + ext
    
    # Если после всего осталось пустое имя — возвращаем безопасное
    if not filename.strip('_'):
        filename = "file" + ext
    
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
