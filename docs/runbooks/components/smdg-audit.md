# SMDG Audit Runbook

## Назначение

Аудит фиксирует операции безопасности и доступа, критичен для комплаенса.

## Проверки

```bash
tail -100 "audit_logs/audit_$(date +%Y-%m-%d).log"
docker compose logs --since 30m smdg | grep -i audit | tail -50
```

## Контроль целостности

- отсутствуют временные разрывы в логах
- есть записи по ключевым операциям (login/upload/download/delete)
- нет ошибок flush/rotation

## Инциденты

- пропуски в аудите -> `incidents/audit-gap.md`
- переполнение диска от логов -> `incidents/disk-full.md`
