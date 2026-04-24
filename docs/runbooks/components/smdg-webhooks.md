# SMDG Webhooks Runbook

## Назначение

Webhook subsystem доставляет внешние уведомления и использует retry/DLQ.

## Проверки

```bash
curl -s http://localhost:8000/api/webhooks/meta/events | jq .
curl -s http://localhost:8000/api/dead-letter/stats | jq .
docker compose logs --since 30m smdg | grep -i webhook | tail -100
```

## Диагностика проблем

- рост retry backlog -> проверить внешние endpoint и сеть
- частые timeout -> проверить webhook target latency
- DLQ рост -> инициировать replay после фикса первопричины

## Восстановление

1. Исправить endpoint/доступность приемника.
2. Проверить подпись/секрет webhook.
3. Запустить replay из DLQ.
4. Убедиться, что backlog снижается.
