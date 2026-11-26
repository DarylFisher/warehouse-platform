# Warehouse Application Platform

Multi-tenant SaaS platform for building warehouse applications from declarative
definitions, with Python plugins, durable flows and ClickHouse analytics.

- Architecture: see `docs/adr/` and the architecture options doc linked in `docs/PLAN.md`
- Plan and current status: `docs/PLAN.md`

## Prerequisites

- Docker Desktop (Windows: use the WSL2 backend and keep the repo inside the WSL2 filesystem)
- [uv](https://docs.astral.sh/uv/) and [just](https://github.com/casey/just)

## Quick start

```bash
cp .env.example .env
just up        # Postgres, ClickHouse, Keycloak, migrations, API
just seed      # two demo tenants with sample sites
just test      # lint, type check, unit + integration tests
```

Then open:

| Service | URL |
| --- | --- |
| API docs | http://localhost:8100/docs |
| Readiness | http://localhost:8100/health/ready |
| ClickHouse HTTP | http://localhost:8123/play |
| Keycloak admin | http://localhost:8180 (admin / admin) |

Try tenant isolation. The API needs a Keycloak access token; the dev realm has
`north.admin`, `south.admin` and `ops.both` (member of both tenants), all with
password `password`:

```bash
curl -H "Authorization: Bearer $(just token north.admin)" http://localhost:8100/api/sites
curl -H "Authorization: Bearer $(just token south.admin)" http://localhost:8100/api/sites
```

`just seed` makes `north.admin` and `south.admin` admins of their tenants, and
`ops.both` a viewer in `demo-north` and an operator in `demo-south`. Anyone else
who signs in gets no roles until an admin grants one (`PUT /api/users/{id}/roles`).
`GET /api/me/access` shows your roles and permissions in the current tenant.

Keycloak imports the dev realm only when its container is created. After the
realm file changes, run `just down && just up` (Keycloak keeps no volume, so
this re-imports it), then `just seed`.

The tenant comes from the token's `tenant-<slug>` groups. A user in several
tenants picks one with `X-Tenant`, which must name a tenant the token grants:

```bash
curl -H "Authorization: Bearer $(just token ops.both)" -H "X-Tenant: demo-south" \
  http://localhost:8100/api/sites
```

## Ports

Chosen to avoid 5432, 8080 and 8765, which other local stacks already use.

| Service | Host port |
| --- | --- |
| Postgres | 5433 |
| ClickHouse HTTP / native | 8123 / 9002 |
| Keycloak | 8180 |
| API | 8100 |

## Running the backend outside Docker

```bash
just deps            # start only Postgres, ClickHouse, Keycloak
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn wap.api.main:app --reload --port 8100
```
