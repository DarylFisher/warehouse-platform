"""Transactional outbox, fed by the app and by every audit entry.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-27

* ``kernel.outbox`` is tenant-scoped with forced RLS. Events are written in the
  same transaction as the change they describe, so an event exists exactly when
  its change committed.
* The app role may only INSERT (through ``wap.kernel.outbox.emit``), and only
  for the current tenant. It can't read or change events.
* The relay role ``wap_relay`` reads and marks events of every tenant through
  explicit policies, and has no access to any other table.
* Every audit entry becomes an ``audit.recorded`` event, so audit history
  reaches ClickHouse through the same path.
* The outbox and the audit log are not themselves audited (that would recurse).
"""

import os
from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = os.environ.get("WAP_APP_ROLE", "wap_app")
RELAY_ROLE = os.environ.get("WAP_RELAY_ROLE", "wap_relay")


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE kernel.outbox (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     uuid NOT NULL REFERENCES kernel.tenants (id),
            event_type    text NOT NULL
                          CHECK (event_type ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$'),
            occurred_at   timestamptz NOT NULL DEFAULT clock_timestamp(),
            payload       jsonb NOT NULL,
            published_at  timestamptz,
            attempts      integer NOT NULL DEFAULT 0,
            last_error    text
        )
        """
    )
    # The relay's queue: unpublished events, oldest first.
    op.execute(
        "CREATE INDEX outbox_pending ON kernel.outbox (occurred_at) WHERE published_at IS NULL"
    )
    op.execute("ALTER TABLE kernel.outbox ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE kernel.outbox FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON kernel.outbox
        USING (tenant_id = kernel.current_tenant_id())
        WITH CHECK (tenant_id = kernel.current_tenant_id())
        """
    )
    # The relay works across tenants, on this table only.
    op.execute(f"CREATE POLICY relay_read ON kernel.outbox FOR SELECT TO {RELAY_ROLE} USING (true)")
    op.execute(
        f"CREATE POLICY relay_mark ON kernel.outbox FOR UPDATE TO {RELAY_ROLE} "
        "USING (true) WITH CHECK (true)"
    )

    op.execute(
        """
        CREATE FUNCTION kernel.audit_to_outbox() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, kernel
        AS $$
        BEGIN
            INSERT INTO kernel.outbox (id, tenant_id, event_type, occurred_at, payload)
            VALUES (NEW.id, NEW.tenant_id, 'audit.recorded', NEW.occurred_at, to_jsonb(NEW));
            RETURN NULL;
        END
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION kernel.audit_to_outbox() FROM PUBLIC")
    op.execute(
        """
        CREATE TRIGGER to_outbox AFTER INSERT ON kernel.audit_log
        FOR EACH ROW EXECUTE FUNCTION kernel.audit_to_outbox()
        """
    )

    op.execute(f"GRANT INSERT ON kernel.outbox TO {APP_ROLE}")
    op.execute(f"GRANT USAGE ON SCHEMA kernel TO {RELAY_ROLE}")
    op.execute(f"GRANT SELECT ON kernel.outbox TO {RELAY_ROLE}")
    op.execute(
        f"GRANT UPDATE (published_at, attempts, last_error) ON kernel.outbox TO {RELAY_ROLE}"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER to_outbox ON kernel.audit_log")
    op.execute("DROP FUNCTION kernel.audit_to_outbox()")
    op.execute("DROP TABLE kernel.outbox")
    op.execute(f"REVOKE USAGE ON SCHEMA kernel FROM {RELAY_ROLE}")
