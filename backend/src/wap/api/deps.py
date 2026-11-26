"""FastAPI dependencies shared by routers."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from psycopg import AsyncConnection
from psycopg.rows import DictRow
from psycopg_pool import AsyncConnectionPool

from wap.config import Settings, get_settings
from wap.db import tenant_transaction
from wap.kernel.tenancy import Tenant, TenantNotFoundError, resolve_tenant

Pool = AsyncConnectionPool[AsyncConnection[DictRow]]


def get_pool(request: Request) -> Pool:
    pool: Pool = request.app.state.pool
    return pool


async def current_tenant(
    pool: Annotated[Pool, Depends(get_pool)],
    settings: Annotated[Settings, Depends(get_settings)],
    x_tenant: Annotated[str | None, Header()] = None,
) -> Tenant:
    if not settings.dev_tenant_header:
        # OIDC-based resolution arrives in M1.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    if not x_tenant:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Tenant header is required")
    async with pool.connection() as conn:
        try:
            return await resolve_tenant(conn, x_tenant)
        except TenantNotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown tenant") from None


async def tenant_conn(
    pool: Annotated[Pool, Depends(get_pool)],
    tenant: Annotated[Tenant, Depends(current_tenant)],
) -> AsyncIterator[AsyncConnection[DictRow]]:
    async with tenant_transaction(pool, tenant.id) as conn:
        yield conn


TenantDep = Annotated[Tenant, Depends(current_tenant)]
TenantConn = Annotated[AsyncConnection[DictRow], Depends(tenant_conn)]
