"""Tenant isolation: the platform's most important guarantee.

Requests carry signed tokens; the tenant comes only from their tenant groups.

These tests go through the API and straight to the database as the app role,
so a gap in either the code or the RLS policies fails the build.
"""

import psycopg
import pytest
from auth_support import bearer_as, bearer_for
from httpx import AsyncClient
from psycopg import AsyncConnection
from psycopg.rows import DictRow
from psycopg_pool import AsyncConnectionPool

from wap.db import tenant_transaction
from wap.kernel.tenancy import resolve_tenant

pytestmark = pytest.mark.integration

Pool = AsyncConnectionPool[AsyncConnection[DictRow]]


TENANT_ADMINS = {"demo-north": "north.admin", "demo-south": "south.admin"}


async def _codes(client: AsyncClient, tenant: str) -> set[str]:
    r = await client.get("/api/sites", headers=bearer_as(TENANT_ADMINS[tenant]))
    assert r.status_code == 200, r.text
    return {s["code"] for s in r.json()}


async def test_each_tenant_sees_only_its_own_sites(client: AsyncClient) -> None:
    north = await _codes(client, "demo-north")
    south = await _codes(client, "demo-south")
    assert {"NDC1", "NXD2"} <= north
    assert "SFC1" in south
    assert north.isdisjoint(south)


async def test_group_for_unknown_tenant_is_403(client: AsyncClient) -> None:
    r = await client.get("/api/sites", headers=bearer_for("no-such-tenant"))
    assert r.status_code == 403


async def test_no_token_is_401(client: AsyncClient) -> None:
    for method, body in (("GET", None), ("POST", {"code": "NOAUTH", "name": "x"})):
        r = await client.request(method, "/api/sites", json=body)
        assert r.status_code == 401
        assert r.headers["www-authenticate"] == "Bearer"


async def test_x_tenant_cannot_reach_a_tenant_the_token_does_not_grant(
    client: AsyncClient,
) -> None:
    headers = {**bearer_as("north.admin"), "X-Tenant": "demo-south"}
    r = await client.get("/api/sites", headers=headers)
    assert r.status_code == 403
    r = await client.post("/api/sites", json={"code": "XT", "name": "x"}, headers=headers)
    assert r.status_code == 403


async def test_multi_tenant_user_picks_a_granted_tenant(client: AsyncClient) -> None:
    both = bearer_as("ops.both")
    r = await client.get("/api/sites", headers=both)
    assert r.status_code == 400  # ambiguous without a choice
    north = await client.get("/api/sites", headers={**both, "X-Tenant": "demo-north"})
    south = await client.get("/api/sites", headers={**both, "X-Tenant": "demo-south"})
    north_codes = {s["code"] for s in north.json()}
    south_codes = {s["code"] for s in south.json()}
    assert "NDC1" in north_codes and "SFC1" in south_codes
    assert north_codes.isdisjoint(south_codes)


async def test_created_site_is_invisible_to_other_tenant(client: AsyncClient) -> None:
    r = await client.post(
        "/api/sites",
        json={"code": "NTEST", "name": "North test"},
        headers=bearer_as("north.admin"),
    )
    assert r.status_code == 201, r.text
    assert "NTEST" in await _codes(client, "demo-north")
    assert "NTEST" not in await _codes(client, "demo-south")


async def test_site_codes_are_unique_per_tenant_only(client: AsyncClient) -> None:
    body = {"code": "SHARED", "name": "Same code, two tenants"}
    north = await client.post("/api/sites", json=body, headers=bearer_as("north.admin"))
    south = await client.post("/api/sites", json=body, headers=bearer_as("south.admin"))
    again = await client.post("/api/sites", json=body, headers=bearer_as("north.admin"))
    assert (north.status_code, south.status_code, again.status_code) == (201, 201, 409)


async def test_no_tenant_set_means_no_rows(pool: Pool) -> None:
    async with pool.connection() as conn:
        for table in ("kernel.sites", "kernel.tenants", "kernel.users", "kernel.user_roles"):
            cur = await conn.execute(f"SELECT count(*) AS n FROM {table}")  # noqa: S608
            row = await cur.fetchone()
            assert row is not None and row["n"] == 0, table


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


# --- users and role assignments -------------------------------------------------


async def _user_id(pool: Pool, tenant_slug: str, email: str) -> object:
    async with pool.connection() as conn:
        tenant = await resolve_tenant(conn, tenant_slug)
    async with tenant_transaction(pool, tenant.id) as conn:
        cur = await conn.execute("SELECT id FROM kernel.users WHERE email = %s", (email,))
        row = await cur.fetchone()
        assert row is not None
        return row["id"]


async def test_users_list_shows_only_own_tenant(client: AsyncClient) -> None:
    r = await client.get("/api/users", headers=bearer_as("north.admin"))
    assert r.status_code == 200, r.text
    emails = {u["email"] for u in r.json()}
    assert "north.admin@example.com" in emails
    assert "south.admin@example.com" not in emails


async def test_cannot_manage_a_user_in_another_tenant(client: AsyncClient, pool: Pool) -> None:
    south_admin = await _user_id(pool, "demo-south", "south.admin@example.com")
    north = bearer_as("north.admin")
    r = await client.put(f"/api/users/{south_admin}/roles", json={"roles": []}, headers=north)
    assert r.status_code == 404
    r = await client.patch(f"/api/users/{south_admin}", json={"status": "disabled"}, headers=north)
    assert r.status_code == 404


async def test_cannot_insert_a_user_for_another_tenant(pool: Pool) -> None:
    async with pool.connection() as conn:
        north = await resolve_tenant(conn, "demo-north")
        south = await resolve_tenant(conn, "demo-south")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        async with tenant_transaction(pool, north.id) as conn:
            await conn.execute(
                "INSERT INTO kernel.users (tenant_id, issuer, subject) VALUES (%s, 'i', 's')",
                (south.id,),
            )


async def test_cannot_grant_a_role_across_tenants(pool: Pool) -> None:
    async with pool.connection() as conn:
        north = await resolve_tenant(conn, "demo-north")
        south = await resolve_tenant(conn, "demo-south")
    south_admin = await _user_id(pool, "demo-south", "south.admin@example.com")
    # Tagged with our own tenant: the composite foreign key finds no such user here.
    # (South admin already holds "admin"; the tenant-scoped primary key means that
    # existing grant is not revealed by a unique violation.)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        async with tenant_transaction(pool, north.id) as conn:
            await conn.execute(
                "INSERT INTO kernel.user_roles (tenant_id, user_id, role_key) "
                "VALUES (%s, %s, 'admin')",
                (north.id, south_admin),
            )
    # Tagged with the other tenant: row level security refuses it.
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        async with tenant_transaction(pool, north.id) as conn:
            await conn.execute(
                "INSERT INTO kernel.user_roles (tenant_id, user_id, role_key) "
                "VALUES (%s, %s, 'admin')",
                (south.id, south_admin),
            )


async def test_app_role_cannot_change_the_role_catalogue(pool: Pool) -> None:
    for sql in (
        "INSERT INTO kernel.roles (key, name, permissions) VALUES ('root', 'x', '{}')",
        "UPDATE kernel.roles SET permissions = '{users.manage}' WHERE key = 'viewer'",
    ):
        async with pool.connection() as conn:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                await conn.execute(sql)


async def test_app_role_cannot_delete_users(pool: Pool) -> None:
    async with pool.connection() as conn:
        north = await resolve_tenant(conn, "demo-north")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        async with tenant_transaction(pool, north.id) as conn:
            await conn.execute("DELETE FROM kernel.users")
