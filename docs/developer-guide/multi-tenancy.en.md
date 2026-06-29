# Multi-tenancy

Data isolation model in SMDG.

## Model

Default: **shared database** — all tenants in one PostgreSQL, isolation via `tenant_id` on `User` and `File` rows.

## Tenant resolution

1. **Subdomain** in the `Host` header (e.g. `clinic1.example.com`).
2. JWT carries `tenant_id` after login.
3. Middleware validates Host vs JWT consistency.

```bash
TENANT_DEFAULT_SUBDOMAIN=default
TENANT_RESOLVE_LOCALHOST_AS_DEFAULT=true
```

## Roles

| Role | Tenant scope |
|------|--------------|
| `user`, `doctor`, `admin` | Own tenant only |
| `super_admin` | Cross-tenant (`saas` profile) |

## Storage

Files are logically partitioned by metadata (`tenant_id` in DB). On disk/S3 — shared bucket with application-defined prefixes/paths.

## Profiles

| Profile | Multi-tenant |
|---------|--------------|
| `single` | No (single tenant) |
| `saas` | Yes |
| `russia`, `intl`, `demo` | Optional |

Check: `GET /health/deployment`.

## API

All write endpoints are automatically scoped to the tenant from JWT/Host.

See [src/MULTI_TENANCY.md](../src/MULTI_TENANCY.md).

## Runbook

Cross-tenant access incident: [runbooks/cross-tenant-access.md](../runbooks/cross-tenant-access.md).
