"""Seed two demo tenants with sample sites. Safe to run more than once.

Runs as the schema owner. Sites have FORCED row level security, so even the
owner sets the tenant before writing them.

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


def seed(conninfo: str) -> None:
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
                conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))
                for code, site_name in sites:
                    conn.execute(
                        """
                        INSERT INTO kernel.sites (tenant_id, code, name) VALUES (%s, %s, %s)
                        ON CONFLICT (tenant_id, code) DO UPDATE SET name = EXCLUDED.name
                        """,
                        (tenant_id, code, site_name),
                    )
            print(f"seeded tenant {slug} with {len(sites)} site(s)")


def main() -> None:
    seed(get_settings().migration_database_url)


if __name__ == "__main__":
    main()
