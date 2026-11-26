"""Alembic environment for kernel migrations.

Kernel tables only. Tables that apps define in metadata are created by the
platform's own migration engine (M2), never by Alembic.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from wap.config import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _url() -> str:
    url = os.environ.get("ALEMBIC_DATABASE_URL") or get_settings().migration_database_url
    # Use the psycopg 3 driver.
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


def run_migrations_offline() -> None:
    context.configure(url=_url(), literal_binds=True, version_table_schema="public")
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, version_table_schema="public")
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
