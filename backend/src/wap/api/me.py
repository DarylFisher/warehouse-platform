"""The signed-in user, the tenants their token grants, and their access in one."""

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from wap.api.deps import AccessDep, PrincipalDep

router = APIRouter(prefix="/api", tags=["identity"])


class Me(BaseModel):
    subject: str
    email: str | None
    name: str | None
    tenants: list[str]


@router.get("/me")
async def whoami(principal: PrincipalDep) -> Me:
    return Me(
        subject=principal.subject,
        email=principal.email,
        name=principal.name,
        tenants=sorted(principal.tenant_slugs),
    )


class MyAccess(BaseModel):
    tenant: str
    user_id: UUID
    roles: list[str]
    permissions: list[str]


@router.get("/me/access")
async def my_access(access: AccessDep) -> MyAccess:
    """Roles and permissions in the current tenant. Signing in here provisions the user."""
    return MyAccess(
        tenant=access.tenant.slug,
        user_id=access.user_id,
        roles=sorted(access.roles),
        permissions=sorted(access.permissions),
    )
