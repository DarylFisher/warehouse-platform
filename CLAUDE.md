# CLAUDE.md

Guidance for Claude Code sessions in this repo. Read `docs/PLAN.md` first: it
holds the milestone plan and where work stopped.

## What this is

A multi-tenant SaaS platform for warehouse applications. A small kernel
(tenancy, identity, metadata, migrations, audit, outbox) hosts apps defined as
declarative metadata plus sandboxed Python plugins. Postgres is the system of
record; ClickHouse holds analytics and audit history. Production: Fly.io for the
app tier, ClickHouse Managed Postgres and ClickHouse Cloud for data.

## Commands

All from the repo root unless noted (`just --list` shows everything):

- `just up` / `just down` / `just reset-db`: local stack in Docker
- `just run`: API on the host with hot reload (after `just deps`)
- `just deps`: only Postgres, ClickHouse, Keycloak (run the API on the host)
- `just seed`: demo tenants `demo-north` and `demo-south`
- `just token <user>`: dev access token (`north.admin`, `south.admin`, `ops.both`)
- `just test`: ruff, pyright (strict), pytest including integration tests
- `just fmt`: format and auto-fix

Integration tests need `WAP_TEST_DATABASE_URL` and
`WAP_TEST_MIGRATION_DATABASE_URL` (see `.env.example`); without them they skip.

## Rules that must not be broken

1. **Tenant isolation.** Every tenant-scoped table has `tenant_id`, RLS ENABLED
   and FORCED, and a policy on `kernel.current_tenant_id()`. Grant the app role
   per table, never through default privileges. Attach the audit trigger
   (`wap.kernel.audit.attach_sql`, ADR 0005). Add tests to
   `tests/test_tenant_isolation.py` for every new tenant-scoped table.
2. **The app connects as `wap_app`**, never as the owner. Migrations and seeds
   use `WAP_MIGRATION_DATABASE_URL` (`wap_owner`).
3. **Set the tenant only with `wap.db.tenant_transaction`**, which uses a
   transaction-local setting so it cannot leak through the pool.
4. **The tenant comes only from the verified token's `tenant-<slug>` groups**
   (ADR 0003). Routes get it through `TenantDep` / `TenantConn`; never read a
   tenant from the request body or an unchecked header.
5. **Every tenant route declares a permission** with
   `Depends(require(Permission.X))` (ADR 0004). New permissions go in
   `wap.kernel.access.Permission` and the built-in roles migration together.
6. **No tenant filter needed in queries**: RLS supplies it. Do not add
   `WHERE tenant_id = ...` as a substitute for RLS.
7. **Kernel tables are Alembic migrations** in `backend/migrations/versions/`.
   App-defined tables (M2 onwards) come from the platform migration engine,
   never Alembic.
8. **ClickHouse tables lead their sort key with `tenant_id`.**
9. Python 3.13, strict pyright, ruff. Keep `just test` green before finishing.

## Layout

- `backend/src/wap/kernel/`: tenancy, identity, access and audit now; metadata, migrations, outbox next
- `backend/src/wap/api/`: FastAPI routers and dependencies
- `backend/src/wap/cli/`: seed and maintenance commands
- `docker/`: init scripts for Postgres, ClickHouse and the Keycloak dev realm
- `docs/adr/`: architecture decisions; add one for each significant choice
- `scripts/`: cloud environment setup script and the SessionStart hook

## Cloud sessions

The SessionStart hook runs `uv sync` and starts dockerd in cloud sessions.
In cloud sessions the justfile also loads `docker-compose.cloud.yml`, which
passes the session proxy CA into image builds and lowers the ClickHouse file
limit to fit the sandbox. Containers are not started automatically: run `just deps` (or `just up`)
before integration tests. Work on a branch and open a pull request; CI must pass.

## Local ports

Postgres 5433, ClickHouse 8123/9002, Keycloak 8180, API 8100. Avoid 5432,
8080 and 8765, which other local stacks on the developer's machine use.
