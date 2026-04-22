# Runbook: SMDGApiDown

**Severity:** `critical`
**Alert rule:** `up{job="smdg"} == 0 for 1m`

## Что означает

Prometheus не смог получить `/metrics` у SMDG API более 60 сек. Либо процесс
упал, либо сеть потеряла связь, либо `prometheus-fastapi-instrumentator`
завис.

## Быстрая диагностика (≤ 3 мин)

```bash
# 1. Проверить статус контейнеров
docker compose ps smdg

# 2. Последние 200 строк логов
docker compose logs --tail 200 smdg

# 3. Ручной /metrics (должен отвечать 200)
curl -sS -o /dev/null -w "%{http_code}\n" http://smdg:8000/metrics

# 4. /health/live должен отвечать всегда, пока процесс жив
curl -sS http://smdg:8000/health/live
```

## Возможные причины и действия

| Причина                      | Признак                                   | Действие                                |
|------------------------------|-------------------------------------------|-----------------------------------------|
| OOM-kill                     | `dmesg` или `docker inspect` → ExitCode 137 | Поднять память в compose, проверить утечки |
| Crash в lifespan             | Stacktrace в `docker logs`                  | Откатить последний релиз (`git revert`) |
| Deadlock worker'а            | `/health/live` 200, `/metrics` таймаутит   | `docker compose restart smdg`           |
| Сеть между Prometheus и SMDG | `up` падает, но SMDG отвечает локально     | Проверить `docker network inspect smdg_backend` |

## Эскалация

- Если через 10 минут не восстановлен → уведомить tech-lead'а.
- Если затронута regulated-среда (Russia/HIPAA) → создать инцидент в
  compliance-треке.
