# Инцидент: Сработал Rate Limiting

## Симптомы

- рост HTTP 429
- пользователи жалуются на недоступность login/upload

## Диагностика

```bash
docker compose logs --since 30m smdg | grep -Ei "rate limit|429|Too Many Requests" | tail -100
docker compose exec -T redis redis-cli INFO stats | grep -E "instantaneous_ops_per_sec|rejected_connections"
```

## Восстановление

1. Проверить источник трафика (бот, burst клиента, циклические retry).
2. Для легитимного трафика временно повысить лимит в `.env`.
3. Для злоупотребления включить блокировку по IP/API key.
4. Вернуть стандартные лимиты после стабилизации.
