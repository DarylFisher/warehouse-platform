"""Tenant users and their roles.

Queries carry no tenant filter: row level security scopes every one of them.
A user from another tenant is simply not found (404).
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import AsyncConnection
from psycopg.rows import DictRow
from pydantic import BaseModel, Field

from wap.api.deps import TenantConn, require
from wap.kernel.access import ADMIN_ROLE, Access, Permission

router = APIRouter(prefix="/api", tags=["users"])

UserStatus = Literal["active", "disabled"]


class Role(BaseModel):
    key: str
    name: str
    description: str
    permissions: list[str]


class User(BaseModel):
    id: UUID
    email: str | None
    name: str | None
    status: UserStatus
    roles: list[str]
    created_at: datetime
    last_seen_at: datetime


class RolesIn(BaseModel):
    roles: list[str] = Field(max_length=20)


class StatusIn(BaseModel):
    status: UserStatus


USER_COLUMNS = """
    u.id, u.email, u.name, u.status, u.created_at, u.last_seen_at,
    coalesce(
        array_agg(ur.role_key ORDER BY ur.role_key) FILTER (WHERE ur.role_key IS NOT NULL),
        '{}'
    ) AS roles
"""


async def _get_user(conn: AsyncConnection[DictRow], user_id: UUID) -> User:
    cur = await conn.execute(
        f"""
        SELECT {USER_COLUMNS}
        FROM kernel.users u LEFT JOIN kernel.user_roles ur ON ur.user_id = u.id
        WHERE u.id = %s
        GROUP BY u.id
        """,  # noqa: S608 - fixed column list, values are parameters
        (user_id,),
    )
    row = await cur.fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return User.model_validate(row)


async def _lock_admin_changes(conn: AsyncConnection[DictRow], access: Access) -> None:
    """Serialize changes that could remove the tenant's last admin."""
    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended('wap.admins:' || %s, 0))",
        (str(access.tenant.id),),
    )


async def _ensure_an_active_admin_remains(conn: AsyncConnection[DictRow]) -> None:
    cur = await conn.execute(
        """
        SELECT count(*) AS n
        FROM kernel.user_roles ur JOIN kernel.users u ON u.id = ur.user_id
        WHERE ur.role_key = %s AND u.status = 'active'
        """,
        (ADMIN_ROLE,),
    )
    row = await cur.fetchone()
    if row is None or row["n"] == 0:
        # Raising rolls back the whole request transaction, change included.
        raise HTTPException(status.HTTP_409_CONFLICT, "The tenant must keep an active admin")


@router.get("/roles", dependencies=[Depends(require(Permission.USERS_READ))])
async def list_roles(conn: TenantConn) -> list[Role]:
    cur = await conn.execute(
        "SELECT key, name, description, permissions FROM kernel.roles ORDER BY key"
    )
    return [Role.model_validate(row) for row in await cur.fetchall()]


@router.get("/users", dependencies=[Depends(require(Permission.USERS_READ))])
async def list_users(conn: TenantConn) -> list[User]:
    cur = await conn.execute(
        f"""
        SELECT {USER_COLUMNS}
        FROM kernel.users u LEFT JOIN kernel.user_roles ur ON ur.user_id = u.id
        GROUP BY u.id
        ORDER BY u.email NULLS LAST, u.id
        """  # noqa: S608 - fixed column list
    )
    return [User.model_validate(row) for row in await cur.fetchall()]


@router.put("/users/{user_id}/roles")
async def set_user_roles(
    user_id: UUID,
    body: RolesIn,
    conn: TenantConn,
    access: Annotated[Access, Depends(require(Permission.USERS_MANAGE))],
) -> User:
    """Replace the user's roles with exactly ``roles``."""
    wanted = sorted(set(body.roles))
    cur = await conn.execute("SELECT key FROM kernel.roles WHERE key = ANY(%s)", (wanted,))
    known = {row["key"] for row in await cur.fetchall()}
    if unknown := sorted(set(wanted) - known):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown roles: {unknown}")

    await _lock_admin_changes(conn, access)
    await _get_user(conn, user_id)  # 404 if not in this tenant
    await conn.execute(
        "DELETE FROM kernel.user_roles WHERE user_id = %s AND NOT (role_key = ANY(%s))",
        (user_id, wanted),
    )
    for role in wanted:
        await conn.execute(
            """
            INSERT INTO kernel.user_roles (tenant_id, user_id, role_key, granted_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (tenant_id, user_id, role_key) DO NOTHING
            """,
            (access.tenant.id, user_id, role, access.user_id),
        )
    await _ensure_an_active_admin_remains(conn)
    return await _get_user(conn, user_id)


@router.patch("/users/{user_id}")
async def set_user_status(
    user_id: UUID,
    body: StatusIn,
    conn: TenantConn,
    access: Annotated[Access, Depends(require(Permission.USERS_MANAGE))],
) -> User:
    """Enable or disable a user in this tenant. Users are disabled, never deleted."""
    if user_id == access.user_id and body.status == "disabled":
        raise HTTPException(status.HTTP_409_CONFLICT, "You cannot disable yourself")
    await _lock_admin_changes(conn, access)
    cur = await conn.execute(
        "UPDATE kernel.users SET status = %s WHERE id = %s RETURNING id",
        (body.status, user_id),
    )
    if await cur.fetchone() is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    await _ensure_an_active_admin_remains(conn)
    return await _get_user(conn, user_id)
