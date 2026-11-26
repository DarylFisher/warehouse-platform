"""FastAPI dependencies shared by routers."""

import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg import AsyncConnection
from psycopg.rows import DictRow
from psycopg_pool import AsyncConnectionPool

from wap.db import tenant_transaction
from wap.kernel.identity import (
    IdentityProviderUnavailableError,
    InvalidTokenError,
    Principal,
    TokenVerifier,
)
from wap.kernel.tenancy import Tenant, TenantNotFoundError, resolve_tenant

log = logging.getLogger(__name__)

Pool = AsyncConnectionPool[AsyncConnection[DictRow]]

bearer = HTTPBearer(auto_error=False, description="OIDC access token")


def get_pool(request: Request) -> Pool:
    pool: Pool = request.app.state.pool
    return pool


def get_verifier(request: Request) -> TokenVerifier:
    verifier: TokenVerifier = request.app.state.verifier
    return verifier


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"}
    )


async def current_principal(
    verifier: Annotated[TokenVerifier, Depends(get_verifier)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    if credentials is None:
        raise _unauthorized("Authentication required")
    try:
        return await verifier.verify(credentials.credentials)
    except InvalidTokenError as exc:
        log.info("rejected token: %s", exc)
        raise _unauthorized("Invalid or expired token") from None
    except IdentityProviderUnavailableError as exc:
        log.warning("identity provider unavailable: %s", exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Identity provider unavailable"
        ) from None


async def current_tenant(
    pool: Annotated[Pool, Depends(get_pool)],
    principal: Annotated[Principal, Depends(current_principal)],
    x_tenant: Annotated[
        str | None,
        Header(description="Picks one tenant when the token grants several; never grants access"),
    ] = None,
) -> Tenant:
    """The tenant for this request, taken from the token's tenant groups.

    ``X-Tenant`` only chooses among tenants the token already grants.
    """
    granted = principal.tenant_slugs
    if x_tenant is not None:
        if x_tenant not in granted:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to this tenant")
        slug = x_tenant
    elif len(granted) == 1:
        (slug,) = granted
    elif not granted:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No tenant access")
    else:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Token grants several tenants: choose one with the X-Tenant header",
        )
    async with pool.connection() as conn:
        try:
            return await resolve_tenant(conn, slug)
        except TenantNotFoundError:
            # Unknown or suspended: the group exists in the provider but the tenant doesn't here.
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Tenant not available") from None


async def tenant_conn(
    pool: Annotated[Pool, Depends(get_pool)],
    tenant: Annotated[Tenant, Depends(current_tenant)],
) -> AsyncIterator[AsyncConnection[DictRow]]:
    async with tenant_transaction(pool, tenant.id) as conn:
        yield conn


PrincipalDep = Annotated[Principal, Depends(current_principal)]
TenantDep = Annotated[Tenant, Depends(current_tenant)]
TenantConn = Annotated[AsyncConnection[DictRow], Depends(tenant_conn)]
