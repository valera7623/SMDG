# Environment variables

Reference for main SMDG variables. Full list in `.env.example`.

## Application

| Variable | Default | Description |
|----------|---------|-------------|
| `DEV_MODE` | `false` | Development mode |
| `DEPLOYMENT_TYPE` | `single` | `russia` \| `intl` \| `single` \| `saas` \| `demo` |
| `MAX_UPLOAD_SIZE_MB` | `600` | Upload limit |
| `JWT_ACCESS_EXPIRES_MINUTES` | `60` | JWT TTL |

## Security

| Variable | Description |
|----------|-------------|
| `JWT_SECRET_KEY` | JWT secret (≥48 chars) |
| `COOKIE_SECURE` | Secure cookies |
| `REQUIRE_SECURE_COOKIES` | Require Secure |
| `CORS_ORIGINS` | Allowed origins |
| `CORS_INCLUDE_DEV_ORIGINS` | `false` in prod |

## Database

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://...` (built by entrypoint in Docker prod) |

## Redis

| Variable | Description |
|----------|-------------|
| `REDIS_PASSWORD` | Redis password |

## Domain and TLS

| Variable | Description |
|----------|-------------|
| `DOMAIN` | Primary domain |
| `DOMAIN_NAME` | Alternative name for scripts |
| `LETSENCRYPT_EMAIL` | ACME email |
| `API_PUBLIC_URL` | Public API URL |

## S3

| Variable | Description |
|----------|-------------|
| `S3_ENABLED` | Enable S3 backend |
| `S3_ENDPOINT_URL` | Endpoint (MinIO, Yandex, AWS) |
| `S3_ACCESS_KEY` | Access key |
| `S3_SECRET_KEY` | Secret key |
| `S3_BUCKET_ENCRYPTED` | Ciphertext bucket |

## Rate limiting

| Variable | Default |
|----------|---------|
| `RATE_LIMIT_DEFAULT` | `100/minute` |
| `RATE_LIMIT_LOGIN` | `10/minute;5/10seconds` |
| `RATE_LIMIT_REGISTER` | `10/minute` (demo: `3/hour`) |

## Multi-tenant

| Variable | Description |
|----------|-------------|
| `TENANT_DEFAULT_SUBDOMAIN` | Default subdomain |
| `TENANT_RESOLVE_LOCALHOST_AS_DEFAULT` | localhost → default tenant |

## Telegram

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Bot token |
| `TELEGRAM_CHAT_ID` | Alert chat ID |
| `SMDG_DASHBOARD_URL` | Grafana link in alerts |

## Docker prod (compose)

| Variable | Description |
|----------|-------------|
| `DOCKER_USERNAME` | Registry user |
| `IMAGE_TAG` | Immutable image tag |
| `GIT_SHA` | SHA for metrics |
