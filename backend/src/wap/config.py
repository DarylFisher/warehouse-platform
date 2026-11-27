"""Settings, read from WAP_* environment variables (and .env when present)."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WAP_", env_file=".env", extra="ignore")

    # The app connects as a non-owner role so row level security always applies.
    database_url: str = "postgresql://wap_app:wap_app_dev@localhost:5433/wap"
    # Migrations and seeding run as the schema owner.
    migration_database_url: str = "postgresql://wap_owner:wap_owner_dev@localhost:5433/wap"

    # The outbox relay connects as a role that can read and mark outbox events only.
    relay_database_url: str = "postgresql://wap_relay:wap_relay_dev@localhost:5433/wap"
    relay_batch_size: int = 500

    db_pool_min_size: int = 1
    db_pool_max_size: int = 10

    clickhouse_host: str = "localhost"
    clickhouse_port: int = 8123
    clickhouse_user: str = "wap"
    clickhouse_password: SecretStr = SecretStr("wap_dev")
    clickhouse_database: str = "wap"

    # OIDC. The issuer must match the token's `iss` exactly. Signing keys come
    # from `oidc_jwks_url` when set (e.g. a Docker-internal address), otherwise
    # from the issuer's discovery document.
    oidc_issuer: str = "http://localhost:8180/realms/wap-dev"
    oidc_audience: str = "wap-api"
    oidc_jwks_url: str | None = None
    # Group-name prefix that grants access to a tenant: `tenant-<slug>`.
    oidc_tenant_group_prefix: str = "tenant-"


@lru_cache
def get_settings() -> Settings:
    return Settings()
