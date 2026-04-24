# Ежемесячные задачи SMDG

## 1. Capacity review

```bash
docker system df
df -h
docker compose exec -T db psql -U smdg_user -d smdg -c "SELECT pg_database_size('smdg')/1024/1024/1024 AS size_gb;"
```

Проверить тренды в Grafana:
- RPS
- p95/p99 latency
- DB connections
- Redis memory
- Disk utilization

## 2. Проверка бэкапов и восстановления

```bash
./scripts/restore.sh --dry-run 2>/dev/null || true
```

Провести тестовое восстановление в staging.

## 3. Security housekeeping

- Проверить результаты `security-scan.yml`
- Закрыть/эскалировать критичные findings
- Ревизия токенов и секретов

## 4. Технический долг эксплуатации

- Обновить runbooks по новым инцидентам
- Обновить SLO и алерты при изменении нагрузки
