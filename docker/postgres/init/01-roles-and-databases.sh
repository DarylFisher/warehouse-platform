#!/bin/bash
# Runs once, when the Postgres data volume is first created. Safe to re-run on
# an existing volume to add roles introduced later: `just db-roles`.
#
# Roles:
#   wap_owner  owns the schema and runs migrations
#   wap_app    used by the running application: not an owner, no BYPASSRLS,
#              so row level security always applies to it
#   wap_relay  used by the outbox relay: may read and mark outbox events of
#              every tenant (an explicit RLS policy), and nothing else
set -euo pipefail

: "${WAP_RELAY_PASSWORD:=wap_relay_dev}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-SQL
  DO \$\$
  BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'wap_owner') THEN
      CREATE ROLE wap_owner LOGIN PASSWORD '${WAP_OWNER_PASSWORD}';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'wap_app') THEN
      CREATE ROLE wap_app LOGIN PASSWORD '${WAP_APP_PASSWORD}' NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'wap_relay') THEN
      CREATE ROLE wap_relay LOGIN PASSWORD '${WAP_RELAY_PASSWORD}' NOBYPASSRLS;
    END IF;
  END
  \$\$;

  SELECT 'CREATE DATABASE wap OWNER wap_owner'
  WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'wap') \gexec
  SELECT 'CREATE DATABASE wap_test OWNER wap_owner'
  WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'wap_test') \gexec
SQL

for db in wap wap_test; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" <<-SQL
    REVOKE ALL ON SCHEMA public FROM PUBLIC;
    GRANT CONNECT ON DATABASE $db TO wap_app, wap_relay;
SQL
done
