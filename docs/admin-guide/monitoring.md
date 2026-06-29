# Мониторинг

Наблюдаемость SMDG: метрики, трейсинг, алерты.

## Стек observability

| Компонент | URL (внутри compose) | Назначение |
|-----------|---------------------|------------|
| **Prometheus** | `:9090` | Сбор метрик |
| **Grafana** | `/grafana/` | Дашборды |
| **Alertmanager** | `:9093` | Маршрутизация алертов |
| **Jaeger** | `/jaeger/` | Distributed tracing (OpenTelemetry) |

## Health endpoints

```bash
curl https://${DOMAIN}/health/live    # liveness
curl https://${DOMAIN}/health/ready   # readiness
curl https://${DOMAIN}/metrics        # Prometheus scrape
```

## Ключевые метрики

| Метрика | Описание |
|---------|----------|
| `http_request_duration_seconds` | Латентность API |
| `smdg_slo_*` | SLO/SLI (см. `/api/slo`) |
| `circuit_breaker_*` | Состояние circuit breaker |
| `bulkhead_*` | Очереди bulkhead |

Дашборды: `grafana/dashboards/` (slo-dashboard, circuit-breaker-dashboard).

## Алерты

Конфигурация: `alertmanager/alertmanager.yml`, правила — `prometheus/`.

Telegram-уведомления (опционально):

```bash
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

## Runbooks

При срабатывании алерта:

1. Откройте Grafana → **SMDG - Alerts overview**.
2. Найдите runbook в [runbooks/](../runbooks/README.md).

| Проблема | Runbook |
|----------|---------|
| API не отвечает | [smdg-api.md](../runbooks/components/smdg-api.md) |
| БД медленная | [smdg-database.md](../runbooks/components/smdg-database.md) |
| DICOM не рендерится | [smdg-dicom.md](../runbooks/components/smdg-dicom.md) |
| Высокая память | [high-memory.md](../runbooks/incidents/high-memory.md) |

## Ежедневные проверки

См. [runbooks/operations/daily-checks.md](../runbooks/operations/daily-checks.md).

## SLA-отчёты

```bash
python scripts/monthly_sla_report.py
```
