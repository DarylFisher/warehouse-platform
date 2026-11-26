"""Apply a ClickHouse SQL file statement by statement.

Used by CI and when running ClickHouse outside docker-compose, so every
environment builds the schema from the same file:

    python -m wap.cli.ch_init ../docker/clickhouse/init/01-schema.sql
"""

import sys
from pathlib import Path

from wap.clickhouse import create_client
from wap.config import get_settings


def split_statements(sql: str) -> list[str]:
    lines = [line for line in sql.splitlines() if not line.lstrip().startswith("--")]
    return [stmt.strip() for stmt in "\n".join(lines).split(";") if stmt.strip()]


def main(argv: list[str]) -> None:
    if len(argv) != 1:
        raise SystemExit("usage: python -m wap.cli.ch_init <file.sql>")
    statements = split_statements(Path(argv[0]).read_text())
    client = create_client(get_settings())
    try:
        for stmt in statements:
            client.command(stmt)
    finally:
        client.close()
    print(f"applied {len(statements)} statement(s)")


if __name__ == "__main__":
    main(sys.argv[1:])
