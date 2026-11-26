"""Test fixtures.

Integration tests need a disposable database (``wap_test`` locally) given by
WAP_TEST_DATABASE_URL (app role) and WAP_TEST_MIGRATION_DATABASE_URL (owner),
plus ClickHouse from the WAP_CLICKHOUSE_* settings. Each session rebuilds the
kernel schema from scratch, so tests never depend on leftover data.
"""

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from auth_support import make_verifier
from httpx import ASGITransport, AsyncClient
from psycopg import AsyncConnection
from psycopg.rows import DictRow
from psycopg_pool import AsyncConnectionPool

from wap.api.main import create_app
from wap.cli.seed import seed
from wap.config import Settings, get_settings
from wap.db import create_pool

BACKEND_DIR = Path(__file__).resolve().parent.parent

TEST_DB_URL = os.environ.get("WAP_TEST_DATABASE_URL")
TEST_OWNER_URL = os.environ.get("WAP_TEST_MIGRATION_DATABASE_URL")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if TEST_DB_URL and TEST_OWNER_URL:
        return
    skip = pytest.mark.skip(
        reason="WAP_TEST_DATABASE_URL / WAP_TEST_MIGRATION_DATABASE_URL not set"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


def _alembic(*args: str) -> None:
    assert TEST_OWNER_URL
    env = {**os.environ, "ALEMBIC_DATABASE_URL": TEST_OWNER_URL}
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND_DIR, env=env, check=True)


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    assert TEST_DB_URL and TEST_OWNER_URL
    return Settings(database_url=TEST_DB_URL, migration_database_url=TEST_OWNER_URL)


@pytest.fixture(scope="session")
def migrated_db(test_settings: Settings) -> Settings:
    _alembic("downgrade", "base")
    _alembic("upgrade", "head")
    seed(test_settings.migration_database_url)
    return test_settings


@pytest.fixture(scope="session")
async def pool(
    migrated_db: Settings,
) -> AsyncIterator[AsyncConnectionPool[AsyncConnection[DictRow]]]:
    p = create_pool(migrated_db)
    await p.open(wait=True)
    yield p
    await p.close()


@pytest.fixture(scope="session")
async def client(
    migrated_db: Settings, pool: AsyncConnectionPool[AsyncConnection[DictRow]]
) -> AsyncIterator[AsyncClient]:
    app = create_app()
    app.state.pool = pool
    app.state.clickhouse = None
    app.state.verifier = make_verifier()
    app.dependency_overrides[get_settings] = lambda: migrated_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
