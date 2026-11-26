"""Tenant resolution.

The app role cannot read ``kernel.tenants`` without a tenant set, so resolution
goes through ``kernel.resolve_tenant(slug)``, a SECURITY DEFINER function that
returns only the id and name for an active tenant.
"""

import re
from dataclasses import dataclass
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import DictRow

SLUG_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class TenantNotFoundError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class Tenant:
    id: UUID
    slug: str
    name: str


def is_valid_slug(slug: str) -> bool:
    return bool(SLUG_PATTERN.fullmatch(slug))


async def resolve_tenant(conn: AsyncConnection[DictRow], slug: str) -> Tenant:
    if not is_valid_slug(slug):
        raise TenantNotFoundError(slug)
    cur = await conn.execute("SELECT id, name FROM kernel.resolve_tenant(%s)", (slug,))
    row = await cur.fetchone()
    if row is None:
        raise TenantNotFoundError(slug)
    return Tenant(id=row["id"], slug=slug, name=row["name"])
