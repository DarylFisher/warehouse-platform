# ADR 0005: Audit log written by trigger, in the same transaction

- Status: accepted
- Date: 2026-11-27

## Decision

Every insert, update and delete on an audited table is recorded in
`kernel.audit_log`, in the same Postgres transaction as the change. A change
that rolls back leaves no entry; a committed change always has one.

- **Written by trigger, not by application code.** `kernel.audit_row()` runs
  after each row change and stores the whole row before and after (`jsonb`),
  the action, the table, the row id, the transaction id and the actor. Code
  that forgets to call an audit helper can't skip it. Audited tables get the
  trigger from `wap.kernel.audit.attach_sql`, which the platform migration
  engine will reuse for app-defined tables (M2).
- **The actor comes from the transaction.** `tenant_transaction` sets the
  transaction-local settings `app.actor_user_id` and `app.actor_subject`. Request
  transactions act as the signed-in user. A first sign-in, before the user's row
  exists, records the token subject. Jobs record `system:<job>` (the seed uses
  `system:seed`).
- **Tamper-resistant.** The app role can only read the log. The trigger
  function is SECURITY DEFINER, so entries are written as the schema owner; the
  app can't forge, edit or remove them. A further trigger refuses UPDATE and
  DELETE on the log for everyone, the owner included.
- **Tenant-scoped like everything else.** The log has `tenant_id` and forced
  RLS; an entry can only be written for, and read by, the current tenant.
- **Only real changes.** An update that changes nothing, or only columns the
  table marks as ignored (`last_seen_at` on users), writes no entry. So the
  15-minute sign-in refresh and re-running the seed add nothing.
- **Order.** `occurred_at` uses `clock_timestamp()`, so entries within one
  transaction keep their order; `txid` groups them.
- **Reading.** `GET /api/audit`, filtered by table, row, actor and time, needs
  the `audit.read` permission, which only `admin` has.

## Considered

- Writing audit entries from application code: needs a call on every write
  path and is easy to miss; before-images need an extra read.
- Writing straight to ClickHouse: not transactional with the change, so a
  rolled-back change could be logged, or a committed one lost.
- Postgres logical decoding (pgaudit, CDC) as the source: sees every change but
  not the application actor without extra plumbing.

## Consequences

- Postgres holds recent audit history. The transactional outbox (next M1 step)
  and CDC (M5) ship entries to ClickHouse for long-term history and queries; a
  retention job can then trim Postgres.
- Each audited write costs one extra insert in the same transaction.
- `TRUNCATE` bypasses row triggers; the app role has no TRUNCATE privilege.
- Every new tenant-scoped table attaches the audit trigger in its migration.
