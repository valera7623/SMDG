# SMDG deployment profiles

The environment variable **`DEPLOYMENT_TYPE`** accepts one of:
`russia` | `intl` | `single` | `saas`.

## Python runtime

Production containers built from the repository [`Dockerfile`](../../Dockerfile) use **Python 3.10** (`python:3.10-slim`). CI runs tests on **Python 3.10, 3.11, and 3.12** (see [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)). When debugging production behaviour locally, align your interpreter with the image baseline unless you intentionally rebuild the image on a newer Python.

## Production Docker Compose (single host)

The supported single-host production entrypoint is the base compose file plus
the production override:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml config
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Do not rely on `deploy.replicas`, `deploy.update_config` or
`deploy.rollback_config` when running plain Docker Compose: those keys are
Swarm-only. They remain in `docker-compose.prod.yml` as documentation for a
future Swarm migration. For single-host zero-downtime deployments, use:

```bash
./scripts/zero_downtime_deploy.sh
```

The `smdg` container intentionally starts its entrypoint as root because it has
to read Docker secrets, initialize `/app/keys/age.key`, create writable runtime
directories and fix volume ownership. The application process itself is then
started as the unprivileged `smdg` user via `gosu smdg` in
[`entrypoint.sh`](../../entrypoint.sh).

### Required production environment

Set these values in `.env` before starting the production compose stack:

```bash
DOMAIN=example.com
REDIS_PASSWORD=<long-random-password>
DOCKER_USERNAME=<registry-user-or-org>
IMAGE_TAG=<immutable-image-tag>
GIT_SHA=<git-sha-for-metrics>
```

`DATABASE_URL` is normally not set manually for the Docker production stack.
[`entrypoint.sh`](../../entrypoint.sh) builds it from the Docker secret
`postgres_password`, so the PostgreSQL password has one source of truth.

### Required local secret files

Create the secret files on the production host before `docker compose up`.
They must not be committed to git.

```bash
mkdir -p secrets
printf '%s' '<48+ chars jwt secret>' > secrets/jwt_secret.txt
printf '%s' '<initial admin password>' > secrets/admin_password.txt
printf '%s' '<postgres password>' > secrets/postgres_password.txt
printf '%s' '<age private key>' > secrets/age.key
printf '%s' '<grafana admin password>' > secrets/grafana_password.txt
bash scripts/generate-htpasswd.sh jaeger <username>
bash scripts/generate-htpasswd.sh prometheus <username>
```

The compose files reference these secrets by name:
`jwt_secret_key`, `admin_password`, `postgres_password`, `age_private_key`,
`grafana_password`, `secrets/.htpasswd-jaeger` and
`secrets/.htpasswd-prometheus`.

### Health and readiness contract

Use different endpoints for different layers:

- Docker container healthcheck: `/health/live`
- External load balancer / orchestrator readiness: `/health/ready`
- Nginx self-check only: `/healthz`
- Human/API compatibility health summary: `/health`

`/health/live` only proves that the process answers HTTP. It must not check
PostgreSQL, Redis or storage, otherwise a dependency outage would cause
unnecessary container restarts. `/health/ready` checks shutdown state,
overload, database, Redis, storage and optional DICOM viewer readiness; route
production traffic based on this endpoint.

Post-deploy smoke checks:

```bash
curl -fsS http://localhost/healthz
curl -kfsS https://${DOMAIN}/health/live
curl -kfsS https://${DOMAIN}/health/ready
curl -kfsS https://${DOMAIN}/health
curl -fsSI http://${DOMAIN} | grep -i '^location: https://'
```

### TLS certificates

The repository contains localhost certificates only for development. In
production, mount certificates for the real domain into `./certs` and point
Nginx at them. The current Nginx configs expect certificate files under
`/etc/nginx/certs`; use one of these approaches:

- copy/symlink the domain certificate and key to the filenames used by the
  active Nginx config;
- or update `ssl_certificate` / `ssl_certificate_key` to your mounted
  `fullchain.pem` / `privkey.pem` paths.

