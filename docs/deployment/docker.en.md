# Docker

Running SMDG with Docker Compose.

## Development

```bash
cp .env.example .env
docker compose up --build
```

Services:

| Service | Port | Purpose |
|---------|------|---------|
| `smdg` | 443 (via nginx) | FastAPI app |
| `db` | 5432 (internal) | PostgreSQL |
| `redis` | 6379 (internal) | Redis |
| `nginx` | 80, 443 | TLS, reverse proxy |

## Production

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Production stack also includes Prometheus, Grafana, Alertmanager, Jaeger.

## Compose files

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Base stack |
| `docker-compose.prod.yml` | Production override |
| `docker-compose.demo.yml` | Public demo |
| `docker-compose.intl.yml` | International (S3) |
| `docker-compose.replicas.yml` | Multiple API replicas |
| `docker-compose.load-test.yml` | k6 load tests |

## MinIO (S3)

```bash
# .env:
S3_ENABLED=true

docker compose --profile s3 up -d
```

MinIO console: http://localhost:9001

## Secrets

In production, secrets are mounted from `secrets/` via Docker Secrets (see [admin-guide/deployment.md](../admin-guide/deployment.md)).

## Entrypoint

The `smdg` container starts as root to initialise keys and volumes, then the app runs as user `smdg` via `gosu` in `entrypoint.sh`.

## Cleanup

```bash
./scripts/docker-cleanup-ubuntu.sh
```
