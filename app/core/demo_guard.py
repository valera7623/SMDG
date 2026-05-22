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
