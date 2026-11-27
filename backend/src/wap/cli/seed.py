"""Seed two demo tenants with sample sites and dev users. Safe to run more than once.

Runs as the schema owner. Tenant tables have FORCED row level security, so even
the owner sets the tenant before writing them.

The dev users match the Keycloak dev realm, whose users have fixed ids, so
their roles exist before they first sign in.

    python -m wap.cli.seed
"""

import psycopg

from wap.config import get_settings

DEMO_TENANTS: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "demo-north": (
        "Demo North Logistics",
        [("NDC1", "North distribution centre"), ("NXD2", "North cross-dock")],
    ),
    "demo-south": (
        "Demo South Fulfilment",
        [("SFC1", "South fulfilment centre")],
    ),
}


# username -> (Keycloak user id, email, display name, {tenant slug: roles})
DEV_USERS: dict[str, tuple[str, str, str, dict[str, list[str]]]] = {
    "north.admin": (
        "8f6d2c1e-4b7a-4e0f-9a51-1d2e3f4a5b01",
        "north.admin@example.com",
        "North Admin",
        {"demo-north": ["admin"]},
    ),
    "south.admin": (
        "8f6d2c1e-4b7a-4e0f-9a51-1d2e3f4a5b02",
        "south.admin@example.com",
        "South Admin",
        {"demo-south": ["admin"]},
    ),
    "ops.both": (
        "8f6d2c1e-4b7a-4e0f-9a51-1d2e3f4a5b03",
        "ops.both@example.com",
        "Ops Both",
        {"demo-north": ["viewer"], "demo-south": ["operator"]},
    ),
}


def _seed_users(
    conn: psycopg.Connection[tuple[object, ...]], slug: str, tenant_id: object, issuer: str
) -> int:
    count = 0
    for subject, email, name, grants in DEV_USERS.values():
        roles = grants.get(slug)
        if roles is None:
            continue
        row = conn.execute(
            """
            INSERT INTO kernel.users (tenant_id, issuer, subject, email, name)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, issuer, subject)
                DO UPDATE SET email = EXCLUDED.email, name = EXCLUDED.name
            RETURNING id
            """,
            (tenant_id, issuer, subject, email, name),
        ).fetchone()
        assert row is not None
        for role in roles:
            conn.execute(
                """
                INSERT INTO kernel.user_roles (tenant_id, user_id, role_key)
                VALUES (%s, %s, %s) ON CONFLICT DO NOTHING
                """,
                (tenant_id, row[0], role),
            )
        count += 1
    return count


def seed(conninfo: str, issuer: str) -> None:
    with psycopg.connect(conninfo) as conn:
        for slug, (name, sites) in DEMO_TENANTS.items():
            with conn.transaction():
                row = conn.execute(
                    """
                    INSERT INTO kernel.tenants (slug, name) VALUES (%s, %s)
                    ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
                    RETURNING id
                    """,
                    (slug, name),
                ).fetchone()
                assert row is not None
                tenant_id = row[0]
                conn.execute(
                    "SELECT set_config('app.tenant_id', %s, true), "
                    "set_config('app.actor_subject', 'system:seed', true)",
                    (str(tenant_id),),
                )
                for code, site_name in sites:
                    conn.execute(
                        """
                        INSERT INTO kernel.sites (tenant_id, code, name) VALUES (%s, %s, %s)
                        ON CONFLICT (tenant_id, code) DO UPDATE SET name = EXCLUDED.name
                        """,
                        (tenant_id, code, site_name),
                    )
                users = _seed_users(conn, slug, tenant_id, issuer)
            print(f"seeded tenant {slug} with {len(sites)} site(s) and {users} user(s)")


def main() -> None:
    settings = get_settings()
    seed(settings.migration_database_url, settings.oidc_issuer)


if __name__ == "__main__":
    main()
