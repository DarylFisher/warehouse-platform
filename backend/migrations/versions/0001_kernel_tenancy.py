"""Kernel schema: tenants, sites and row level security.

Revision ID: 0001
Revises:
Create Date: 2026-11-26

Tenancy rules established here, which every later tenant-scoped table follows:

* every tenant-scoped table has ``tenant_id`` and RLS ENABLED and FORCED;
* the policy compares ``tenant_id`` with ``kernel.current_tenant_id()``, which
  reads the transaction-local setting ``app.tenant_id``;
* with no tenant set, a query sees no rows and cannot insert any;
* the app role gets explicit grants per table, never default privileges, so a
  table can't be exposed before its policy exists.
"""

import os
from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = os.environ.get("WAP_APP_ROLE", "wap_app")


def upgrade() -> None:
    op.execute("CREATE SCHEMA kernel")
    op.execute(f"GRANT USAGE ON SCHEMA kernel TO {APP_ROLE}")

    op.execute(
        """
        CREATE FUNCTION kernel.current_tenant_id() RETURNS uuid
        LANGUAGE sql STABLE
        AS $$ SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid $$
        """
    )

    op.execute(
        """
        CREATE TABLE kernel.tenants (
            id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            slug        text NOT NULL UNIQUE
                        CHECK (slug ~ '^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$'),
            name        text NOT NULL,
            status      text NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'suspended')),
            created_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    # Not FORCED: the owner manages tenants; the app role sees only its own row.
    op.execute("ALTER TABLE kernel.tenants ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_self ON kernel.tenants
        USING (id = kernel.current_tenant_id())
        """
    )

    op.execute(
        """
        CREATE FUNCTION kernel.resolve_tenant(p_slug text)
        RETURNS TABLE (id uuid, name text)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, kernel
        AS $$
            SELECT t.id, t.name FROM kernel.tenants t
            WHERE t.slug = p_slug AND t.status = 'active'
        $$
        """
    )

    op.execute(
        """
        CREATE TABLE kernel.sites (
            id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   uuid NOT NULL REFERENCES kernel.tenants (id),
            code        text NOT NULL,
            name        text NOT NULL,
            created_at  timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, code)
        )
        """
    )
    op.execute("ALTER TABLE kernel.sites ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE kernel.sites FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON kernel.sites
        USING (tenant_id = kernel.current_tenant_id())
        WITH CHECK (tenant_id = kernel.current_tenant_id())
        """
    )

    op.execute("REVOKE ALL ON FUNCTION kernel.resolve_tenant(text) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION kernel.resolve_tenant(text) TO {APP_ROLE}")
    op.execute(f"GRANT EXECUTE ON FUNCTION kernel.current_tenant_id() TO {APP_ROLE}")
    op.execute(f"GRANT SELECT ON kernel.tenants TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON kernel.sites TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP SCHEMA kernel CASCADE")
