"""Tenant users: provisioned on first sign-in, with roles granted in the platform.

Every query here runs inside ``tenant_transaction``; row level security scopes
it to the current tenant, so none of them filter on ``tenant_id``.
"""

from dataclasses import dataclass
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from wap.kernel.identity import Principal
from wap.kernel.tenancy import Tenant


class UserDisabledError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Access:
    """Who is acting, in which tenant, and what they may do there."""

    user_id: UUID
    subject: str
    tenant: Tenant
    roles: frozenset[str]
    permissions: frozenset[str]

    def can(self, permission: str) -> bool:
        return permission in self.permissions


async def provision_user(
    conn: AsyncConnection[DictRow], tenant: Tenant, principal: Principal
) -> tuple[UUID, str]:
    """Create the user's row in this tenant on first sign-in; refresh it now and then.

    A new user has no roles: access is granted in the platform, never assumed.
    The row is only rewritten when the profile changed or it was last seen over
    15 minutes ago, so most requests don't write.
    """
    cur = await conn.execute(
        """
        INSERT INTO kernel.users (tenant_id, issuer, subject, email, name)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (tenant_id, issuer, subject) DO UPDATE
            SET email = EXCLUDED.email, name = EXCLUDED.name, last_seen_at = now()
            WHERE kernel.users.email IS DISTINCT FROM EXCLUDED.email
               OR kernel.users.name IS DISTINCT FROM EXCLUDED.name
               OR kernel.users.last_seen_at < now() - interval '15 minutes'
        RETURNING id, status
        """,
        (tenant.id, principal.issuer, principal.subject, principal.email, principal.name),
    )
    row = await cur.fetchone()
    if row is None:  # existing user, nothing to refresh
        cur = await conn.execute(
            "SELECT id, status FROM kernel.users WHERE issuer = %s AND subject = %s",
            (principal.issuer, principal.subject),
        )
        row = await cur.fetchone()
        assert row is not None
    return row["id"], row["status"]


async def load_access(
    conn: AsyncConnection[DictRow], tenant: Tenant, principal: Principal
) -> Access:
    user_id, status = await provision_user(conn, tenant, principal)
    if status != "active":
        raise UserDisabledError(str(user_id))
    cur = await conn.execute(
        """
        SELECT r.key, r.permissions
        FROM kernel.user_roles ur JOIN kernel.roles r ON r.key = ur.role_key
        WHERE ur.user_id = %s
        """,
        (user_id,),
    )
    roles: set[str] = set()
    permissions: set[str] = set()
    for row in await cur.fetchall():
        roles.add(row["key"])
        permissions.update(row["permissions"])
    return Access(
        user_id=user_id,
        subject=principal.subject,
        tenant=tenant,
        roles=frozenset(roles),
        permissions=frozenset(permissions),
    )
