# Runbook: SMDGAuditLogGap

**Severity:** `critical`  ·  **Класс:** compliance
**Alert rule:** `(time() - smdg_last_audit_timestamp) > 300 for 5m`

Аудит-логи не обновлялись более 5 минут. Это **регуляторный риск**:
152-ФЗ, HIPAA и GDPR требуют непрерывности логирования. Даже если
сам сервис работает, отсутствие логирования действий пользователей
может привести к штрафу.

## Диагностика

```bash
# 1. Файлы audit_logs — пишется ли что-то?
ls -lh audit_logs/ | tail

# 2. Диск заполнен?
df -h | grep audit_logs

# 3. Логи самого SMDG за последние 10 мин на предмет AuditLogger errors
docker compose logs --since 10m smdg | grep -i audit
```

## Возможные причины

- **Диск заполнен** — самая частая причина.
- **Права на директорию** `audit_logs/` изменились (например, после
  перезапуска с другим UID).
- **Баг в AuditLogger** — крэш треда/корутины записи.
- **SMDG idle** — если сервис просто не получал запросов, гэп возможен
  в dev-среде; в production это аномалия, т.к. health probes сами
  идут через middleware.

## Действия

1. Освободить диск, если забит:
   ```bash
   # Архивировать старые аудит-логи в S3 и удалить
   ./scripts/archive_audit_logs.sh --older-than 90d
   ```
2. Перезапустить SMDG, если AuditLogger крэшнулся:
   ```bash
   docker compose restart smdg
   ```
3. Проверить, что новая запись появилась:
   ```bash
   curl http://smdg:8000/health/live
   tail -n 1 audit_logs/$(date +%Y-%m-%d).log
   ```

## Compliance-эскалация

- Если простой > 1 часа → уведомить DPO и compliance-officer.
- В post-mortem обязательно указать, какие операции происходили в окне
  отсутствия логов (по Prometheus counters).
