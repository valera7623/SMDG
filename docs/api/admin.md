# API — администрирование

Эндпоинты для роли `admin` и `super_admin`.

## Пользователи

```http
GET /api/admin/users
POST /api/admin/users
DELETE /api/admin/users/{id}
```

## Экспорт аудита

```http
GET /api/admin/audit/export?format=xlsx&from=2026-01-01&to=2026-06-30
```

| Параметр | Описание |
|----------|----------|
| `format` | `xlsx`, `pdf`, `csv` |
| `from`, `to` | Период (UTC, включительно) |
| `user_id` | Фильтр по пользователю (опционально) |
| `action` | Фильтр по действию (опционально) |

Ответ: `application/octet-stream` с `Content-Disposition: attachment`.

## Аудит доступа к файлам

```http
GET /api/admin/file-audit/
```

Дерево событий доступа к файлам в админ-панели.

## DLQ (Dead Letter Queue)

Неудачные webhook-доставки доступны в UI `/admin` → DLQ.

API: см. Swagger `/docs` (admin section).

## SLO / SLI

```http
GET /api/slo
GET /api/sli
```

Метрики для Grafana и SLA-отчётов.

## Demo info

```http
GET /api/demo/info
```

Только профиль `demo` — публичная информация об инстансе.
