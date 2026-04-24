# Бэкап и восстановление SMDG

## Что бэкапим

- PostgreSQL (`smdg`)
- `encrypted/` (если локальное хранилище)
- `audit_logs/`
- Конфигурацию (`.env`, compose files, nginx config)

## Регламент

- DB backup: каждые 24 часа
- Проверка целостности: ежедневно
- Тест восстановления: минимум 1 раз в месяц

## Создание бэкапа

```bash
./scripts/backup.sh
ls -lah /backups /backups/smdg 2>/dev/null
```

## Восстановление БД

```bash
./scripts/restore.sh /backups/smdg/db_latest.sql.gz
```

После восстановления:

```bash
docker compose ps
curl -s http://localhost:8000/health/ready | jq .
```

## Восстановление файлов

1. Остановить запись в систему (maintenance mode).
2. Восстановить каталог `encrypted/` или объекты из S3/MinIO.
3. Сверить количество объектов с реестром БД.
4. Запустить smoke и выборочную проверку download/DICOM.

## Критерии успешного восстановления

- API отвечает и ready
- Данные читаются и расшифровываются
- Аудит продолжает писаться без пропусков
