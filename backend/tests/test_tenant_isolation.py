"""Tenant isolation: the platform's most important guarantee.

These tests go through the API and straight to the database as the app role,
so a gap in either the code or the RLS policies fails the build.
"""

import psycopg
import pytest
from httpx import AsyncClient
from psycopg import AsyncConnection
from psycopg.rows import DictRow
from psycopg_pool import AsyncConnectionPool

from wap.db import tenant_transaction
from wap.kernel.tenancy import resolve_tenant

pytestmark = pytest.mark.integration

Pool = AsyncConnectionPool[AsyncConnection[DictRow]]


async def _codes(client: AsyncClient, tenant: str) -> set[str]:
    r = await client.get("/api/sites", headers={"X-Tenant": tenant})
    assert r.status_code == 200, r.text
    return {s["code"] for s in r.json()}


async def test_each_tenant_sees_only_its_own_sites(client: AsyncClient) -> None:
    north = await _codes(client, "demo-north")
    south = await _codes(client, "demo-south")
    assert {"NDC1", "NXD2"} <= north
    assert "SFC1" in south
    assert north.isdisjoint(south)


async def test_unknown_tenant_is_404(client: AsyncClient) -> None:
    r = await client.get("/api/sites", headers={"X-Tenant": "no-such-tenant"})
    assert r.status_code == 404


async def test_created_site_is_invisible_to_other_tenant(client: AsyncClient) -> None:
    r = await client.post(
        "/api/sites",
        json={"code": "NTEST", "name": "North test"},
        headers={"X-Tenant": "demo-north"},
    )
    assert r.status_code == 201, r.text
    assert "NTEST" in await _codes(client, "demo-north")
    assert "NTEST" not in await _codes(client, "demo-south")


async def test_site_codes_are_unique_per_tenant_only(client: AsyncClient) -> None:
    body = {"code": "SHARED", "name": "Same code, two tenants"}
    north = await client.post("/api/sites", json=body, headers={"X-Tenant": "demo-north"})
    south = await client.post("/api/sites", json=body, headers={"X-Tenant": "demo-south"})
    again = await client.post("/api/sites", json=body, headers={"X-Tenant": "demo-north"})
    assert (north.status_code, south.status_code, again.status_code) == (201, 201, 409)


async def test_no_tenant_set_means_no_rows(pool: Pool) -> None:
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT count(*) AS n FROM kernel.sites")
        row = await cur.fetchone()
        assert row is not None and row["n"] == 0
        cur = await conn.execute("SELECT count(*) AS n FROM kernel.tenants")
        row = await cur.fetchone()
        assert row is not None and row["n"] == 0


async def test_cannot_write_rows_for_another_tenant(pool: Pool) -> None:
    async with pool.connection() as conn:
        north = await resolve_tenant(conn, "demo-north")
        south = await resolve_tenant(conn, "demo-south")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        async with tenant_transaction(pool, north.id) as conn:
            await conn.execute(
                "INSERT INTO kernel.sites (tenant_id, code, name) VALUES (%s, 'HIJACK', 'x')",
                (south.id,),
            )


async def test_cannot_move_a_row_to_another_tenant(pool: Pool) -> None:
    async with pool.connection() as conn:
        north = await resolve_tenant(conn, "demo-north")
        south = await resolve_tenant(conn, "demo-south")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        async with tenant_transaction(pool, north.id) as conn:
            await conn.execute(
                "UPDATE kernel.sites SET tenant_id = %s WHERE code = 'NDC1'", (south.id,)
            )


async def test_app_role_sees_only_its_own_tenant_row(pool: Pool) -> None:
    async with pool.connection() as conn:
        north = await resolve_tenant(conn, "demo-north")
    async with tenant_transaction(pool, north.id) as conn:
        cur = await conn.execute("SELECT slug FROM kernel.tenants")
        assert [r["slug"] for r in await cur.fetchall()] == ["demo-north"]


async def test_app_role_cannot_disable_rls(pool: Pool) -> None:
    async with pool.connection() as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await conn.execute("ALTER TABLE kernel.sites DISABLE ROW LEVEL SECURITY")


async def test_app_role_has_no_rls_bypass(pool: Pool) -> None:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname = current_user"
        )
        row = await cur.fetchone()
        assert row == {"rolbypassrls": False, "rolsuper": False}


async def test_tenant_setting_does_not_leak_between_transactions(pool: Pool) -> None:
    async with pool.connection() as conn:
        north = await resolve_tenant(conn, "demo-north")
    # min/max pool size in tests can reuse the same connection; check on one connection.
    async with pool.connection() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(north.id),))
        cur = await conn.execute("SELECT kernel.current_tenant_id() AS t")
        row = await cur.fetchone()
        assert row is not None and row["t"] is None
