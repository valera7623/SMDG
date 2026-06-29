# API — Webhooks

SMDG отправляет HTTP POST на настроенные URL при событиях с файлами.

## События

| Событие | Когда |
|---------|-------|
| `file.uploaded` | После успешной загрузки |
| `file.downloaded` | После скачивания (в т.ч. по ссылке) |
| `file.deleted` | После удаления |

## Регистрация webhook

```http
POST /api/webhooks
Content-Type: application/json
Cookie: access_token=<JWT>

{
  "url": "https://your-service.com/hooks/smdg",
  "events": ["file.uploaded", "file.downloaded"],
  "secret": "your-hmac-secret"
}
```

## Подпись payload

Заголовок `X-SMDG-Signature`:

```
HMAC-SHA256(secret, raw_body)
```

Проверяйте подпись на стороне получателя.

## Повторные попытки

Exponential backoff при ошибках доставки. История — в БД и админ-панели DLQ.

## Список webhooks

```http
GET /api/webhooks
```

Требует роль `admin`.

Runbook: [runbooks/components/smdg-webhooks.md](../runbooks/components/smdg-webhooks.md).
