"""Users, roles and permission checks, through the API against real Postgres.

Seeded users (wap.cli.seed): north.admin and south.admin are admins of their
tenants; ops.both is a viewer in demo-north and an operator in demo-south.
Tests that create users use their own subjects, so they don't interfere.
"""

import uuid

import pytest
from auth_support import bearer_as, bearer_for
from httpx import AsyncClient

from wap.kernel.access import Permission

pytestmark = pytest.mark.integration

NORTH_ADMIN = bearer_as("north.admin")


def _new_north_user() -> dict[str, str]:
    return bearer_for("demo-north", sub=f"new-{uuid.uuid4()}")


async def _my_access(client: AsyncClient, headers: dict[str, str]) -> dict[str, object]:
    r = await client.get("/api/me/access", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def test_viewer_can_read_but_not_write(client: AsyncClient) -> None:
    viewer = {**bearer_as("ops.both"), "X-Tenant": "demo-north"}
    assert (await client.get("/api/sites", headers=viewer)).status_code == 200
    r = await client.post("/api/sites", json={"code": "VIEW1", "name": "x"}, headers=viewer)
    assert r.status_code == 403
    assert "sites.write" in r.json()["detail"]


async def test_same_user_has_different_roles_per_tenant(client: AsyncClient) -> None:
    both = bearer_as("ops.both")
    north = await _my_access(client, {**both, "X-Tenant": "demo-north"})
    south = await _my_access(client, {**both, "X-Tenant": "demo-south"})
    assert (north["roles"], south["roles"]) == (["viewer"], ["operator"])
    r = await client.post(
        "/api/sites",
        json={"code": "OPS1", "name": "Operator site"},
        headers={**both, "X-Tenant": "demo-south"},
    )
    assert r.status_code == 201, r.text


async def test_new_user_is_provisioned_without_roles(client: AsyncClient) -> None:
    newcomer = _new_north_user()
    access = await _my_access(client, newcomer)
    assert access["roles"] == [] and access["permissions"] == []
    assert (await client.get("/api/sites", headers=newcomer)).status_code == 403


async def test_refused_newcomer_still_appears_for_admins(client: AsyncClient) -> None:
    sub = f"new-{uuid.uuid4()}"
    newcomer = bearer_for("demo-north", sub=sub, email=f"{sub}@example.com")
    # Their very first request is refused; their user row must survive that.
    assert (await client.get("/api/sites", headers=newcomer)).status_code == 403
    users = (await client.get("/api/users", headers=NORTH_ADMIN)).json()
    assert any(u["email"] == f"{sub}@example.com" for u in users)


async def test_admin_grants_a_role_and_it_takes_effect(client: AsyncClient) -> None:
    newcomer = _new_north_user()
    user_id = (await _my_access(client, newcomer))["user_id"]
    r = await client.put(
        f"/api/users/{user_id}/roles", json={"roles": ["viewer"]}, headers=NORTH_ADMIN
    )
    assert r.status_code == 200, r.text
    assert r.json()["roles"] == ["viewer"]
    assert (await client.get("/api/sites", headers=newcomer)).status_code == 200
    # Replacing with an empty set takes it away again.
    r = await client.put(f"/api/users/{user_id}/roles", json={"roles": []}, headers=NORTH_ADMIN)
    assert r.json()["roles"] == []
    assert (await client.get("/api/sites", headers=newcomer)).status_code == 403


async def test_unknown_role_is_rejected(client: AsyncClient) -> None:
    user_id = (await _my_access(client, _new_north_user()))["user_id"]
    r = await client.put(
        f"/api/users/{user_id}/roles", json={"roles": ["superuser"]}, headers=NORTH_ADMIN
    )
    assert r.status_code == 422


async def test_non_admins_cannot_manage_users(client: AsyncClient) -> None:
    viewer = {**bearer_as("ops.both"), "X-Tenant": "demo-north"}
    user_id = (await _my_access(client, _new_north_user()))["user_id"]
    assert (await client.get("/api/users", headers=viewer)).status_code == 403
    r = await client.put(f"/api/users/{user_id}/roles", json={"roles": ["admin"]}, headers=viewer)
    assert r.status_code == 403


async def test_last_admin_cannot_remove_their_own_admin_role(client: AsyncClient) -> None:
    me = await _my_access(client, NORTH_ADMIN)
    r = await client.put(
        f"/api/users/{me['user_id']}/roles", json={"roles": []}, headers=NORTH_ADMIN
    )
    assert r.status_code == 409
    assert (await _my_access(client, NORTH_ADMIN))["roles"] == ["admin"]  # rolled back


async def test_a_second_admin_lets_the_first_step_down(client: AsyncClient) -> None:
    deputy = _new_north_user()
    deputy_id = (await _my_access(client, deputy))["user_id"]
    me = await _my_access(client, NORTH_ADMIN)
    r = await client.put(
        f"/api/users/{deputy_id}/roles", json={"roles": ["admin"]}, headers=NORTH_ADMIN
    )
    assert r.status_code == 200
    r = await client.put(
        f"/api/users/{me['user_id']}/roles", json={"roles": ["viewer"]}, headers=NORTH_ADMIN
    )
    assert r.status_code == 200
    # Restore, so other tests keep their seeded admin.
    r = await client.put(
        f"/api/users/{me['user_id']}/roles", json={"roles": ["admin"]}, headers=deputy
    )
    assert r.status_code == 200
    r = await client.put(f"/api/users/{deputy_id}/roles", json={"roles": []}, headers=NORTH_ADMIN)
    assert r.status_code == 200


async def test_disabled_user_is_refused_and_can_be_re_enabled(client: AsyncClient) -> None:
    newcomer = _new_north_user()
    user_id = (await _my_access(client, newcomer))["user_id"]
    await client.put(f"/api/users/{user_id}/roles", json={"roles": ["viewer"]}, headers=NORTH_ADMIN)

    r = await client.patch(
        f"/api/users/{user_id}", json={"status": "disabled"}, headers=NORTH_ADMIN
    )
    assert r.status_code == 200 and r.json()["status"] == "disabled"
    r = await client.get("/api/sites", headers=newcomer)
    assert r.status_code == 403 and "disabled" in r.json()["detail"]

    r = await client.patch(f"/api/users/{user_id}", json={"status": "active"}, headers=NORTH_ADMIN)
    assert r.status_code == 200
    assert (await client.get("/api/sites", headers=newcomer)).status_code == 200


async def test_admin_cannot_disable_themselves(client: AsyncClient) -> None:
    me = await _my_access(client, NORTH_ADMIN)
    r = await client.patch(
        f"/api/users/{me['user_id']}", json={"status": "disabled"}, headers=NORTH_ADMIN
    )
    assert r.status_code == 409


async def test_role_catalogue_uses_only_known_permissions(client: AsyncClient) -> None:
    r = await client.get("/api/roles", headers=NORTH_ADMIN)
    assert r.status_code == 200
    roles = {role["key"]: set(role["permissions"]) for role in r.json()}
    known = {p.value for p in Permission}
    assert set(roles) == {"admin", "operator", "viewer"}
    assert all(perms <= known for perms in roles.values())
    assert roles["admin"] == known