If using the built-in ACME webroot flow, mount challenges at
`./certbot/www:/var/www/certbot` and keep `/.well-known/acme-challenge/`
reachable on HTTP. If TLS is terminated by a cloud load balancer or external
reverse proxy, keep this compose Nginx internal and configure certificates
there instead.

Enable HSTS preload only after the real domain and all subdomains are verified
to be HTTPS-only. The default Nginx configs intentionally avoid `preload` to
reduce the risk of locking a new domain into an irreversible browser policy too
early.

### Future Kubernetes probe mapping

Kubernetes manifests are not part of the current Docker Compose deployment.
When migrating later, use the same probe contract:

```yaml
livenessProbe:
  httpGet:
    path: /health/live
    port: 8000
readinessProbe:
  httpGet:
    path: /health/ready
    port: 8000
startupProbe:
  httpGet:
    path: /health/live
    port: 8000
  failureThreshold: 30
  periodSeconds: 2
```

## Russia (`russia`)

- Local storage (`S3_ENABLED=false`).
- Mandatory 2FA enforced at the login policy level.
- Audit retention: 1095 days (`AUDIT_3_YEARS` in the feature matrix).
- GOST crypto profile (`GOST_CRYPTO`): currently a wrapper around `age` —
  replace with a certified provider before going to production.

```bash
docker build --build-arg DEPLOYMENT_TYPE=russia -t smdg:russia .
docker compose -f docker-compose.yml -f docker-compose.russia.yml up -d
```

## International (`intl`)

- S3 / MinIO, DICOM Viewer, GDPR-oriented features enabled in the matrix.

```bash
DEPLOYMENT_TYPE=intl docker compose up -d
```

Use the overlay `docker-compose.intl.yml` to apply resource limits.

## Single tenant (`single`)

- One default tenant, simplified admin panel (`SIMPLE_ADMIN`), local storage
  by default.
- With `MULTI_TENANCY` disabled, the `super_admin` role cannot switch
  organisation through the `Host` or `X-Tenant-*` headers: the context
  always resolves to the tenant with `tenant_default_subdomain` (same as
  other roles). This prevents hidden multi-tenancy in the single profile.

```bash
docker compose -f docker-compose.yml -f docker-compose.single.yml up -d
```

If `.env` already enables S3 with valid credentials, the application keeps
backwards compatibility and continues to use S3.

## SaaS (`saas`)

- Multi-tenancy, billing and white-label enabled in the matrix; a working
  S3 backend is required outside dev.

```bash
docker compose -f docker-compose.yml -f docker-compose.saas.yml up -d
```

## Horizontal scaling (stateless cluster)

Use `docker-compose.scale.yml` when you need multiple app replicas behind
an Nginx load balancer.

### Architecture requirements

- Keep app nodes stateless.
- Store sessions, cache and job queue in Redis:
  - `HORIZONTAL_SCALING_REDIS_SESSION_URL`
  - `HORIZONTAL_SCALING_REDIS_CACHE_URL`
  - `HORIZONTAL_SCALING_REDIS_JOB_QUEUE_URL`
- Use shared object storage (`S3`/`MinIO`) for uploaded files.
- Route traffic through `nginx-lb` (`nginx/nginx-load-balancer.conf`).

### Start and scale

```bash
# Start baseline cluster (ports: 18080 HTTP, 18443 HTTPS)
docker compose -p smdg-scale -f docker-compose.scale.yml up -d

# Scale app replicas to 3
docker compose -p smdg-scale -f docker-compose.scale.yml up -d --scale smdg=3

# Or use helper script
./scripts/scale.sh 3
```

### Verify readiness and balancing

```bash
# Cluster readiness through load balancer
curl -k https://localhost:18443/health/ready

# Confirm requests are distributed across replicas
for i in {1..30}; do
  curl -ks https://localhost:18443/health/ready | jq -r '.instance_id'
done | sort | uniq -c
```

