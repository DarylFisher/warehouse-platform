"""The signed-in user and the tenants their token grants."""

from fastapi import APIRouter
from pydantic import BaseModel

from wap.api.deps import PrincipalDep

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
