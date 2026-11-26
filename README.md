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

Try tenant isolation:

```bash
curl -H "X-Tenant: demo-north" http://localhost:8100/api/sites
curl -H "X-Tenant: demo-south" http://localhost:8100/api/sites
```

The `X-Tenant` header is a development stand-in until OIDC login lands in M1.

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
