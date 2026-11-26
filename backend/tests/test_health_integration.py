"""Readiness against real Postgres and ClickHouse."""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration


async def test_ready_when_both_databases_are_up(client: AsyncClient) -> None:
    r = await client.get("/health/ready")
    assert r.json() == {"status": "ok", "postgres": "ok", "clickhouse": "ok"}
    assert r.status_code == 200


async def test_clickhouse_event_table_exists(client: AsyncClient) -> None:
    from wap.clickhouse import create_client
    from wap.config import get_settings

    ch = create_client(get_settings())
    try:
        assert ch.command("EXISTS TABLE wap.platform_events") == 1
    finally:
        ch.close()
