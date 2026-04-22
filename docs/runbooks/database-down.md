# Runbook: SMDGDatabaseDown

**Severity:** `critical`
**Alert rule:** `smdg_db_up == 0 for 1m`

Внутренний health-check (`SELECT 1`) не проходит более минуты. SMDG не
может обслуживать запросы — всё, что требует БД, отдаёт 503/500.

## Диагностика

```bash
# 1. Доступен ли контейнер БД?
docker compose ps db

# 2. Логи PostgreSQL за последние 5 мин
docker compose logs --since 5m db | tail -100

# 3. Подключение извне приложения
docker compose exec db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} -c "SELECT 1"

# 4. pg_stat_activity — не залочены ли сессии
docker compose exec db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} \
  -c "SELECT pid, state, wait_event, query FROM pg_stat_activity;"
```

## Возможные причины

- **OOM / диск 100%** — проверить `df -h` и `dmesg`.
- **Max_connections исчерпан** — перезапустить SMDG (освобождает пул)
  или увеличить лимит в конфигурации PG.
- **Миграция зависла** — проверить блокировки: `SELECT * FROM pg_locks`.
- **Сеть между SMDG и db** — `docker network inspect smdg_backend`.

## Действия

1. Если контейнер БД упал — перезапустить:
   `docker compose restart db`.
2. Если диск забит — удалить старые WAL/логи, расширить volume.
3. Если проблема в пуле соединений — `docker compose restart smdg`
   (освободит открытые connection'ы).
4. Если ничего не помогает — failover на реплику (см. `docs/DB_FAILOVER.md`).

## После восстановления

- Проверить, что `smdg_db_up` вернулось в 1.
- Запустить smoke-test: `curl /health/ready` должен ответить 200.
- Убедиться, что webhook retry-очередь не распухла за время простоя.
