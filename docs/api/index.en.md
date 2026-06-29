# API overview

SMDG exposes a REST API built on FastAPI.

## Base URL

```
https://your-domain.com/api
```

Locally: `http://localhost/api`

## Interactive documentation

| URL | Format |
|-----|--------|
| `/docs` | Swagger UI (OpenAPI 3) |
| `/redoc` | ReDoc |
| `/openapi.json` | OpenAPI JSON (English) |
| `/openapi.ru.json` | OpenAPI with Russian descriptions |

## Authentication

Primary method: **HttpOnly cookie** `access_token` after `POST /api/auth/login`.

Alternative for integrations:

```bash
curl -H "Authorization: Bearer YOUR_JWT" \
  https://example.com/api/files
```

See [auth.md](auth.md)

## Response format

Success — JSON.

Errors:

```json
{
  "detail": "machine-readable English message",
  "code": "optional_error_code"
}
```

| Code | Meaning |
|------|---------|
| 400 | Bad request |
| 401 | Unauthorised |
| 403 | Forbidden |
| 404 | Not found |
| 429 | Rate limited |
| 500 | Server error |

## Main sections

| Area | Document |
|------|----------|
| Authentication | [auth.md](auth.md) |
| Files | [files.md](files.md) |
| DICOM | [dicom.md](dicom.md) |
| Webhooks | [webhooks.md](webhooks.md) |
| Admin | [admin.md](admin.md) |

## Health and metrics

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Summary |
| `GET /health/live` | Liveness |
| `GET /health/ready` | Readiness |
| `GET /health/features` | Feature matrix |
| `GET /metrics` | Prometheus |

Full guide: [src/API_GUIDE.md](../src/API_GUIDE.md).
