"""Postgres connection pool and tenant-scoped transactions."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

from wap.config import Settings


def create_pool(settings: Settings) -> AsyncConnectionPool[AsyncConnection[DictRow]]:
    return AsyncConnectionPool(
        conninfo=settings.database_url,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        kwargs={"row_factory": dict_row},
        connection_class=AsyncConnection[DictRow],
        open=False,
    )


@asynccontextmanager
async def tenant_transaction(
    pool: AsyncConnectionPool[AsyncConnection[DictRow]], tenant_id: UUID
) -> AsyncGenerator[AsyncConnection[DictRow]]:
    """Open a transaction with the tenant set for row level security.

    The setting is transaction-local (``is_local = true``), so it can never leak
    to the next request that reuses the pooled connection.
    """
    async with pool.connection() as conn, conn.transaction():
        await conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))
        yield conn
