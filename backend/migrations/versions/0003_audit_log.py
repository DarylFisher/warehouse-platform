"""Audit log, written by trigger in the same transaction as each change.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-27

* ``kernel.audit_log`` is tenant-scoped with forced RLS. The app role may only
  read it: rows are written by ``kernel.audit_row()``, a SECURITY DEFINER
  trigger, so the app can't forge or remove entries.
* Rows are never updated or deleted, by anyone: a trigger refuses it.
* The actor comes from transaction-local settings that ``tenant_transaction``
  sets: ``app.actor_user_id`` and ``app.actor_subject``.
* Audited tables get the trigger through ``wap.kernel.audit.attach_sql``, the
  same SQL the platform migration engine will use for app tables (M2).
"""

import os
from collections.abc import Sequence

from alembic import op

from wap.kernel.audit import attach_sql, detach_sql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = os.environ.get("WAP_APP_ROLE", "wap_app")

# (table, columns whose changes alone are not worth an entry)
AUDITED = [
    ("kernel.sites", []),
    ("kernel.users", ["last_seen_at"]),
    ("kernel.user_roles", []),
]


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE kernel.audit_log (
            id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id      uuid NOT NULL REFERENCES kernel.tenants (id),
            -- clock_timestamp, not now(): entries in one transaction keep their order.
            occurred_at    timestamptz NOT NULL DEFAULT clock_timestamp(),
            txid           bigint NOT NULL DEFAULT txid_current(),
            actor_user_id  uuid,
            actor_subject  text,
            action         text NOT NULL CHECK (action IN ('insert', 'update', 'delete')),
            table_name     text NOT NULL,
            row_id         text,
            before         jsonb,
            after          jsonb
        )
        """
    )
    op.execute(
        "CREATE INDEX audit_log_tenant_time ON kernel.audit_log (tenant_id, occurred_at DESC)"
    )
    op.execute(
        "CREATE INDEX audit_log_tenant_row ON kernel.audit_log (tenant_id, table_name, row_id)"
    )
    op.execute("ALTER TABLE kernel.audit_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE kernel.audit_log FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON kernel.audit_log
        USING (tenant_id = kernel.current_tenant_id())
        WITH CHECK (tenant_id = kernel.current_tenant_id())
        """
    )

    op.execute(
        """
        CREATE FUNCTION kernel.audit_log_is_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'kernel.audit_log is append-only';
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_append_only
        BEFORE UPDATE OR DELETE ON kernel.audit_log
        FOR EACH ROW EXECUTE FUNCTION kernel.audit_log_is_append_only()
        """
    )

    # Runs as the owner, so the app role needs no INSERT on audit_log. RLS still
    # applies (forced), so an entry can only land in the current tenant.
    op.execute(
        """
        CREATE FUNCTION kernel.audit_row() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, kernel
        AS $$
        DECLARE
            old_row  jsonb := CASE WHEN TG_OP <> 'INSERT' THEN to_jsonb(OLD) END;
            new_row  jsonb := CASE WHEN TG_OP <> 'DELETE' THEN to_jsonb(NEW) END;
            ignored  text[] := coalesce(TG_ARGV, '{}');
        BEGIN
            IF TG_OP = 'UPDATE' AND (old_row - ignored) = (new_row - ignored) THEN
                RETURN NULL;  -- only ignored columns changed
            END IF;
            INSERT INTO kernel.audit_log
                (tenant_id, actor_user_id, actor_subject, action, table_name, row_id,
                 before, after)
            VALUES (
                (coalesce(new_row, old_row) ->> 'tenant_id')::uuid,
                NULLIF(current_setting('app.actor_user_id', true), '')::uuid,
                NULLIF(current_setting('app.actor_subject', true), ''),
                lower(TG_OP),
                TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME,
                coalesce(new_row, old_row) ->> 'id',
                old_row,
                new_row
            );
            RETURN NULL;
        END
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION kernel.audit_row() FROM PUBLIC")

    for table, ignored in AUDITED:
        op.execute(attach_sql(table, ignored))

    op.execute(f"GRANT SELECT ON kernel.audit_log TO {APP_ROLE}")

    # Rule: new permissions go in the Permission enum and the role catalogue together.
    op.execute(
        "UPDATE kernel.roles SET permissions = array_append(permissions, 'audit.read') "
        "WHERE key = 'admin' AND NOT ('audit.read' = ANY(permissions))"
    )


def downgrade() -> None:
    op.execute("UPDATE kernel.roles SET permissions = array_remove(permissions, 'audit.read')")
    for table, _ in AUDITED:
        op.execute(detach_sql(table))
    op.execute("DROP FUNCTION kernel.audit_row()")
    op.execute("DROP TABLE kernel.audit_log")
    op.execute("DROP FUNCTION kernel.audit_log_is_append_only()")
