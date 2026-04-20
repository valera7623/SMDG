from fastapi import HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant


def _get_optional_header(request: Request, canonical: str) -> str | None:
    """Читает заголовок (имена в HTTP регистронезависимы — см. Starlette Headers)."""
    raw = request.headers.get(canonical)
    if raw is None:
        return None
    s = str(raw).strip()
    return s if s else None


def _plain_hostname(host: str) -> str:
    return (host or "").split(":")[0].strip().lower()


def extract_subdomain(host: str) -> str | None:
    """Извлекает поддомен из Host.

    - ``clinic.example.com`` → ``clinic`` (≥3 меток).
    - ``alpha.localhost`` → ``alpha`` (dev: две метки, второй уровень ``localhost``).
    Одиночный ``localhost`` / ``127.0.0.1`` не даёт поддомена (обрабатывается в resolve)."""
    if not host:
        return None
    hostname = host.split(":")[0].strip().lower()
    parts = hostname.split(".")
    if len(parts) >= 3:
        return parts[0]
    # Два сегмента: например alpha.localhost (curl / dev без DNS)
    if len(parts) == 2 and parts[1] == "localhost":
        return parts[0]
    return None


async def _resolve_tenant_from_headers_and_host(
    db: AsyncSession, request: Request
) -> Tenant | None:
    """Только заголовки и Host (без JWT)."""
    raw_id = _get_optional_header(request, "X-Tenant-ID")
    if raw_id is not None:
        try:
            tid = int(raw_id)
            result = await db.execute(select(Tenant).where(Tenant.id == tid))
            tenant = result.scalar_one_or_none()
            if tenant is not None:
                return tenant
        except (ValueError, TypeError):
            pass

    raw_sub = _get_optional_header(request, "X-Tenant-Subdomain")
    if raw_sub is not None:
        sub_norm = raw_sub.lower()
        result = await db.execute(
            select(Tenant).where(func.lower(Tenant.subdomain) == sub_norm)
        )
        tenant = result.scalar_one_or_none()
        if tenant is not None:
            return tenant

    return await resolve_tenant_by_host(db, request.headers.get("host", ""))


async def resolve_tenant_from_request(
    db: AsyncSession,
    request: Request,
    jwt_tenant_id: int | None = None,
    jwt_role: str | None = None,
) -> Tenant | None:
    """Определяет tenant для запроса.

    **Подсказки запроса** (порядок): ``X-Tenant-ID`` → ``X-Tenant-Subdomain`` → ``Host``.

    **JWT** (если переданы ``jwt_tenant_id`` / ``jwt_role`` из распакованного токена):

    - Обычные роли: при наличии ``tenant_id`` в токене загружается tenant из БД и **используется
      как основной контекст** — заголовки ``X-Tenant-*`` не обязательны после логина.
      Если подсказки запроса указывают другой tenant — **403** (несогласованность с сессией).
    - ``super_admin``: при явной подсказке (Host / заголовки) используется она; иначе — tenant из JWT.

    Без JWT / без ``tenant_id`` в токене поведение как раньше — только подсказки запроса.

    При выключенном ``MULTI_TENANCY`` контекст всегда ровно один — tenant с
    ``tenant_default_subdomain``. Это относится и к ``super_admin``: переключение через
    Host или ``X-Tenant-*`` отключено, чтобы single-tenant-профиль не имел скрытого multi-tenant.
    """
    from app.core.config import settings
    from app.core.feature_flags import Feature, is_enabled

    if not is_enabled(Feature.MULTI_TENANCY):
        result = await db.execute(
            select(Tenant).where(
                func.lower(Tenant.subdomain) == settings.tenant_default_subdomain.lower()
            )
        )
        tenant_default = result.scalar_one_or_none()
        if tenant_default is None:
            return await _resolve_tenant_from_headers_and_host(db, request)

        tid_i: int | None = None
        if jwt_tenant_id is not None:
            try:
                tid_i = int(jwt_tenant_id)
            except (TypeError, ValueError):
                tid_i = None

        role = (jwt_role or "").strip() or "user"

        # super_admin в single-tenant не выбирает организацию по Host/заголовкам — только default.
        if role != "super_admin":
            if tid_i is not None and tid_i != tenant_default.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Для режима без multi-tenancy допустим только tenant по умолчанию",
                )

            hints = await _resolve_tenant_from_headers_and_host(db, request)
            if hints is not None and hints.id != tenant_default.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Запрос указывает другой tenant; включён режим одной организации",
                )

        return tenant_default

    tenant_hints = await _resolve_tenant_from_headers_and_host(db, request)

    tid: int | None = None
    if jwt_tenant_id is not None:
        try:
            tid = int(jwt_tenant_id)
        except (TypeError, ValueError):
            tid = None

    role = (jwt_role or "").strip() or "user"

    if role == "super_admin":
        if tenant_hints is not None:
            return tenant_hints
        if tid is not None:
            result = await db.execute(select(Tenant).where(Tenant.id == tid))
            return result.scalar_one_or_none()
        return None

    if tid is not None:
        result = await db.execute(select(Tenant).where(Tenant.id == tid))
        tenant_jwt = result.scalar_one_or_none()
        if tenant_jwt is None:
            if tenant_hints is not None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Сессия содержит недействительный tenant; выполните вход повторно",
                )
            return None

        if tenant_hints is not None and tenant_hints.id != tenant_jwt.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tenant сессии не совпадает с Host или заголовками X-Tenant-*",
            )
        return tenant_jwt

    return tenant_hints


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
    result = await db.execute(
        select(Tenant).where(func.lower(Tenant.subdomain) == subdomain.lower())
    )
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
