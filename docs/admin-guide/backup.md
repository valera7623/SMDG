# Резервное копирование

Процедуры бэкапа и восстановления SMDG.

## Что бэкапить

| Компонент | Критичность | Скрипт / метод |
|-----------|-------------|----------------|
| PostgreSQL | Критично | `scripts/backup.sh` |
| `encrypted/` или S3 bucket | Критично | `backup.sh` / `aws s3 sync` |
| `keys/age.key` | Критично | GPG-шифрование в `backup.sh` |
| `audit_logs/` | Высокая | tar.gz в `backup.sh` |
| `secrets/` | Высокая | копия в `backup.sh` |
| `.env` | Средняя | копия в `backup.sh` |

!!! danger "Ключ age"
    Без `age.key` зашифрованные файлы **невосстановимы**. Храните ключ отдельно от бэкапов данных (split custody).

## Автоматический бэкап

```bash
./scripts/backup.sh
```

Переменные:

| Переменная | По умолчанию |
|------------|--------------|
| `BACKUP_DIR` | `/backups/smdg` |
| `RETENTION_DAYS` | `30` |
| `S3_BUCKET_ENCRYPTED` | `smdg-encrypted` |

Рекомендуется cron:

```cron
0 2 * * * cd /opt/smdg && ./scripts/backup.sh >> /var/log/smdg-backup.log 2>&1
```

## Восстановление

```bash
./scripts/restore.sh
```

Перед восстановлением:

1. Остановите приложение (`docker compose down`).
2. Убедитесь, что `age.key` доступен.
3. Восстановите PostgreSQL из `db_*.sql.gz`.
4. Синхронизируйте `encrypted/` или S3 bucket.
5. Запустите стек и проверьте `/health/ready`.

Подробный runbook: [runbooks/operations/backup-recovery.md](../runbooks/operations/backup-recovery.md).

## Тестирование бэкапов

Раз в квартал выполняйте **тестовое восстановление** на staging:

1. Разверните чистый инстанс.
2. Восстановите последний бэкап.
3. Скачайте тестовый файл и откройте DICOM.

## Off-site копии

Копируйте `BACKUP_DIR` на отдельный сервер или в объектное хранилище с versioning и encryption at rest.
