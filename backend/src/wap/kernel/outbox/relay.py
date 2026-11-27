"""Ship committed outbox events to ClickHouse ``wap.platform_events``.

At-least-once: a batch is inserted into ClickHouse, then marked published in
the same Postgres transaction that locked it. If the process dies in between,
the batch is sent again; ClickHouse's ReplacingMergeTree keys on the event id,
so repeats collapse. ``FOR UPDATE SKIP LOCKED`` lets several relays run.
"""

import json
from dataclasses import dataclass
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row

CH_TABLE = "platform_events"
CH_COLUMNS = ["tenant_id", "event_id", "event_type", "occurred_at", "payload"]


class EventSink(Protocol):
    """The part of the ClickHouse client the relay uses."""

    def insert(self, table: str, data: Any, column_names: Any) -> Any: ...


@dataclass(frozen=True, slots=True)
class RelayResult:
    published: int
    failed: int


def relay_batch(
    conn: psycopg.Connection[Any], sink: EventSink, batch_size: int = 500
) -> RelayResult:
    """Publish up to ``batch_size`` pending events, oldest first. Connect as wap_relay."""
    with conn.transaction():
        cur = conn.cursor(row_factory=dict_row)
        rows = cur.execute(
            """
            SELECT id, tenant_id, event_type, occurred_at, payload
            FROM kernel.outbox
            WHERE published_at IS NULL
            ORDER BY occurred_at
            LIMIT %s
            FOR UPDATE SKIP LOCKED
            """,
            (batch_size,),
        ).fetchall()
        if not rows:
            return RelayResult(published=0, failed=0)
        ids = [r["id"] for r in rows]
        data = [
            [r["tenant_id"], r["id"], r["event_type"], r["occurred_at"], json.dumps(r["payload"])]
            for r in rows
        ]
        try:
            sink.insert(CH_TABLE, data, column_names=CH_COLUMNS)
        except Exception as exc:
            cur.execute(
                """
                UPDATE kernel.outbox SET attempts = attempts + 1, last_error = %s
                WHERE id = ANY(%s)
                """,
                (str(exc)[:1000], ids),
            )
            return RelayResult(published=0, failed=len(rows))
        cur.execute(
            "UPDATE kernel.outbox SET published_at = now(), last_error = NULL WHERE id = ANY(%s)",
            (ids,),
        )
        return RelayResult(published=len(rows), failed=0)
