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
