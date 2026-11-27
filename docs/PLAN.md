# Plan and status

Full plan, with rationale: [Development Plan](https://claude.ai/artifact/PKYtYFxCDVBhj6BVUMKQBN).
Architecture: [Architecture Options](https://claude.ai/artifact/YBdjfyqZQt9eBy8kyRZycV).

## Decisions

- Python 3.13 backend: FastAPI, Pydantic v2, psycopg 3, SQLAlchemy Core, Alembic for kernel tables
- Durable flows and queues: DBOS Transact (Python), state in Postgres
- Production: Fly.io (app), ClickHouse Managed Postgres, ClickHouse Cloud, ClickPipes CDC
- Development: Docker containers for Postgres and ClickHouse; PeerDB optional for local CDC
- Tenancy: shared tables + `tenant_id` + forced RLS; database-per-tenant later for large customers
- Login: WorkOS in production, Keycloak locally, plain OIDC in code; badge/PIN for shared scanners
- Web: React + TypeScript + Vite, Mantine, AG Grid, TanStack Query and Router; RF client a separate PWA
- Plugins: Python, run out of process
- First app: the Work Platform (keeps Redis for ingest through the migration)

## Milestones

| | Milestone | Status |
| --- | --- | --- |
| M0 | Foundations | Done (see below) |
| M1 | Kernel: tenancy, OIDC identity, audit, outbox, staging on Fly.io | In progress: tenancy, OIDC login, users and roles done |
| M2 | Metadata runtime and migration engine | Not started |
| M3 | Flows (DBOS) and connectors | Not started |
| M4 | Plugins | Not started |
| M5 | Analytics: outbox and CDC to ClickHouse | Not started |
| M6 | Work Platform as first app, production go-live | Not started |
| M7 | AI authoring | Not started |
| M8 | RF client and app catalogue | Not started |

## M0 — done

- [x] Monorepo, uv, ruff, strict pyright, pre-commit, justfile
- [x] Docker Compose: Postgres 17 (logical WAL), ClickHouse 25.8, Keycloak dev realm, migrate, API
- [x] CI on GitHub Actions with Postgres and ClickHouse service containers
- [x] Exit test: fresh clone runs `up`, `seed`, `test` green

## M1 — next steps

- [x] Kernel schema, roles, forced RLS, tenant resolution, isolation tests (pulled forward into M0)
- [x] OIDC login: validate Keycloak tokens, map `groups` claim `tenant-<slug>` to tenant; retire `X-Tenant` ([ADR 0003](adr/0003-identity.md))
- [x] Users and roles tables; permission checks on routes ([ADR 0004](adr/0004-users-and-roles.md))
- [ ] Audit writer (actor, tenant, before/after) on every write
- [ ] Transactional outbox table and relay skeleton to `wap.platform_events`
- [ ] Staging on Fly.io

## Session notes

- 2026-11-26: M0 built and verified (24 tests passing against Postgres 16 and ClickHouse 25.8 run natively; the Docker images themselves were not run in the build environment, so the first `just up` on a workstation is the first real container run).
- 2026-11-26: `just up` fixed for cloud sessions ([#1](https://github.com/DarylFisher/warehouse-platform/pull/1)). OIDC login built: the API requires Keycloak access tokens and takes the tenant from `tenant-<slug>` groups; `X-Tenant` only picks among granted tenants. `just token <user>` prints a dev token. Verified end to end against the real Keycloak realm. Next: users and roles tables, keyed by `iss` + `sub`.
- 2026-11-26: OIDC login merged ([#2](https://github.com/DarylFisher/warehouse-platform/pull/2)). Users and roles built: tenant-scoped users provisioned on first sign-in with no roles; built-in `admin`, `operator`, `viewer` roles; routes declare permissions with `require(...)`; user and role management API; a tenant always keeps an active admin. Verified with real Keycloak tokens. Next: audit writer.
