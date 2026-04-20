# Multi-tenancy

> **Translation status:** English stub. The authoritative Russian
> reference is [`docs/locales/ru/MULTI_TENANCY.md`](../locales/ru/MULTI_TENANCY.md).

## Model

SMDG supports single-tenant and multi-tenant deployments. A `Tenant`
row represents an isolated organisation and owns users, files and
audit records.

Tenancy is resolved from the following sources (in order):

1. `X-Tenant-ID` header (administrative API calls).
2. `X-Tenant-Subdomain` header.
3. `Host` header subdomain (`<subdomain>.example.com`).
4. `tenant_id` claim from the JWT.
5. Default tenant (`tenant_default_subdomain`).

## Feature matrix

Multi-tenancy is controlled by the `multi_tenancy` feature flag:

- `saas` — enabled by default.
- `single`, `russia`, `intl` — disabled; a single default tenant is
  created at startup and every request maps to it.

When disabled, even the `super_admin` role cannot switch organisation
through headers (see [DEPLOYMENT.md](DEPLOYMENT.md)).

## Database

Every tenant-scoped table has a `tenant_id` column and a composite
index `(tenant_id, <natural key>)`. Queries are filtered by
`request.state.tenant_id` through the async SQLAlchemy session, which
is set up by the `set_user_context` middleware in `app/main.py`.

## Administration

- `super_admin` can list, create, suspend and delete tenants via the
  admin API (`/api/admin/tenants`, SaaS profile only).
- Per-tenant quotas and branding live in `Tenant.settings` (JSON).

## White-label

In the `saas` profile the `white_label` feature flag enables per-tenant
branding: logo URL, primary colour, custom legal links. The frontend
reads these values from `/api/tenant/me` on page load and applies them
before the i18n runtime renders translated strings.
