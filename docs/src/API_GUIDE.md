# SMDG API Guide

> **Translation status:** this page is the source-of-truth slot for the
> English translation of the SMDG API guide. The authoritative Russian
> version currently lives at
> [`docs/locales/ru/API_GUIDE.md`](../locales/ru/API_GUIDE.md) and is being
> progressively migrated to this file. Until the migration completes,
> please refer to the Russian version for full examples.

## Overview

The SMDG API is an OpenAPI 3 / Swagger-compliant REST API served by
FastAPI. Interactive documentation is available at:

- `/docs` — Swagger UI (English, source of truth)
- `/openapi.json` — OpenAPI schema (English)
- `/openapi.ru.json` — OpenAPI schema with Russian descriptions
- `/openapi.de.json` — OpenAPI schema with German descriptions
- `/openapi.fr.json` — OpenAPI schema with French descriptions
- `/redoc` — ReDoc UI

## Authentication

SMDG uses JWT access tokens stored in an HttpOnly cookie `access_token`.
All write endpoints require authentication. Role-based access control
distinguishes `admin`, `doctor`, `user`, and `super_admin`.

## Major endpoints

| Area            | Endpoint                          | Method       |
|-----------------|-----------------------------------|--------------|
| Authentication  | `/api/auth/login`                 | POST         |
| Authentication  | `/api/auth/logout`                | POST         |
| Authentication  | `/api/auth/register`              | POST         |
| Authentication  | `/api/auth/change-password`       | POST         |
| Authentication  | `/api/auth/setup-2fa`             | POST         |
| Authentication  | `/api/auth/verify-2fa-setup`      | POST         |
| Authentication  | `/api/auth/disable-2fa`           | POST         |
| Files           | `/api/upload`                     | POST         |
| Files           | `/api/files`                      | GET          |
| Files           | `/api/download/{file_id}`         | GET          |
| Files           | `/api/files/{file_id}`            | DELETE       |
| Admin users     | `/api/admin/users`                | GET/POST     |
| Admin users     | `/api/admin/users/{id}`           | DELETE       |
| Audit export    | `/api/admin/audit/export`         | GET          |
| File audit      | `/api/admin/file-audit/`          | GET          |
| DICOM           | `/api/dicom/studies`              | GET          |
| DICOMweb        | `/wado-rs/...`, `/qido-rs/...`    | GET          |
| Webhooks        | `/api/webhooks`                   | GET/POST     |
| Health          | `/health`, `/health/live`, `/health/ready` | GET |
| Feature flags   | `/health/features`, `/health/deployment` | GET   |
| SLO / SLI       | `/api/slo`, `/api/sli`            | GET          |
| Demo (demo mode)| `/api/demo/info`                  | GET          |
| Metrics         | `/metrics`                        | GET          |

## Audit export API

`GET /api/admin/audit/export?format=xlsx|pdf|csv&from=YYYY-MM-DD&to=YYYY-MM-DD`

- Requires the `admin` role.
- `format` — one of `xlsx`, `pdf`, `csv`.
- `from` / `to` — inclusive date range (UTC).
- Optional filters: `user_id`, `action`, `resource_type`.
- Response: `application/octet-stream` with a `Content-Disposition`
  attachment header.

## Error model

All errors return a JSON payload:

```json
{
  "detail": "machine-readable English message",
  "code": "optional_error_code"
}
```

Clients are responsible for presenting localised versions of error
messages. The server always emits English strings.

## Rate limiting

Limits are enforced per IP via slowapi (Redis-backed in scaled mode) and are
configurable through environment variables (see `.env.example`).

| Scope                       | Default                    | Env override            |
|-----------------------------|----------------------------|-------------------------|
| Global default              | `100/minute`               | `RATE_LIMIT_DEFAULT`    |
| Login (`/api/auth/login`)   | `10/minute;5/10seconds`    | `RATE_LIMIT_LOGIN`      |
| Register (`/api/auth/register`) | `10/minute` (`3/hour` in demo) | `RATE_LIMIT_REGISTER` |
| `change-password`, `verify-2fa-setup` | `5/minute`      | —                       |
| `setup-2fa`, `disable-2fa`  | `3/minute`                 | —                       |
| `logout`                    | `60/minute`                | —                       |

`429 Too Many Requests` responses include a `Retry-After` header.
