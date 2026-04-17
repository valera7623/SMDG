from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant


def _plain_hostname(host: str) -> str:
    return (host or "").split(":")[0].strip().lower()


def extract_subdomain(host: str) -> str | None:
    if not host:
        return None
    hostname = host.split(":")[0].strip().lower()
    parts = hostname.split(".")
    if len(parts) < 3:
        return None
    return parts[0]


async def resolve_tenant_by_host(db: AsyncSession, host: str) -> Tenant | None:
    from app.core.config import settings

    subdomain = extract_subdomain(host)
    # Локально: https://localhost, http://127.0.0.1 — без поддомена; подставляем tenant default (см. миграцию / create_first_admin)
    if not subdomain:
        hn = _plain_hostname(host)
        if settings.tenant_resolve_localhost_as_default and hn in (
            "localhost",
            "127.0.0.1",
            "::1",
            "0.0.0.0",
        ):
            subdomain = settings.tenant_default_subdomain
        elif settings.dev_mode and hn == "":
            subdomain = settings.tenant_default_subdomain
    if not subdomain:
        return None
    result = await db.execute(select(Tenant).where(Tenant.subdomain == subdomain))
    return result.scalar_one_or_none()


def require_tenant(request: Request) -> Tenant:
    tenant = getattr(request.state, "tenant", None) or request.scope.get("tenant")
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant could not be resolved from subdomain",
        )
    return tenant


def assert_tenant_access(
    current_user_tenant_id: int | None,
    request_tenant_id: int | None,
    role: str,
) -> None:
    if role == "super_admin":
        return
    if request_tenant_id is None:
        raise HTTPException(status_code=400, detail="Tenant context is missing")
    if current_user_tenant_id != request_tenant_id:
        raise HTTPException(status_code=403, detail="Cross-tenant access is forbidden")
