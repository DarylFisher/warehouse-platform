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
| M1 | Kernel: tenancy, OIDC identity, audit, outbox, staging on Fly.io | Started: tenancy done |
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
- [ ] OIDC login: validate Keycloak tokens, map `groups` claim `tenant-<slug>` to tenant; retire `X-Tenant`
- [ ] Users and roles tables; permission checks on routes
- [ ] Audit writer (actor, tenant, before/after) on every write
- [ ] Transactional outbox table and relay skeleton to `wap.platform_events`
- [ ] Staging on Fly.io

## Session notes

- 2026-11-26: M0 built and verified (24 tests passing against Postgres 16 and ClickHouse 25.8 run natively; the Docker images themselves were not run in the build environment, so the first `just up` on a workstation is the first real container run).
