# SMDG Runbooks

## Оглавление

- [Ежедневные операции](operations/daily-checks.md)
- [Еженедельное обслуживание](operations/weekly-maintenance.md)
- [Ежемесячные задачи](operations/monthly-tasks.md)
- [Бэкап и восстановление](operations/backup-recovery.md)
- [Компоненты системы](components/)
- [Аварийные сценарии](incidents/)
- [Устранение неисправностей](troubleshooting/)

## Быстрая навигация

| Проблема | Куда смотреть |
|----------|---------------|
| API не отвечает | [SMDG API Runbook](components/smdg-api.md#диагностика-проблем) |
| База данных медленная | [Database Runbook](components/smdg-database.md#производительность) |
| Ошибки аутентификации | [Auth Runbook](components/smdg-auth.md#диагностика-проблем) |
| DICOM не рендерится | [DICOM Runbook](components/smdg-dicom.md#диагностика-проблем) |
| Высокая нагрузка | [High CPU Incident](incidents/high-cpu.md) |
| Заполнен диск | [Disk Full Incident](incidents/disk-full.md) |

## Общий алгоритм on-call

1. Подтвердить алерт в Alertmanager (`http://alertmanager:9093`).
2. Открыть Grafana dashboard `SMDG - Alerts overview`.
3. Выполнить соответствующий runbook из этой директории.
4. Проверить `resolved` статус алерта и стабильность метрик 10-15 минут.
5. Создать post-mortem для инцидентов длительностью более 5 минут.

## Контакты

- **Primary On-call:** +7 XXX XXX-XX-XX
- **Secondary On-call:** +7 XXX XXX-XX-XX
- **Engineering Lead:** @username
- **Security Team:** security@smdg.local

## Legacy runbooks

Ранее созданные файлы верхнего уровня (`api-down.md`, `database-down.md`,
`system-compromise.md` и другие) остаются валидными и могут использоваться как
дополнение к новой структуре.
