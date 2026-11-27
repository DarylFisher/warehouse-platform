"""Warehouse sites: the first tenant-scoped kernel entity.

Queries carry no tenant filter on purpose: row level security supplies it, and
the tenant-isolation tests prove it does.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from wap.api.deps import TenantConn, require
from wap.kernel.access import Access, Permission
from wap.kernel.outbox import emit

router = APIRouter(prefix="/api/sites", tags=["sites"])


class SiteIn(BaseModel):
    code: str = Field(min_length=1, max_length=20, pattern=r"^[A-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=200)


class Site(SiteIn):
    id: UUID
    created_at: datetime


@router.get("", dependencies=[Depends(require(Permission.SITES_READ))])
async def list_sites(conn: TenantConn) -> list[Site]:
    cur = await conn.execute("SELECT id, code, name, created_at FROM kernel.sites ORDER BY code")
    return [Site.model_validate(row) for row in await cur.fetchall()]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_site(
    body: SiteIn,
    conn: TenantConn,
    access: Annotated[Access, Depends(require(Permission.SITES_WRITE))],
) -> Site:
    try:
        cur = await conn.execute(
            """
            INSERT INTO kernel.sites (tenant_id, code, name)
            VALUES (%s, %s, %s)
            RETURNING id, code, name, created_at
            """,
            (access.tenant.id, body.code, body.name),
        )
    except psycopg.errors.UniqueViolation:
        raise HTTPException(status.HTTP_409_CONFLICT, "Site code already exists") from None
    row = await cur.fetchone()
    assert row is not None
    site = Site.model_validate(row)
    await emit(conn, "site.created", {"site_id": str(site.id), "code": site.code})
    return site
