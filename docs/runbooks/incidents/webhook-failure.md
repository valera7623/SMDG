# Инцидент: Ошибки webhook

## Симптомы

- рост retry backlog / DLQ
- внешние системы не получают события

## Диагностика

```bash
docker compose logs --since 30m smdg | grep -i webhook | tail -200
curl -s http://localhost:8000/api/dead-letter/stats | jq .
```

## Восстановление

1. Проверить доступность webhook endpoint получателя.
2. Проверить TLS/сертификаты и секрет подписи.
3. Уменьшить burst, чтобы не DDOSить получателя ретраями.
4. После восстановления выполнить replay из DLQ.
