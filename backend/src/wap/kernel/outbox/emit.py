"""Write an event to the outbox inside the caller's tenant transaction."""

import re
import uuid
from collections.abc import Mapping
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import DictRow
from psycopg.types.json import Jsonb

_EVENT_TYPE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


def is_valid_event_type(event_type: str) -> bool:
    """Dotted lower-case names such as ``site.created``."""
    return bool(_EVENT_TYPE.fullmatch(event_type))


async def emit(
    conn: AsyncConnection[DictRow], event_type: str, payload: Mapping[str, Any]
) -> uuid.UUID:
    """Record ``event_type`` for the current tenant; it ships only if the transaction commits.

    Call it on the request's ``TenantConn``. The tenant comes from the
    transaction (row level security checks it), never from the caller.
    """
    if not is_valid_event_type(event_type):
        raise ValueError(f"invalid event type: {event_type!r}")
    event_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO kernel.outbox (id, tenant_id, event_type, payload)
        VALUES (%s, kernel.current_tenant_id(), %s, %s)
        """,
        (event_id, event_type, Jsonb(dict(payload))),
    )
    return event_id
