"""Единое место для подавления известных шумных предупреждений третьих сторон.

Использовать при старте приложения / CLI / pytest до импорта passlib.
"""

from __future__ import annotations

import warnings


def apply_known_warning_filters() -> None:
    """Подключить фильтры идемпотентно (повторные вызовы безопасны)."""
    # passlib 1.7.x импортирует stdlib ``crypt`` → DeprecationWarning в Python 3.13+
    warnings.filterwarnings(
        "ignore",
        message=r"'crypt' is deprecated and slated for removal in Python 3\.13",
        category=DeprecationWarning,
    )
    # passlib / argon2-cffi: доступ к ``argon2.__version__`` устарел.
    warnings.filterwarnings(
        "ignore",
        message=r"Accessing argon2\.__version__ is deprecated.*",
        category=DeprecationWarning,
    )
