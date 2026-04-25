# SMDG deployment profiles

The environment variable **`DEPLOYMENT_TYPE`** accepts one of:
`russia` | `intl` | `single` | `saas`.

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
