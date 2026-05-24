"""
Demo guard — decorator to block destructive operations in demo mode.

Usage:
    from app.core.demo_guard import demo_readonly

    @router.delete("/api/admin/users/{user_id}")
    @demo_readonly("Deleting users")
    async def delete_user(...):
        ...

The decorator inspects `settings.demo_mode` at request time.
Returns HTTP 403 with a user-friendly English message when blocked.
"""
from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from fastapi import HTTPException, status


def is_demo_seed_file(file: Any) -> bool:
    """True for files created by demo_seeder (protected from deletion in demo mode)."""
    from app.core.config import settings

    if not settings.demo_mode:
        return False

    metadata = getattr(file, "medical_metadata", None) or {}
    if isinstance(metadata, dict) and metadata.get("demo") is True:
        return True

    patient_id = getattr(file, "patient_id", None)
    if isinstance(patient_id, str) and patient_id.startswith("demo-"):
        return True

    encrypted_name = getattr(file, "encrypted_name", "") or ""
    if encrypted_name.startswith("demo_"):
        return True

    return False


def assert_demo_file_deletable(file: Any) -> None:
    """Raise 403 if the file is a demo seed artifact that must stay for the showcase."""
    if not is_demo_seed_file(file):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "This is a demo sample file and cannot be deleted. "
            "Upload your own file to test the delete workflow."
        ),
    )


def demo_readonly(operation: str = "This operation") -> Callable:
    """Decorator: raises HTTP 403 if the application is running in demo mode.

    Args:
        operation: Human-readable name of the blocked operation shown in the
                   error detail (e.g. "Deleting users", "Bulk file cleanup").
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            from app.core.config import settings  # lazy import to avoid circular deps
            if settings.demo_mode:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        f"{operation} is disabled in Demo mode. "
                        "Deploy your own instance for unrestricted access: "
                        "https://github.com/smdg-project/smdg"
                    ),
                )
            return await func(*args, **kwargs)
        return wrapper
    return decorator
