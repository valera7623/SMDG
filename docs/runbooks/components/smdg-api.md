# SMDG API Runbook

## Общая информация

| Параметр | Значение |
|----------|----------|
| Сервис | SMDG API |
| Порт | 8000 |
| Логи | `docker compose logs smdg` |
| Метрики | `curl -s localhost:8000/metrics` |
| Health | `curl -s localhost:8000/health` |
| Readiness | `curl -s localhost:8000/health/ready` |

## Операции

```bash
docker compose up -d smdg
docker compose restart smdg
docker compose stop smdg
```

## Мониторинг

- p99 latency < 500ms
- 5xx rate < 1%
- active requests < 100

## Диагностика проблем

```bash
docker compose ps smdg
docker compose logs --tail=200 smdg
curl -s http://localhost:8000/health/ready | jq .
curl -s http://localhost:8000/api/circuit-breaker/status | jq .
docker compose exec -T redis redis-cli PING
```

## Эскалация

- P1: API недоступен полностью -> немедленная эскалация
- P2: высокая латентность/ошибки -> до 1 часа
