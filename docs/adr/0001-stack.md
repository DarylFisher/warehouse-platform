# ADR 0001: Core stack

- Status: accepted
- Date: 2026-11-26

## Decision

- Backend in Python 3.13 with FastAPI, Pydantic v2 and psycopg 3. App tables are
  defined at runtime, which suits Python's dynamic models; the AI and data
  ecosystem is strongest in Python; plugins are Python too.
- Modular monolith: one image, separate process groups (API, workers, plugin runner).
- Postgres is the system of record; ClickHouse for analytics, audit history and metering.
- Production on Fly.io with ClickHouse Managed Postgres and ClickHouse Cloud.
- Durable workflows on DBOS, a library that keeps state in Postgres: no extra cluster.

## Considered

- Go: smaller memory footprint and single-binary deploys, but awkward for
  runtime-defined data. Kept as an option for hot paths (RF gateway, ingest).
- Fly Managed Postgres: logical replication for CDC to ClickHouse was unconfirmed.
- Temporal: more mature, but a separate service to run.

## Consequences

- Concurrency-heavy paths may later move to Go behind the same contracts.
- Fly.io and ClickHouse Cloud regions must be co-located; measure latency early.
