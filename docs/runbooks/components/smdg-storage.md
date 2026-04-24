# SMDG Storage Runbook (S3/MinIO/Local)

## Назначение

Хранение зашифрованных payload-файлов и связанных объектов.

## Проверки

```bash
docker compose ps minio 2>/dev/null || true
docker compose logs --tail=200 minio 2>/dev/null || true
df -h /app/encrypted 2>/dev/null || true
```

MinIO health:

```bash
docker compose exec -T smdg curl -s http://minio:9000/minio/health/live
```

## Инциденты

- рост ошибок upload/download -> проверить доступность storage и креды
- рост latency -> проверить диск/сеть и нагрузку на bucket
- corruption подозрение -> переключиться на backup copy и инициировать расследование
