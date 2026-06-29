# Мультитенантность

Модель изоляции данных в SMDG.

## Модель

По умолчанию — **shared database**: все tenant'ы в одной PostgreSQL, изоляция через `tenant_id` на строках `User` и `File`.

## Определение tenant

1. **Subdomain** в заголовке `Host` (например `clinic1.example.com`).
2. JWT содержит `tenant_id` после входа.
3. Middleware проверяет соответствие Host и JWT.

```bash
TENANT_DEFAULT_SUBDOMAIN=default
TENANT_RESOLVE_LOCALHOST_AS_DEFAULT=true
```

## Роли

| Роль | Tenant scope |
|------|--------------|
| `user`, `doctor`, `admin` | Только свой tenant |
| `super_admin` | Кросс-tenant (профиль `saas`) |

## Хранилище

Файлы логически разделены метаданными (`tenant_id` в БД). На диске/S3 — общий bucket с префиксами или путями по политике приложения.

## Профили

| Профиль | Multi-tenant |
|---------|--------------|
| `single` | Нет (один tenant) |
| `saas` | Да |
| `russia`, `intl`, `demo` | Опционально |

Проверка: `GET /health/deployment`.

## API

Все write-эндпоинты автоматически scope'ятся по tenant из JWT/Host.

Подробнее: [src/MULTI_TENANCY.md](../src/MULTI_TENANCY.md).

## Runbook

Инцидент кросс-tenant доступа: [runbooks/cross-tenant-access.md](../runbooks/cross-tenant-access.md).
