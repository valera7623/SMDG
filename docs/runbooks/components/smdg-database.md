# SMDG PostgreSQL Runbook

## Назначение

PostgreSQL хранит пользователей, метаданные файлов, токены, аудит и служебные данные.

## Ежедневные проверки

```bash
docker compose exec -T db pg_isready -U smdg_user
docker compose exec -T db psql -U smdg_user -d smdg -c "SELECT count(*) FROM pg_stat_activity;"
docker compose exec -T db psql -U smdg_user -d smdg -c "SELECT pg_database_size('smdg')/1024/1024 AS size_mb;"
```

## Производительность

```bash
docker compose exec -T db psql -U smdg_user -d smdg -c "SELECT query, calls, mean_exec_time FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 10;" 2>/dev/null || true
```

## Частые проблемы

- `too many connections` -> см. `incidents/db-connection-limit.md`
- медленные запросы -> проверить индексы, VACUUM, рост таблиц
- репликация отстает -> проверить network/IO лаг

## Восстановление

```bash
./scripts/restore.sh /backups/smdg/db_latest.sql.gz
```
