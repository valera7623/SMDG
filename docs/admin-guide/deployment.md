# Деплой (администратор)

Руководство для DevOps и системных администраторов SMDG.

## Варианты деплоя

| Способ | Когда использовать |
|--------|------------------|
| **GitHub Actions** | Продакшен primary / demo (рекомендуется) |
| **Docker Compose** | Локально / staging / single-host prod |
| **zero_downtime_deploy.sh** | Rolling update без простоя |

## Быстрый старт (development)

```bash
git clone https://github.com/valera7623/SMDG.git
cd SMDG
cp .env.example .env
docker compose up --build
```

Приложение: `https://localhost`

## Production (single host)

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### Обязательные секреты

```bash
mkdir -p secrets
printf '%s' '<48+ chars jwt secret>' > secrets/jwt_secret.txt
printf '%s' '<initial admin password>' > secrets/admin_password.txt
printf '%s' '<postgres password>' > secrets/postgres_password.txt
printf '%s' '<age private key>' > secrets/age.key
printf '%s' '<grafana admin password>' > secrets/grafana_password.txt
```

### Проверка после деплоя

```bash
curl -fsS https://${DOMAIN}/health/live
curl -fsS https://${DOMAIN}/health/ready
BASE_URL=https://${DOMAIN} ./scripts/post-deploy-verify.sh
```

| Endpoint | Назначение |
|----------|------------|
| `/health/live` | Liveness (процесс жив) |
| `/health/ready` | Readiness (БД, Redis, storage) |
| `/health` | Сводка для мониторинга |

## Профили развёртывания

Переменная `DEPLOYMENT_TYPE`:

| Профиль | Назначение |
|---------|------------|
| `russia` | ФЗ-152, локальное хранилище, аудит 3 года |
| `intl` | S3, GDPR/HIPAA-ориентированные фичи |
| `single` | Один tenant, упрощённая админка |
| `saas` | Multi-tenant, биллинг в матрице фич |
| `demo` | Публичное демо (fileguardian.info) |

Проверка фич: `GET /health/features` или `python -m app.cli feature-info`.

## CI/CD

- **primary** (186.246.3.65): `.github/workflows/deploy-primary.yml`
- **demo** (fileguardian.info): `.github/workflows/deploy-fileguardian.yml`

См. [CI/CD](../deployment/ci-cd.md).

## Zero-downtime

```bash
./scripts/zero_downtime_deploy.sh
```

Подробнее: [src/ZERO_DOWNTIME_DEPLOY.md](../src/ZERO_DOWNTIME_DEPLOY.md) (если есть) или `docs/src/DEPLOYMENT.md`.
