# Инцидент: Пропуски в аудите

## Симптомы

- отсутствуют записи за временной интервал
- алерт `SMDGAuditLogGap`

## Диагностика

```bash
ls -lah audit_logs
tail -200 "audit_logs/audit_$(date +%Y-%m-%d).log"
docker compose logs --since 1h smdg | grep -Ei "audit|flush|permission|disk" | tail -200
df -h
```

## Восстановление

1. Устранить root cause (диск, права, приложение).
2. Проверить, что новые записи снова пишутся.
3. Зафиксировать границы потенциальной потери аудита.
4. Уведомить security/compliance и создать post-incident отчет.
