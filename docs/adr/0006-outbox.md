# ADR 0006: Transactional outbox, relayed to ClickHouse by a dedicated role

- Status: accepted
- Date: 2026-11-27

## Decision

Events that leave Postgres go through `kernel.outbox`, written in the same
transaction as the change they describe. A relay ships committed events to
ClickHouse `wap.platform_events`.

- **Two sources, one path.** App code calls `wap.kernel.outbox.emit(conn,
  "site.created", {...})` on the request's tenant transaction. Every audit
  entry becomes an `audit.recorded` event via a trigger on `kernel.audit_log`,
  so audit history reaches ClickHouse the same way (ADR 0005). The audit event
  reuses the audit entry's id.
- **Tenant-scoped like everything else.** The outbox has `tenant_id` and forced
  RLS. The app role may only INSERT, for the current tenant; it can't read or
  change events. Event types are dotted lower-case names, checked in code and
  by a constraint.
- **A dedicated relay role.** The relay must read every tenant's events, which
  the app role can't. `wap_relay` (no BYPASSRLS) gets explicit RLS policies on
  `kernel.outbox` only: read any row, and update just `published_at`,
  `attempts` and `last_error`. It has no grant on any other table. The app
  never connects as the owner (CLAUDE.md rule 2), and neither does the relay.
- **At-least-once, idempotent at the sink.** The relay locks a batch with
  `FOR UPDATE SKIP LOCKED`, inserts it into ClickHouse, then marks it
  published in the same transaction. A crash between the two resends the
  batch; `platform_events` is a ReplacingMergeTree whose key includes the event
  id, so resends collapse. Several relays can run side by side.
- **Failures back off.** A failed insert records `attempts` and `last_error`
  and leaves the events pending; the worker retries with exponential backoff
  up to 30 s.
- **Runs as its own process.** `python -m wap.cli.relay` (`just relay` on the
  host, the `worker` service in Docker), polling every second when idle.
- **The outbox and audit log are not audited themselves**, which would recurse.

## Considered

- Writing to ClickHouse from request handlers: not transactional, so events
  could be lost or describe changes that rolled back.
- CDC (logical replication of business tables) instead of an outbox: planned
  for analytics in M5 (ClickPipes), but it ships table changes, not
  domain events, and needs a replication slot. The outbox works without it.
- A SECURITY DEFINER function for the relay instead of a role: the owner is
  bound by forced RLS too, so it would still need a cross-tenant policy, and
  the relay would run with owner rights.
- LISTEN/NOTIFY to wake the relay: lower latency, but polling is simpler and
  enough for now; it can be added without changing the table.

## Consequences

- Existing Postgres volumes need the new role: `just db-roles` (the init script
  is now idempotent). CI and fresh volumes get it automatically.
- Published rows stay in the outbox for now; a retention job will trim them
  (and old audit entries) once ClickHouse holds the history.
- Audit entries written before this migration are not backfilled into the
  outbox.
- Consumers read `wap.platform_events`; per-event-type ClickHouse tables come
  with analytics in M5.
