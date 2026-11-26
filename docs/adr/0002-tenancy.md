# ADR 0002: Tenancy with shared tables and forced row level security

- Status: accepted
- Date: 2026-11-26

## Decision

Pooled tenancy: shared tables with a `tenant_id` column, protected by Postgres
row level security.

- RLS is ENABLED and FORCED on every tenant-scoped table, so even the owner
  must set a tenant to read or write rows.
- Policies compare `tenant_id` with `kernel.current_tenant_id()`, which reads
  the transaction-local setting `app.tenant_id`. With no tenant set, queries
  return nothing and inserts fail.
- The application connects as `wap_app`: not an owner, not a superuser, no
  BYPASSRLS. It can't alter tables or disable policies.
- Tenant lookup by slug goes through `kernel.resolve_tenant`, a SECURITY
  DEFINER function, because `wap_app` can't read `kernel.tenants` unscoped.
- `kernel.tenants` itself is RLS-enabled but not forced, so the owner can
  manage tenants while the app sees only its current tenant's row.
- The app role is granted per table, never via default privileges.
- Large customers can later get a dedicated database (silo tier) from the same code.

## Considered

- Schema per tenant: real per-tenant columns, but migrations across many schemas get slow and fragile.
- Database per tenant only: strong isolation, but cost and fleet management from day one.

## Consequences

- Every new tenant-scoped table needs its policy and isolation tests.
- ClickHouse has no RLS: `tenant_id` leads every sort key and the query API enforces the filter.
