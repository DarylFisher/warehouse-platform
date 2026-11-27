"""Users, roles and role assignments.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-26

* ``kernel.roles`` is a global catalogue of built-in roles: the same for every
  tenant, readable by the app and never writable by it, so no tenant can grant
  itself new permissions.
* ``kernel.users`` and ``kernel.user_roles`` are tenant-scoped with forced RLS,
  like every tenant table. A person in two tenants has a user row in each,
  keyed by the token's issuer and subject.
* ``user_roles`` references ``users (tenant_id, id)``, so a role assignment can
  only ever point at a user in the same tenant.
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = os.environ.get("WAP_APP_ROLE", "wap_app")

# Keep in step with wap.kernel.access.permissions.Permission.
BUILT_IN_ROLES = [
    (
        "admin",
        "Administrator",
        "Everything, including users and roles",
        ["sites.read", "sites.write", "users.read", "users.manage"],
    ),
    ("operator", "Operator", "Day-to-day warehouse operations", ["sites.read", "sites.write"]),
    ("viewer", "Viewer", "Read-only access", ["sites.read"]),
]


def _tenant_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table}
        USING (tenant_id = kernel.current_tenant_id())
        WITH CHECK (tenant_id = kernel.current_tenant_id())
        """
    )


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE kernel.roles (
            key          text PRIMARY KEY CHECK (key ~ '^[a-z][a-z0-9_]{0,39}$'),
            name         text NOT NULL,
            description  text NOT NULL DEFAULT '',
            permissions  text[] NOT NULL
        )
        """
    )
    insert = sa.text(
        "INSERT INTO kernel.roles (key, name, description, permissions) "
        "VALUES (:key, :name, :description, :permissions)"
    )
    for key, name, description, permissions in BUILT_IN_ROLES:
        op.get_bind().execute(
            insert,
            {"key": key, "name": name, "description": description, "permissions": permissions},
        )

    op.execute(
        """
        CREATE TABLE kernel.users (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     uuid NOT NULL REFERENCES kernel.tenants (id),
            issuer        text NOT NULL,
            subject       text NOT NULL,
            email         text,
            name          text,
            status        text NOT NULL DEFAULT 'active'
                          CHECK (status IN ('active', 'disabled')),
            created_at    timestamptz NOT NULL DEFAULT now(),
            last_seen_at  timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, issuer, subject),
            UNIQUE (tenant_id, id)
        )
        """
    )
    _tenant_rls("kernel.users")

    op.execute(
        """
        CREATE TABLE kernel.user_roles (
            tenant_id   uuid NOT NULL,
            user_id     uuid NOT NULL,
            role_key    text NOT NULL REFERENCES kernel.roles (key),
            granted_at  timestamptz NOT NULL DEFAULT now(),
            granted_by  uuid,
            PRIMARY KEY (tenant_id, user_id, role_key),
            FOREIGN KEY (tenant_id, user_id) REFERENCES kernel.users (tenant_id, id)
                ON DELETE CASCADE,
            FOREIGN KEY (tenant_id, granted_by) REFERENCES kernel.users (tenant_id, id)
        )
        """
    )
    op.execute("CREATE INDEX user_roles_tenant_role ON kernel.user_roles (tenant_id, role_key)")
    _tenant_rls("kernel.user_roles")

    op.execute(f"GRANT SELECT ON kernel.roles TO {APP_ROLE}")
    # No DELETE on users: disable them instead, so audit history keeps its actor.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON kernel.users TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, DELETE ON kernel.user_roles TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP TABLE kernel.user_roles")
    op.execute("DROP TABLE kernel.users")
    op.execute("DROP TABLE kernel.roles")
