# API — administration

Endpoints for `admin` and `super_admin` roles.

## Users

```http
GET /api/admin/users
POST /api/admin/users
DELETE /api/admin/users/{id}
```

## Audit export

```http
GET /api/admin/audit/export?format=xlsx&from=2026-01-01&to=2026-06-30
```

| Parameter | Description |
|-----------|-------------|
| `format` | `xlsx`, `pdf`, `csv` |
| `from`, `to` | Date range (UTC, inclusive) |
| `user_id` | Filter by user (optional) |
| `action` | Filter by action (optional) |

Response: `application/octet-stream` with `Content-Disposition: attachment`.

## File access audit

```http
GET /api/admin/file-audit/
```

File access event tree in the admin panel.

## DLQ (Dead Letter Queue)

Failed webhook deliveries in UI `/admin` → DLQ.

API: see Swagger `/docs` (admin section).

## SLO / SLI

```http
GET /api/slo
GET /api/sli
```

Metrics for Grafana and SLA reports.

## Demo info

```http
GET /api/demo/info
```

`demo` profile only — public instance information.
