# API — обзор

SMDG предоставляет REST API на FastAPI.

## Базовый URL

```
https://your-domain.com/api
```

Локально: `http://localhost/api`

## Интерактивная документация

| URL | Формат |
|-----|--------|
| `/docs` | Swagger UI (OpenAPI 3) |
| `/redoc` | ReDoc |
| `/openapi.json` | OpenAPI JSON (English) |
| `/openapi.ru.json` | OpenAPI с русскими описаниями |

## Аутентификация

Основной способ — **HttpOnly cookie** `access_token` после `POST /api/auth/login`.

Альтернатива для интеграций:

```bash
curl -H "Authorization: Bearer YOUR_JWT" \
  https://example.com/api/files
```

Подробнее: [auth.md](auth.md)

## Формат ответов

Успех — JSON.

Ошибки:

```json
{
  "detail": "machine-readable English message",
  "code": "optional_error_code"
}
```

| Код | Значение |
|-----|----------|
| 400 | Неверный запрос |
| 401 | Не авторизован |
| 403 | Нет прав |
| 404 | Не найдено |
| 429 | Rate limit |
| 500 | Ошибка сервера |

## Основные разделы

| Раздел | Документ |
|--------|----------|
| Аутентификация | [auth.md](auth.md) |
| Файлы | [files.md](files.md) |
| DICOM | [dicom.md](dicom.md) |
| Webhooks | [webhooks.md](webhooks.md) |
| Админ | [admin.md](admin.md) |

## Health и метрики

| Endpoint | Описание |
|----------|----------|
| `GET /health` | Сводка |
| `GET /health/live` | Liveness |
| `GET /health/ready` | Readiness |
| `GET /health/features` | Матрица фич |
| `GET /metrics` | Prometheus |

Полное руководство: [src/API_GUIDE.md](../src/API_GUIDE.md).
