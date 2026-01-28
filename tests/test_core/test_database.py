# tests/test_core/test_database_fixed.py
import pytest
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

def test_database_import():
    """Тест импорта database модуля"""
    from app.core.database import engine, AsyncSessionLocal, Base, get_db
    
    assert engine is not None
    assert Base is not None
    assert AsyncSessionLocal is not None
    
    # get_db возвращает асинхронный генератор, а не корутину
    import inspect
    assert inspect.isasyncgenfunction(get_db)  # Исправлено с iscoroutinefunction
    
    print("✅ Database импорт тест пройден")

def test_base_model():
    """Тест базовой модели"""
    from app.core.database import Base
    from sqlalchemy import Column, Integer, String
    
    # Создаем тестовую модель
    class TestModel(Base):
        __tablename__ = "test_table"
        id = Column(Integer, primary_key=True)
        name = Column(String(50))
    
    # Проверяем что метаданные доступны
    assert hasattr(Base, 'metadata')
    assert "test_table" in Base.metadata.tables
    
    print("✅ Base model тест пройден")