# Еженедельное обслуживание SMDG

## Цель

Поддерживать стабильность, производительность и прогнозируемый capacity.

## План (30-60 минут)

### 1. Проверка обновлений образов

```bash
docker compose pull
docker images | head -20
```

### 2. Проверка роста данных

```bash
docker compose exec -T db psql -U smdg_user -d smdg -c "SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC LIMIT 20;"
du -sh audit_logs encrypted uploads 2>/dev/null
```

### 3. Проверка очередей и ретраев

```bash
curl -s http://localhost:8000/api/dead-letter/stats | jq .
curl -s http://localhost:8000/api/webhooks/meta/events | jq .
```

### 4. Проверка ротации логов

```bash
find audit_logs -type f -name "*.log" | wc -l
```

### 5. Smoke после обслуживания

```bash
curl -s http://localhost:8000/health
pytest -q tests/test_api 2>/dev/null || true
```

## Результат

- Заполнить weekly section в Ops журнале
- Зафиксировать выявленные риски и тикеты на устранение
