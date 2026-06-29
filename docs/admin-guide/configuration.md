# Конфигурация

Основные параметры SMDG задаются через `.env` и Docker Secrets.

## Профиль развёртывания

```bash
DEPLOYMENT_TYPE=russia   # russia | intl | single | saas | demo
```

Матрица фич: `app/core/feature_flags.py`.

## Безопасность

| Переменная | Описание |
|------------|----------|
| `JWT_SECRET_KEY` | Секрет JWT (≥48 символов; в prod — Docker secret) |
| `COOKIE_SECURE` | `true` в production |
| `REQUIRE_SECURE_COOKIES` | `true` в production |
| `CORS_ORIGINS` | Список HTTPS origin через запятую |
| `DEV_MODE` | `false` в production |

## База данных и Redis

```bash
# В Docker prod DATABASE_URL собирает entrypoint.sh из secret postgres_password
REDIS_PASSWORD=<long-random-password>
```

## Хранилище

### Локальное (по умолчанию)

Файлы в `encrypted/` на томе Docker.

### S3 / MinIO

```bash
S3_ENABLED=true
S3_ENDPOINT_URL=http://minio:9000
S3_ACCESS_KEY=...
S3_SECRET_KEY=...
S3_BUCKET_ENCRYPTED=smdg-encrypted
```

Запуск с MinIO:

```bash
docker compose --profile s3 up -d
```

Миграция ФС → S3:

```bash
python scripts/migrate_to_s3.py --dry-run
python scripts/migrate_to_s3.py --delete-local
```

## Загрузка файлов

```bash
MAX_UPLOAD_SIZE_MB=600
```

## DICOM Viewer

Включён по умолчанию в профилях `russia`, `intl`, `single`, `saas`, `demo`.

## Telegram-алерты (опционально)

```bash
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
SMDG_DASHBOARD_URL=https://example.com/grafana/
```

## Мультитенантность

```bash
TENANT_DEFAULT_SUBDOMAIN=default
TENANT_RESOLVE_LOCALHOST_AS_DEFAULT=true
```

Подробнее: [Мультитенантность](../developer-guide/multi-tenancy.md).

## Полный список переменных

См. [Переменные окружения](../deployment/environment-variables.md) и `.env.example`.
