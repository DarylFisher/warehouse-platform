"""Audit log: every write recorded with its actor, in the same transaction.

Runs against real Postgres. Seeded users are described in tests/test_access.py.
"""

import uuid
from typing import Any

import psycopg
import pytest
from auth_support import bearer_as, bearer_for
from httpx import AsyncClient
from psycopg import AsyncConnection
from psycopg.rows import DictRow
from psycopg_pool import AsyncConnectionPool

from wap.config import Settings
from wap.db import tenant_transaction
from wap.kernel.audit import Actor, attach_sql
from wap.kernel.tenancy import resolve_tenant

pytestmark = pytest.mark.integration

Pool = AsyncConnectionPool[AsyncConnection[DictRow]]
NORTH_ADMIN = bearer_as("north.admin")


async def _audit(client: AsyncClient, headers: dict[str, str], **params: str) -> list[Any]:
    r = await client.get("/api/audit", params=params, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def _me(client: AsyncClient, headers: dict[str, str]) -> Any:
    return (await client.get("/api/me/access", headers=headers)).json()


async def test_creating_a_site_is_audited_with_its_actor(client: AsyncClient) -> None:
    code = f"A{uuid.uuid4().hex[:8].upper()}"
    r = await client.post("/api/sites", json={"code": code, "name": "Audited"}, headers=NORTH_ADMIN)
    assert r.status_code == 201
    site_id = r.json()["id"]
    me = await _me(client, NORTH_ADMIN)

    entries = await _audit(client, NORTH_ADMIN, table="kernel.sites", row_id=site_id)
    assert len(entries) == 1
    e = entries[0]
    assert (e["action"], e["actor_user_id"]) == ("insert", me["user_id"])
    assert e["actor_subject"] == "8f6d2c1e-4b7a-4e0f-9a51-1d2e3f4a5b01"
    assert e["before"] is None and e["after"]["code"] == code


async def test_role_change_records_before_and_after_in_one_transaction(
    client: AsyncClient,
) -> None:
    newcomer = bearer_for("demo-north", sub=f"aud-{uuid.uuid4()}")
    user_id = (await _me(client, newcomer))["user_id"]
    await client.put(f"/api/users/{user_id}/roles", json={"roles": ["viewer"]}, headers=NORTH_ADMIN)
    r = await client.put(
        f"/api/users/{user_id}/roles", json={"roles": ["operator"]}, headers=NORTH_ADMIN
    )
    assert r.status_code == 200

    entries = await _audit(client, NORTH_ADMIN, table="kernel.user_roles")
    mine = [e for e in entries if (e["after"] or e["before"])["user_id"] == user_id]
    latest_tx = mine[0]["txid"]
    change = {
        (e["action"], (e["after"] or e["before"])["role_key"])
        for e in mine
        if e["txid"] == latest_tx
    }
    assert change == {("delete", "viewer"), ("insert", "operator")}
    # Within a transaction entries keep their order: newest first, the insert
    # follows the delete it replaced.
    in_tx = [e["action"] for e in mine if e["txid"] == latest_tx]
    assert in_tx == ["insert", "delete"]


async def test_status_change_records_the_old_and_new_value(client: AsyncClient) -> None:
    newcomer = bearer_for("demo-north", sub=f"aud-{uuid.uuid4()}")
    user_id = (await _me(client, newcomer))["user_id"]
    await client.patch(f"/api/users/{user_id}", json={"status": "disabled"}, headers=NORTH_ADMIN)

    entries = await _audit(client, NORTH_ADMIN, table="kernel.users", row_id=user_id)
    actions: list[tuple[Any, Any, Any]] = [
        (e["action"], e["before"] and e["before"]["status"], e["after"]["status"]) for e in entries
    ]
    # Newest first: the disable, then the sign-in that created the user.
    assert actions == [("update", "active", "disabled"), ("insert", None, "active")]


async def test_first_sign_in_is_attributed_to_the_token_subject(client: AsyncClient) -> None:
    sub = f"aud-{uuid.uuid4()}"
    user_id = (await _me(client, bearer_for("demo-north", sub=sub)))["user_id"]
    (entry,) = await _audit(client, NORTH_ADMIN, table="kernel.users", row_id=user_id)
    assert entry["action"] == "insert"
    assert (entry["actor_user_id"], entry["actor_subject"]) == (None, sub)


async def test_rolled_back_change_leaves_no_entry(client: AsyncClient) -> None:
    me = await _me(client, NORTH_ADMIN)
    before = await _audit(client, NORTH_ADMIN, table="kernel.user_roles", limit="200")
    r = await client.put(
        f"/api/users/{me['user_id']}/roles", json={"roles": []}, headers=NORTH_ADMIN
    )
    assert r.status_code == 409  # last admin: the change and its audit roll back together
    after = await _audit(client, NORTH_ADMIN, table="kernel.user_roles", limit="200")
    assert [e["id"] for e in after] == [e["id"] for e in before]


async def test_last_seen_refresh_is_not_audited(pool: Pool) -> None:
    async with pool.connection() as conn:
        north = await resolve_tenant(conn, "demo-north")
    async with tenant_transaction(pool, north.id, Actor.system("test")) as conn:
        cur = await conn.execute("SELECT count(*) AS n FROM kernel.audit_log")
        row = await cur.fetchone()
        assert row is not None
        n = row["n"]
        await conn.execute("UPDATE kernel.users SET last_seen_at = now() - interval '1 day'")
        cur = await conn.execute("SELECT count(*) AS n FROM kernel.audit_log")
        row = await cur.fetchone()
        assert row is not None and row["n"] == n


async def test_seed_entries_name_the_seed_job(client: AsyncClient) -> None:
    entries = await _audit(client, NORTH_ADMIN, table="kernel.sites", limit="200")
    assert any(e["actor_subject"] == "system:seed" for e in entries)


async def test_reading_the_audit_log_needs_audit_read(client: AsyncClient) -> None:
    operator = {**bearer_as("ops.both"), "X-Tenant": "demo-south"}
    assert (await client.get("/api/audit", headers=operator)).status_code == 403
    assert "audit.read" in (await _me(client, NORTH_ADMIN))["permissions"]


async def test_audit_log_is_append_only_even_for_the_owner(migrated_db: Settings) -> None:
    async with await psycopg.AsyncConnection.connect(migrated_db.migration_database_url) as conn:
        cur = await conn.execute("SELECT id FROM kernel.tenants WHERE slug = 'demo-north'")
        row = await cur.fetchone()
        assert row is not None
        await conn.execute("SELECT set_config('app.tenant_id', %s, false)", (str(row[0]),))
        for sql in (
            "UPDATE kernel.audit_log SET action = 'insert'",
            "DELETE FROM kernel.audit_log",
        ):
            with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
                await conn.execute(sql)
            await conn.rollback()
            await conn.execute("SELECT set_config('app.tenant_id', %s, false)", (str(row[0]),))


@pytest.mark.parametrize(
    ("table", "ignored"),
    [("kernel.sites; DROP TABLE x", []), ("sites", []), ("kernel.users", ["a'b"])],
)
def test_attach_sql_rejects_unsafe_names(table: str, ignored: list[str]) -> None:
    with pytest.raises(ValueError):
        attach_sql(table, ignored)


def test_attach_sql_passes_ignored_columns() -> None:
    sql = attach_sql("kernel.users", ["last_seen_at"])
    assert sql.endswith("EXECUTE FUNCTION kernel.audit_row('last_seen_at')")
