"""ClickHouse client factory."""

import clickhouse_connect
from clickhouse_connect.driver.client import Client

from wap.config import Settings


def create_client(settings: Settings) -> Client:
    return clickhouse_connect.get_client(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password.get_secret_value(),
        database=settings.clickhouse_database,
    )
