#!/usr/bin/env python3
"""
Специализированный скрипт очистки clean_bot.py
"""

import shutil
from pathlib import Path

def clean_project():
    """Очистка артефактов bota"""
    project_root = Path(__file__).parent
    
    targets = [
        # Кэш Python
        "__pycache__",
        "*.pyc",
        "*.pyo",
        
        # Кэш тестов и покрытия
        ".pytest_cache",
        "htmlcov",
        ".coverage",
        ".coverage.*",
        
        # Кэш анализаторов
        ".mypy_cache", 
        ".ruff_cache",
        
        # Сборки и дистрибутивы
        "build/",
        "dist/",
        "*.egg-info/",
        
        # Временные файлы
        "*.tmp",
        "*.temp",
        
        # Конкретно cpython файлы
        "**/*.cpython-*.pyc",
    ]
    
    print("🧹 Очистка проекта...")
    deleted_count = 0
    total_size = 0
    
    for target in targets:
        for path in project_root.rglob(target):
            try:
                if path.is_file():
                    size = path.stat().st_size
                    path.unlink()
                    print(f"🗑️  Файл: {path.relative_to(project_root)}")
                    deleted_count += 1
                    total_size += size
                elif path.is_dir():
                    shutil.rmtree(path)
                    print(f"🗑️  Директория: {path.relative_to(project_root)}/")
                    deleted_count += 1
            except Exception as e:
                print(f"⚠️  Не удалось удалить {path}: {e}")
    
    # Форматируем размер
    size_str = f"{total_size / 1024 / 1024:.2f} MB" if total_size > 1024*1024 else f"{total_size / 1024:.2f} KB"
    
    print(f"\n✅ Удалено: {deleted_count} объектов")
    print(f"📊 Освобождено: {size_str}")

if __name__ == "__main__":
    clean_project()
