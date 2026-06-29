# Deployment (administrator)

Guide for DevOps and system administrators deploying SMDG.

## Deployment options

| Method | When to use |
|--------|-------------|
| **GitHub Actions** | Production primary / demo (recommended) |
| **Docker Compose** | Local / staging / single-host prod |
| **zero_downtime_deploy.sh** | Rolling update without downtime |

## Quick start (development)

```bash
git clone https://github.com/valera7623/SMDG.git
cd SMDG
cp .env.example .env
docker compose up --build
```

Application: `https://localhost`

## Production (single host)

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### Required secrets

```bash
mkdir -p secrets
printf '%s' '<48+ chars jwt secret>' > secrets/jwt_secret.txt
printf '%s' '<initial admin password>' > secrets/admin_password.txt
printf '%s' '<postgres password>' > secrets/postgres_password.txt
printf '%s' '<age private key>' > secrets/age.key
printf '%s' '<grafana admin password>' > secrets/grafana_password.txt
```

### Post-deploy checks

```bash
curl -fsS https://${DOMAIN}/health/live
curl -fsS https://${DOMAIN}/health/ready
BASE_URL=https://${DOMAIN} ./scripts/post-deploy-verify.sh
```

| Endpoint | Purpose |
|----------|---------|
| `/health/live` | Liveness (process up) |
| `/health/ready` | Readiness (DB, Redis, storage) |
| `/health` | Monitoring summary |

## Deployment profiles

`DEPLOYMENT_TYPE` variable:

| Profile | Purpose |
|---------|---------|
| `russia` | FZ-152, local storage, 3-year audit |
| `intl` | S3, GDPR/HIPAA-oriented features |
| `single` | Single tenant, simplified admin |
| `saas` | Multi-tenant, billing in feature matrix |
| `demo` | Public demo (fileguardian.info) |

Check features: `GET /health/features` or `python -m app.cli feature-info`.

## CI/CD

- **primary** (186.246.3.65): `.github/workflows/deploy-primary.yml`
- **demo** (fileguardian.info): `.github/workflows/deploy-fileguardian.yml`

See [CI/CD](../deployment/ci-cd.md).

## Zero-downtime

```bash
./scripts/zero_downtime_deploy.sh
```

See `docs/src/DEPLOYMENT.md` for full details.
