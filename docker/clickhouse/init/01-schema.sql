-- Runs once, when the ClickHouse data volume is first created.
-- Analytics tables arrive in M5; this placeholder records platform events so the
-- outbox relay has a target from the start. tenant_id leads every sort key.

CREATE DATABASE IF NOT EXISTS wap;

CREATE TABLE IF NOT EXISTS wap.platform_events
(
    tenant_id   UUID,
    event_id    UUID,
    event_type  LowCardinality(String),
    occurred_at DateTime64(3, 'UTC'),
    payload     String
)
ENGINE = ReplacingMergeTree
PARTITION BY toYYYYMM(occurred_at)
ORDER BY (tenant_id, event_type, occurred_at, event_id);
