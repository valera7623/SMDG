# Runbook: SMDGCrossTenantAccess

**Severity:** `critical`  ·  **Класс:** инцидент безопасности
**Alert rule:** `increase(cross_tenant_access_total[5m]) > 0`

## Что означает

Зафиксирована попытка доступа к данным чужого tenant'а. Это может быть:

- Баг авторизации (чаще всего);
- Целенаправленная атака (подмена `X-Tenant-ID` / JWT `tenant_id`);
- Неправильная конфигурация multi-tenancy.

Любая такая попытка — потенциальный **data-breach**, требует немедленного
реагирования в рамках IR-плейбука.

## Действия on-call (первые 10 минут)

1. **Изолировать инцидент.** Открыть логи SMDG за последние 15 минут и
   найти записи с `cross_tenant_access`:
   ```bash
   docker compose logs smdg --since 15m | grep -i cross_tenant
   ```
2. **Собрать trace_id** из лога и открыть в Jaeger:
   `https://tracing.smdg.local/trace/<trace_id>`.
3. **Идентифицировать актора:** IP, user_id, tenant_id из JWT.
4. **Заблокировать учётку** (если это подтверждённый abuse):
   ```bash
   # пример — через admin API
   curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" \
     https://smdg.local/api/admin/users/<id>/disable
   ```
5. **Уведомить DPO** (Data Protection Officer) и tech-lead'а.
6. **Запустить post-mortem** в Linear с тегом `security-incident`.

## Чек-лист IR (первые 24 часа)

- [ ] Определён scope: какие tenant'ы / какие записи могли утечь.
- [ ] Сохранены логи и трассы (copy to S3 forensics bucket).
- [ ] Проверено наличие экспорта данных за окно атаки.
- [ ] Уведомлены затронутые клиенты (если применимо по 152-ФЗ / GDPR).
- [ ] Создан hotfix для устранения root-cause.
- [ ] Написан тест на регрессию.

## Никогда не делать

- Не чистить логи до окончания расследования.
- Не класть детали инцидента в публичные комменты Linear до обсуждения
  с юр.отделом.
