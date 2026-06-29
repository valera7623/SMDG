# Monitoring

SMDG observability: metrics, tracing, alerts.

## Observability stack

| Component | URL (inside compose) | Purpose |
|-----------|---------------------|---------|
| **Prometheus** | `:9090` | Metrics collection |
| **Grafana** | `/grafana/` | Dashboards |
| **Alertmanager** | `:9093` | Alert routing |
| **Jaeger** | `/jaeger/` | Distributed tracing (OpenTelemetry) |

## Health endpoints

```bash
curl https://${DOMAIN}/health/live    # liveness
curl https://${DOMAIN}/health/ready   # readiness
curl https://${DOMAIN}/metrics        # Prometheus scrape
```

## Key metrics

| Metric | Description |
|--------|-------------|
| `http_request_duration_seconds` | API latency |
| `smdg_slo_*` | SLO/SLI (see `/api/slo`) |
| `circuit_breaker_*` | Circuit breaker state |
| `bulkhead_*` | Bulkhead queues |

Dashboards: `grafana/dashboards/` (slo-dashboard, circuit-breaker-dashboard).

## Alerts

Config: `alertmanager/alertmanager.yml`, rules in `prometheus/`.

Telegram notifications (optional):

```bash
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

## Runbooks

On alert:

1. Open Grafana → **SMDG - Alerts overview**.
2. Follow the runbook in [runbooks/](../runbooks/README.md).

| Issue | Runbook |
|-------|---------|
| API down | [smdg-api.md](../runbooks/components/smdg-api.md) |
| Slow DB | [smdg-database.md](../runbooks/components/smdg-database.md) |
| DICOM render failure | [smdg-dicom.md](../runbooks/components/smdg-dicom.md) |
| High memory | [high-memory.md](../runbooks/incidents/high-memory.md) |

## Daily checks

See [runbooks/operations/daily-checks.md](../runbooks/operations/daily-checks.md).

## SLA reports

```bash
python scripts/monthly_sla_report.py
```