Use `/health/live` for liveness probes, `/health/ready` for orchestrator routing,
and `/health/metrics` for per-instance operational metrics.

### Blue/green cutover

**Scaled cluster** (`smdg-scale`, `docker-compose.scale.yml`): use
`./scripts/cutover.sh` to copy upstream snippets from `nginx/upstreams/`
into `nginx/nginx-load-balancer.conf`, validate, and reload the `nginx-lb`
container. Modes: `status`, `blue` (all replicas), `green <n>` (pin to
replica *n*), `canary`, `rollback`.

```bash
./scripts/cutover.sh status
./scripts/cutover.sh blue
./scripts/cutover.sh green 2
```

`./scripts/deploy.sh` builds the app service and, when healthy, runs
`./scripts/cutover.sh green <instance>` to shift traffic to that replica.

**Include-based** cutover (Nginx with `include ... upstream-target.conf` and
`proxy_pass $smdg_upstream;` layout):

```bash
./scripts/cutover_include.sh blue
./scripts/cutover_include.sh green
```

**Edge** in-container upstream swap (single edge container, no scale compose file):

```bash
EDGE_NGINX_CONTAINER=smdg-nginx-1 ./scripts/cutover_edge.sh
```

The include and edge scripts validate Nginx, reload, run post-cutover health
checks, and auto-roll back on failure (see their headers for environment
variables).

For a dedicated rollback procedure, see
[`docs/runbooks/rollback-to-baseline.md`](../runbooks/rollback-to-baseline.md).

## Migrating from an older version

1. Set `DEPLOYMENT_TYPE` (for the current docker stack with MinIO the
   recommended value is `intl`).
2. Run `python scripts/migrate_deployment_type.py --target <type>` for a
   migration checklist.
3. Restart the services.

`.env` templates: `.env.<profile>.example` in the repository root.

## Operations runbooks

For production operations and incidents, use the runbook index:

- Main index: [`docs/runbooks/README.md`](../runbooks/README.md)

Daily/periodic operations:

- Daily checks: [`docs/runbooks/operations/daily-checks.md`](../runbooks/operations/daily-checks.md)
- Weekly maintenance: [`docs/runbooks/operations/weekly-maintenance.md`](../runbooks/operations/weekly-maintenance.md)
- Monthly tasks: [`docs/runbooks/operations/monthly-tasks.md`](../runbooks/operations/monthly-tasks.md)
- Backup and recovery: [`docs/runbooks/operations/backup-recovery.md`](../runbooks/operations/backup-recovery.md)

Component playbooks:

- API: [`docs/runbooks/components/smdg-api.md`](../runbooks/components/smdg-api.md)
- PostgreSQL: [`docs/runbooks/components/smdg-database.md`](../runbooks/components/smdg-database.md)
- Redis: [`docs/runbooks/components/smdg-redis.md`](../runbooks/components/smdg-redis.md)
- Storage (S3/MinIO/local): [`docs/runbooks/components/smdg-storage.md`](../runbooks/components/smdg-storage.md)
- DICOM: [`docs/runbooks/components/smdg-dicom.md`](../runbooks/components/smdg-dicom.md)
- Auth: [`docs/runbooks/components/smdg-auth.md`](../runbooks/components/smdg-auth.md)
- Audit: [`docs/runbooks/components/smdg-audit.md`](../runbooks/components/smdg-audit.md)
- Webhooks: [`docs/runbooks/components/smdg-webhooks.md`](../runbooks/components/smdg-webhooks.md)

Key incidents:

- High CPU: [`docs/runbooks/incidents/high-cpu.md`](../runbooks/incidents/high-cpu.md)
- High memory: [`docs/runbooks/incidents/high-memory.md`](../runbooks/incidents/high-memory.md)
- DB connection limit: [`docs/runbooks/incidents/db-connection-limit.md`](../runbooks/incidents/db-connection-limit.md)
- Disk full: [`docs/runbooks/incidents/disk-full.md`](../runbooks/incidents/disk-full.md)
