# API — webhooks

SMDG sends HTTP POST to configured URLs on file events.

## Events

| Event | When |
|-------|------|
| `file.uploaded` | After successful upload |
| `file.downloaded` | After download (including via link) |
| `file.deleted` | After deletion |

## Register webhook

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

## Payload signature

Header `X-SMDG-Signature`:

```
HMAC-SHA256(secret, raw_body)
```

Verify the signature on the receiver side.

## Retries

Exponential backoff on delivery failures. History in DB and admin DLQ panel.

## List webhooks

```http
GET /api/webhooks
```

Requires `admin` role.

Runbook: [runbooks/components/smdg-webhooks.md](../runbooks/components/smdg-webhooks.md).
