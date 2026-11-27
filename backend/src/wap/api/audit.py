"""Read the tenant's audit log. Entries are written by database trigger, never here."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from wap.api.deps import TenantConn, require
from wap.kernel.access import Permission

router = APIRouter(prefix="/api", tags=["audit"])


class AuditEntry(BaseModel):
    id: UUID
    occurred_at: datetime
    txid: int
    actor_user_id: UUID | None
    actor_subject: str | None
    action: Literal["insert", "update", "delete"]
    table_name: str
    row_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None


@router.get("/audit", dependencies=[Depends(require(Permission.AUDIT_READ))])
async def list_audit(
    conn: TenantConn,
    table: Annotated[str | None, Query(description="e.g. kernel.sites")] = None,
    row_id: str | None = None,
    actor_user_id: UUID | None = None,
    before: Annotated[
        datetime | None, Query(description="Only entries older than this (for paging)")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AuditEntry]:
    """Newest first. No tenant filter: row level security scopes it."""
    cur = await conn.execute(
        """
        SELECT id, occurred_at, txid, actor_user_id, actor_subject, action, table_name,
               row_id, before, after
        FROM kernel.audit_log
        WHERE (%(table)s::text IS NULL OR table_name = %(table)s)
          AND (%(row_id)s::text IS NULL OR row_id = %(row_id)s)
          AND (%(actor)s::uuid IS NULL OR actor_user_id = %(actor)s)
          AND (%(before)s::timestamptz IS NULL OR occurred_at < %(before)s)
        ORDER BY occurred_at DESC, id
        LIMIT %(limit)s
        """,
        {
            "table": table,
            "row_id": row_id,
            "actor": actor_user_id,
            "before": before,
            "limit": limit,
        },
    )
    return [AuditEntry.model_validate(row) for row in await cur.fetchall()]
