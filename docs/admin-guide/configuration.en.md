# Configuration

SMDG is configured via `.env` and Docker Secrets.

## Deployment profile

```bash
DEPLOYMENT_TYPE=russia   # russia | intl | single | saas | demo
```

Feature matrix: `app/core/feature_flags.py`.

## Security

| Variable | Description |
|----------|-------------|
| `JWT_SECRET_KEY` | JWT secret (≥48 chars; Docker secret in prod) |
| `COOKIE_SECURE` | `true` in production |
| `REQUIRE_SECURE_COOKIES` | `true` in production |
| `CORS_ORIGINS` | Comma-separated HTTPS origins |
| `DEV_MODE` | `false` in production |

## Database and Redis

```bash
# In Docker prod, entrypoint.sh builds DATABASE_URL from postgres_password secret
REDIS_PASSWORD=<long-random-password>
```

## Storage

### Local (default)

Files in `encrypted/` on a Docker volume.

### S3 / MinIO

```bash
S3_ENABLED=true
S3_ENDPOINT_URL=http://minio:9000
S3_ACCESS_KEY=...
S3_SECRET_KEY=...
S3_BUCKET_ENCRYPTED=smdg-encrypted
```

Start with MinIO:

```bash
docker compose --profile s3 up -d
```

FS → S3 migration:

```bash
python scripts/migrate_to_s3.py --dry-run
python scripts/migrate_to_s3.py --delete-local
```

## Upload limits

```bash
MAX_UPLOAD_SIZE_MB=600
```

## DICOM Viewer

Enabled by default in `russia`, `intl`, `single`, `saas`, `demo` profiles.

## Telegram alerts (optional)

```bash
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
SMDG_DASHBOARD_URL=https://example.com/grafana/
```

## Multi-tenancy

```bash
TENANT_DEFAULT_SUBDOMAIN=default
TENANT_RESOLVE_LOCALHOST_AS_DEFAULT=true
```

See [Multi-tenancy](../developer-guide/multi-tenancy.md).

## Full variable list

See [Environment variables](../deployment/environment-variables.md) and `.env.example`.
