"""FastAPI dependencies shared by routers."""

import logging
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg import AsyncConnection
from psycopg.rows import DictRow
from psycopg_pool import AsyncConnectionPool

from wap.db import tenant_transaction
from wap.kernel.access import Access, Permission, UserDisabledError, load_access
from wap.kernel.audit import Actor
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


async def current_access(
    pool: Annotated[Pool, Depends(get_pool)],
    tenant: Annotated[Tenant, Depends(current_tenant)],
    principal: Annotated[Principal, Depends(current_principal)],
) -> Access:
    """The caller's user and permissions in this tenant, provisioning them on first sign-in.

    Uses its own short transaction, separate from the route's: a 403 from a
    permission check must not roll back the new user's row, or admins would
    never see users who are waiting for a role.
    """
    try:
        # No user id yet on a first sign-in: the subject identifies the actor.
        actor = Actor(user_id=None, subject=principal.subject)
        async with tenant_transaction(pool, tenant.id, actor) as conn:
            return await load_access(conn, tenant, principal)
    except UserDisabledError:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User is disabled in this tenant") from None


async def tenant_conn(
    pool: Annotated[Pool, Depends(get_pool)],
    access: Annotated[Access, Depends(current_access)],
) -> AsyncIterator[AsyncConnection[DictRow]]:
    """The request's tenant transaction, acting as the signed-in user for audit."""
    actor = Actor(user_id=access.user_id, subject=access.subject)
    async with tenant_transaction(pool, access.tenant.id, actor) as conn:
        yield conn


def require(permission: Permission) -> Callable[..., Coroutine[Any, Any, Access]]:
    """Route dependency: 403 unless the caller holds ``permission`` in this tenant."""

    async def check(access: Annotated[Access, Depends(current_access)]) -> Access:
        if not access.can(permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires permission {permission}")
        return access

    return check


PrincipalDep = Annotated[Principal, Depends(current_principal)]
TenantDep = Annotated[Tenant, Depends(current_tenant)]
TenantConn = Annotated[AsyncConnection[DictRow], Depends(tenant_conn)]
AccessDep = Annotated[Access, Depends(current_access)]
