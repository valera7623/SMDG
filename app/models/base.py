# app/models/base.py
"""
Standalone Base class for models — doesn't import from app.core.
This allows Alembic to import models without loading Settings.
"""
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    """Базовый класс для всех моделей"""
    pass
