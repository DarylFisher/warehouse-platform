"""FastAPI application."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from wap import __version__
from wap.api import health, sites
from wap.config import get_settings
from wap.db import create_pool


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    settings = get_settings()
    pool = create_pool(settings)
    await pool.open(wait=False)
    app.state.pool = pool
    app.state.clickhouse = None  # created on first use; see health.readiness
    try:
        yield
    finally:
        await pool.close()
        client = app.state.clickhouse
        if client is not None:
            client.close()


def create_app() -> FastAPI:
    app = FastAPI(title="Warehouse Application Platform", version=__version__, lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(sites.router)
    return app


app = create_app()
