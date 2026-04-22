# SMDG Alert Runbooks

Каждый алерт из `prometheus/alerts.yml` содержит аннотацию `runbook` со
ссылкой на страницу в этой директории. Используйте их как **чек-листы
для on-call** — цель: предсказуемо устранить инцидент за ≤ 15 минут.

Общий алгоритм при любом алерте:

1. **Acknowledge** в Alertmanager UI (`http://alertmanager:9093`), чтобы не
   нотифицировать остальных дублирующими сообщениями.
2. Открыть дашборд **SMDG — Alerts overview** в Grafana.
3. Проверить соответствующий раздел runbook'а (см. ниже).
4. После устранения — убедиться, что алерт перешёл в `resolved` и
   сработал `send_resolved` в канале.
5. Если инцидент был > 5 минут — создать post-mortem в Linear.

| Alert                       | Severity  | Runbook file                                     |
|-----------------------------|-----------|--------------------------------------------------|
| SMDGApiDown                 | critical  | [api-down.md](./api-down.md)                     |
| SMDGHighErrorRate           | critical  | [high-error-rate.md](./high-error-rate.md)       |
| SMDGHighLatency             | warning   | [high-latency.md](./high-latency.md)             |
| SMDGReadinessFailing        | critical  | [readiness-failing.md](./readiness-failing.md)   |
| SMDGDatabaseDown            | critical  | [database-down.md](./database-down.md)           |
| SMDGRedisDown               | critical  | [redis-down.md](./redis-down.md)                 |
| SMDGStorageDegraded         | critical  | [storage-down.md](./storage-down.md)             |
| SMDGUploadFailures          | warning   | [upload-failures.md](./upload-failures.md)       |
| SMDGDownloadFailures        | warning   | [download-failures.md](./download-failures.md)   |
| SMDGAuthFailures            | warning   | [auth-bruteforce.md](./auth-bruteforce.md)       |
| SMDG2FAFailures             | warning   | [2fa-failures.md](./2fa-failures.md)             |
| SMDGRateLimitExceeded       | warning   | [rate-limit-exceeded.md](./rate-limit-exceeded.md) |
| SMDGCrossTenantAccess       | critical  | [cross-tenant-access.md](./cross-tenant-access.md) |
| SMDGHighMemoryUsage         | warning   | [high-memory.md](./high-memory.md)               |
| SMDGHighCPUUsage            | warning   | [high-cpu.md](./high-cpu.md)                     |
| SMDGTooManyActiveRequests   | warning   | [overload.md](./overload.md)                     |
| SMDGDICOMViewerDown         | warning   | [dicom-down.md](./dicom-down.md)                 |
| SMDGDICOMRenderSlow         | warning   | [dicom-slow.md](./dicom-slow.md)                 |
| SMDGDICOMRenderFailures     | warning   | [dicom-render-failures.md](./dicom-render-failures.md) |
| SMDGAuditLogGap             | critical  | [audit-gap.md](./audit-gap.md)                   |
| SMDGWebhookRetryBacklog     | warning   | [webhook-backlog.md](./webhook-backlog.md)       |
| SMDGCleanupTaskBacklog      | warning   | [cleanup-backlog.md](./cleanup-backlog.md)       |
