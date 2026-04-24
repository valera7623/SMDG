# Debug Guide

## Сбор базовой диагностики

```bash
docker compose ps
docker compose logs --since 30m smdg db redis nginx > /tmp/smdg-debug.log
df -h
free -m
```

## Метрики

```bash
curl -s http://localhost:8000/metrics > /tmp/smdg-metrics.txt
curl -s http://localhost:9090/api/v1/alerts > /tmp/prom-alerts.json
```

## Проверка зависимостей API

```bash
docker compose exec -T smdg curl -s http://localhost:8000/health/ready
docker compose exec -T smdg python - <<'PY'
import asyncio
from app.core.database import engine
async def t():
    async with engine.connect() as c:
        await c.execute("SELECT 1")
asyncio.run(t())
print("db ok")
PY
```

## Артефакты для эскалации

- `/tmp/smdg-debug.log`
- `/tmp/smdg-metrics.txt`
- скриншоты Grafana/Alertmanager
