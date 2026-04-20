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
| Authentication  | `/api/auth/2fa/setup`             | POST         |
| Files           | `/api/upload`                     | POST         |
| Files           | `/api/files`                      | GET          |
| Files           | `/api/download/{file_id}`         | GET          |
| Files           | `/api/files/{file_id}`            | DELETE       |
| Admin users     | `/api/admin/users`                | GET/POST     |
| Audit export    | `/api/admin/audit/export`         | GET          |
| DICOM           | `/api/dicom/studies`              | GET          |
| DICOMweb        | `/wado-rs/...`, `/qido-rs/...`    | GET          |
| Webhooks        | `/api/webhooks`                   | GET/POST     |
| Health          | `/health`                         | GET          |
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

- Default limit: 100 requests per minute per authenticated user.
- Login endpoint: 5 requests per minute per IP.
- `429 Too Many Requests` responses include a `Retry-After` header.
