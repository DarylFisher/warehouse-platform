"""FastAPI application."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from wap import __version__
from wap.api import audit, health, me, sites, users
from wap.config import Settings, get_settings
from wap.db import create_pool
from wap.kernel.identity import JwksCache, TokenVerifier, http_jwks_fetcher


def create_verifier(settings: Settings, http: httpx.AsyncClient) -> TokenVerifier:
    fetch = http_jwks_fetcher(http, settings.oidc_issuer, settings.oidc_jwks_url)
    return TokenVerifier(
        issuer=settings.oidc_issuer,
        audience=settings.oidc_audience,
        jwks=JwksCache(fetch),
        tenant_group_prefix=settings.oidc_tenant_group_prefix,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    settings = get_settings()
    pool = create_pool(settings)
    await pool.open(wait=False)
    app.state.pool = pool
    app.state.clickhouse = None  # created on first use; see health.readiness
    http = httpx.AsyncClient(timeout=5)
    app.state.verifier = create_verifier(settings, http)
    try:
        yield
    finally:
        await http.aclose()
        await pool.close()
        client = app.state.clickhouse
        if client is not None:
            client.close()


def create_app() -> FastAPI:
    app = FastAPI(title="Warehouse Application Platform", version=__version__, lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(me.router)
    app.include_router(sites.router)
    app.include_router(users.router)
    app.include_router(audit.router)
    return app


app = create_app()
