# Переменные окружения

Справочник основных переменных SMDG. Полный список — в `.env.example`.

## Приложение

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `DEV_MODE` | `false` | Режим разработки |
| `DEPLOYMENT_TYPE` | `single` | `russia` \| `intl` \| `single` \| `saas` \| `demo` |
| `MAX_UPLOAD_SIZE_MB` | `600` | Лимит загрузки |
| `JWT_ACCESS_EXPIRES_MINUTES` | `60` | TTL JWT |

## Безопасность

| Переменная | Описание |
|------------|----------|
| `JWT_SECRET_KEY` | Секрет JWT (≥48 символов) |
| `COOKIE_SECURE` | Secure cookies |
| `REQUIRE_SECURE_COOKIES` | Требовать Secure |
| `CORS_ORIGINS` | Разрешённые origin |
| `CORS_INCLUDE_DEV_ORIGINS` | `false` в prod |

## База данных

| Переменная | Описание |
|------------|----------|
| `DATABASE_URL` | `postgresql+asyncpg://...` (в Docker prod собирается entrypoint) |

## Redis

| Переменная | Описание |
|------------|----------|
| `REDIS_PASSWORD` | Пароль Redis |

## Домен и TLS

| Переменная | Описание |
|------------|----------|
| `DOMAIN` | Основной домен |
| `DOMAIN_NAME` | Альтернативное имя для скриптов |
| `LETSENCRYPT_EMAIL` | Email для ACME |
| `API_PUBLIC_URL` | Публичный URL API |

## S3

| Переменная | Описание |
|------------|----------|
| `S3_ENABLED` | Включить S3 backend |
| `S3_ENDPOINT_URL` | Endpoint (MinIO, Yandex, AWS) |
| `S3_ACCESS_KEY` | Access key |
| `S3_SECRET_KEY` | Secret key |
| `S3_BUCKET_ENCRYPTED` | Bucket для ciphertext |

## Rate limiting

| Переменная | По умолчанию |
|------------|--------------|
| `RATE_LIMIT_DEFAULT` | `100/minute` |
| `RATE_LIMIT_LOGIN` | `10/minute;5/10seconds` |
| `RATE_LIMIT_REGISTER` | `10/minute` (demo: `3/hour`) |

## Multi-tenant

| Переменная | Описание |
|------------|----------|
| `TENANT_DEFAULT_SUBDOMAIN` | Subdomain по умолчанию |
| `TENANT_RESOLVE_LOCALHOST_AS_DEFAULT` | localhost → default tenant |

## Telegram

| Переменная | Описание |
|------------|----------|
| `TELEGRAM_BOT_TOKEN` | Bot token |
| `TELEGRAM_CHAT_ID` | Chat ID для алертов |
| `SMDG_DASHBOARD_URL` | Ссылка на Grafana в алертах |

## Docker prod (compose)

| Переменная | Описание |
|------------|----------|
| `DOCKER_USERNAME` | Registry user |
| `IMAGE_TAG` | Immutable image tag |
| `GIT_SHA` | SHA для метрик |
