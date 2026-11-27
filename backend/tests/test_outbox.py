"""Transactional outbox and relay, against real Postgres and ClickHouse."""

import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from auth_support import bearer_as
from clickhouse_connect.driver.client import Client
from httpx import AsyncClient

from wap.clickhouse import create_client
from wap.config import get_settings
from wap.kernel.outbox import is_valid_event_type, relay_batch

pytestmark = pytest.mark.integration

RelayConn = psycopg.Connection[tuple[object, ...]]
NORTH_ADMIN = bearer_as("north.admin")


@pytest.fixture
def ch() -> Iterator[Client]:
    client = create_client(get_settings())
    yield client
    client.close()


def _events(relay_conn: RelayConn, site_id: str) -> list[tuple[Any, ...]]:
    """The site's events: its ``site.created`` and the audit entry for its row."""
    return relay_conn.execute(
        """
        SELECT id, event_type, payload, published_at, attempts, last_error
        FROM kernel.outbox
        WHERE payload->>'site_id' = %(id)s OR payload->>'row_id' = %(id)s
        ORDER BY occurred_at
        """,
        {"id": site_id},
    ).fetchall()


def _site_created(relay_conn: RelayConn, site_id: str) -> tuple[Any, ...]:
    (event,) = [e for e in _events(relay_conn, site_id) if e[1] == "site.created"]
    return event


def _drain(relay_conn: RelayConn, sink: Any) -> None:
    while relay_batch(relay_conn, sink).published:
        pass


async def _create_site(client: AsyncClient) -> str:
    code = f"O{uuid.uuid4().hex[:8].upper()}"
    r = await client.post("/api/sites", json={"code": code, "name": "Outbox"}, headers=NORTH_ADMIN)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_a_write_emits_its_event_and_audit_entry(
    client: AsyncClient, relay_conn: RelayConn
) -> None:
    site_id = await _create_site(client)
    events = _events(relay_conn, site_id)
    assert sorted(e[1] for e in events) == ["audit.recorded", "site.created"]
    assert all(e[3] is None for e in events)  # not yet published


async def test_relay_ships_events_to_clickhouse_and_marks_them(
    client: AsyncClient, relay_conn: RelayConn, ch: Client
) -> None:
    site_id = await _create_site(client)
    _drain(relay_conn, ch)

    event = _site_created(relay_conn, site_id)
    assert event[3] is not None and event[4] == 0
    rows = ch.query(
        "SELECT event_type, JSONExtractString(payload, 'site_id') FROM platform_events FINAL "
        "WHERE event_id = {id:UUID}",
        parameters={"id": event[0]},
    ).result_rows
    assert rows == [("site.created", site_id)]


async def test_rolled_back_change_emits_nothing(client: AsyncClient, relay_conn: RelayConn) -> None:
    me = (await client.get("/api/me/access", headers=NORTH_ADMIN)).json()
    before = relay_conn.execute("SELECT count(*) FROM kernel.outbox").fetchone()
    r = await client.put(
        f"/api/users/{me['user_id']}/roles", json={"roles": []}, headers=NORTH_ADMIN
    )
    assert r.status_code == 409
    after = relay_conn.execute("SELECT count(*) FROM kernel.outbox").fetchone()
    assert before == after


class _FailingSink:
    def insert(self, table: str, data: Any, column_names: Any) -> Any:
        raise ConnectionError("clickhouse is down")


async def test_failed_delivery_is_recorded_and_retried(
    client: AsyncClient, relay_conn: RelayConn, ch: Client
) -> None:
    _drain(relay_conn, ch)  # start from an empty queue
    site_id = await _create_site(client)

    result = relay_batch(relay_conn, _FailingSink())
    assert result.failed >= 2 and result.published == 0
    events = _events(relay_conn, site_id)
    assert all(e[3] is None and e[4] == 1 and "down" in e[5] for e in events)

    _drain(relay_conn, ch)
    events = _events(relay_conn, site_id)
    assert all(e[3] is not None and e[5] is None for e in events)


class _InsertThenCrash:
    """Delivers to ClickHouse, then fails before the outbox is marked: a resend follows."""

    def __init__(self, ch: Client) -> None:
        self.ch = ch

    def insert(self, table: str, data: Any, column_names: Any) -> Any:
        self.ch.insert(table, data, column_names=column_names)
        raise RuntimeError("crashed after delivery")


async def test_resent_events_collapse_in_clickhouse(
    client: AsyncClient, relay_conn: RelayConn, ch: Client
) -> None:
    _drain(relay_conn, ch)
    site_id = await _create_site(client)
    relay_batch(relay_conn, _InsertThenCrash(ch))  # delivered once, not marked
    _drain(relay_conn, ch)  # delivered again, marked

    event = _site_created(relay_conn, site_id)
    count = ch.query(
        "SELECT count() FROM platform_events FINAL WHERE event_id = {id:UUID}",
        parameters={"id": event[0]},
    ).result_rows[0][0]
    assert count == 1


async def test_audit_entries_reach_clickhouse_with_their_tenant(
    client: AsyncClient, relay_conn: RelayConn, ch: Client
) -> None:
    site_id = await _create_site(client)
    _drain(relay_conn, ch)
    rows = ch.query(
        "SELECT tenant_id, JSONExtractString(payload, 'action') FROM platform_events FINAL "
        "WHERE event_type = 'audit.recorded' "
        "AND JSONExtractString(payload, 'row_id') = {id:String}",
        parameters={"id": site_id},
    ).result_rows
    assert len(rows) == 1 and rows[0][1] == "insert"
    # The ClickHouse row carries the tenant the audit entry was written for (north).
    site_event = relay_conn.execute(
        "SELECT tenant_id FROM kernel.outbox "
        "WHERE event_type = 'site.created' AND payload->>'site_id' = %s",
        (site_id,),
    ).fetchone()
    assert site_event is not None and rows[0][0] == site_event[0]


@pytest.mark.parametrize(
    ("event_type", "valid"),
    [
        ("site.created", True),
        ("audit.recorded", True),
        ("a.b_c.d", True),
        ("site", False),
        ("Site.created", False),
        ("site.", False),
        ("site..created", False),
    ],
)
def test_event_type_names(event_type: str, valid: bool) -> None:
    assert is_valid_event_type(event_type) is valid
