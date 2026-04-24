# Инцидент: Лимит соединений PostgreSQL

## Симптомы

- `too many connections`
- всплеск 5xx на API

## Диагностика

```bash
docker compose exec -T db psql -U smdg_user -d smdg -c "SELECT count(*) FROM pg_stat_activity;"
docker compose exec -T db psql -U smdg_user -d smdg -c "SELECT usename, state, count(*) FROM pg_stat_activity GROUP BY 1,2 ORDER BY 3 DESC;"
docker compose logs --tail=200 smdg | grep -Ei "too many connections|psycopg|database"
```

## Восстановление

1. Убрать лишние долгоживущие коннекты.
2. Временно перезапустить API/worker для сброса невалидных пулов.
3. Проверить настройки pool size/max overflow.
4. При необходимости поднять `max_connections` и ресурсы БД.
