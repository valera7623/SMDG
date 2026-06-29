# Docker

Запуск SMDG в Docker Compose.

## Development

```bash
cp .env.example .env
docker compose up --build
```

Сервисы:

| Сервис | Порт | Назначение |
|--------|------|------------|
| `smdg` | 443 (через nginx) | FastAPI приложение |
| `db` | 5432 (internal) | PostgreSQL |
| `redis` | 6379 (internal) | Redis |
| `nginx` | 80, 443 | TLS, reverse proxy |

## Production

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Дополнительно в prod-стеке: Prometheus, Grafana, Alertmanager, Jaeger.

## Профили Compose

| Файл | Назначение |
|------|------------|
| `docker-compose.yml` | Базовый стек |
| `docker-compose.prod.yml` | Production override |
| `docker-compose.demo.yml` | Публичное демо |
| `docker-compose.intl.yml` | International (S3) |
| `docker-compose.replicas.yml` | Несколько реплик API |
| `docker-compose.load-test.yml` | k6 нагрузочные тесты |

## MinIO (S3)

```bash
# .env:
S3_ENABLED=true

docker compose --profile s3 up -d
```

Консоль MinIO: http://localhost:9001

## Секреты

В production секреты монтируются из `secrets/` через Docker Secrets (см. [admin-guide/deployment.md](../admin-guide/deployment.md)).

## Entrypoint

Контейнер `smdg` стартует от root для инициализации ключей и томов, затем приложение запускается как пользователь `smdg` через `gosu` в `entrypoint.sh`.

## Очистка

```bash
./scripts/docker-cleanup-ubuntu.sh
```
