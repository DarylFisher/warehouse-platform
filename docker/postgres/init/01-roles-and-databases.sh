#!/bin/bash
# Runs once, when the Postgres data volume is first created.
#
# Roles:
#   wap_owner  owns the schema and runs migrations
#   wap_app    used by the running application: not an owner, no BYPASSRLS,
#              so row level security always applies to it
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-SQL
  CREATE ROLE wap_owner LOGIN PASSWORD '${WAP_OWNER_PASSWORD}';
  CREATE ROLE wap_app LOGIN PASSWORD '${WAP_APP_PASSWORD}' NOBYPASSRLS;

  CREATE DATABASE wap OWNER wap_owner;
  CREATE DATABASE wap_test OWNER wap_owner;
SQL

for db in wap wap_test; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" <<-SQL
    REVOKE ALL ON SCHEMA public FROM PUBLIC;
    GRANT CONNECT ON DATABASE $db TO wap_app;
SQL
done
