"""Liveness and readiness endpoints."""

import asyncio
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel

from wap import __version__
from wap.api.deps import Pool, get_pool
from wap.clickhouse import create_client
from wap.config import Settings, get_settings

router = APIRouter(tags=["health"])

CheckStatus = Literal["ok", "error"]


class Liveness(BaseModel):
    status: Literal["ok"] = "ok"
    version: str = __version__


class Readiness(BaseModel):
    status: CheckStatus
    postgres: CheckStatus
    clickhouse: CheckStatus


@router.get("/health")
async def liveness() -> Liveness:
    return Liveness()


async def _check_postgres(pool: Pool) -> CheckStatus:
    try:
        async with pool.connection(timeout=3) as conn:
            await conn.execute("SELECT 1")
    except Exception:
        return "error"
    return "ok"


def _check_clickhouse_sync(request: Request, settings: Settings) -> CheckStatus:
    try:
        client = getattr(request.app.state, "clickhouse", None)
        if client is None:
            client = create_client(settings)
            request.app.state.clickhouse = client
        client.command("SELECT 1")
    except Exception:
        request.app.state.clickhouse = None
        return "error"
    return "ok"


@router.get("/health/ready")
async def readiness(
    request: Request,
    response: Response,
    pool: Annotated[Pool, Depends(get_pool)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Readiness:
    pg, ch = await asyncio.gather(
        _check_postgres(pool),
        asyncio.to_thread(_check_clickhouse_sync, request, settings),
    )
    overall: CheckStatus = "ok" if pg == ch == "ok" else "error"
    if overall != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return Readiness(status=overall, postgres=pg, clickhouse=ch)
