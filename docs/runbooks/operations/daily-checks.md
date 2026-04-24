# Ежедневные проверки SMDG

## Утренняя проверка (15 минут)

### 1. Проверка здоровья системы

```bash
docker compose ps
curl -s http://localhost:8000/health | jq .
curl -s http://localhost:8000/health/ready | jq .
curl -s http://localhost:8000/health/live | jq .
```

### 2. Проверка метрик и алертов

```bash
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | {job: .labels.job, health: .health}'
curl -s http://localhost:9093/api/v1/alerts | jq '.data[] | {name: .labels.alertname, state: .status.state}'
```

### 3. Проверка логов и аудита

```bash
docker compose logs --since 24h smdg | grep -i error | tail -20
tail -50 "audit_logs/audit_$(date +%Y-%m-%d).log"
```

### 4. Проверка БД и Redis

```bash
docker compose exec -T db psql -U smdg_user -d smdg -c "SELECT pg_database_size('smdg')/1024/1024 AS size_mb;"
docker compose exec -T db psql -U smdg_user -d smdg -c "SELECT count(*) FROM pg_stat_activity;"
docker compose exec -T redis redis-cli INFO memory | grep used_memory_human
```

### 5. Проверка хранилища и диска

```bash
df -h
df -h /app/encrypted 2>/dev/null || true
docker compose exec -T smdg ls -lah /app/encrypted | head
```

### 6. Проверка бэкапов

```bash
find /backups -type f -mtime -1 | head -20
```

## Чеклист

- Все контейнеры в состоянии `Up` или `Healthy`
- `/health`, `/health/ready`, `/health/live` возвращают `200`
- Нет критических ошибок в логах
- Свободное место на диске > 20%
- Свежий бэкап за последние 24 часа присутствует
- Нет необработанных критических алертов

## Если что-то не так

1. Открыть [common-issues.md](../troubleshooting/common-issues.md)
2. Выполнить [debug-guide.md](../troubleshooting/debug-guide.md)
3. При необходимости следовать [escalation.md](../troubleshooting/escalation.md)
