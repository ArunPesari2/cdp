-- 0001: core profile tables for the care slice.
-- Migrations are applied in order and never edited after they are applied.
-- v1 stores email/phone in clear text for debuggability; hashing comes in a later migration.

CREATE TABLE Customer (
  customer_id STRING(36) NOT NULL,
  first_name  STRING(100),
  last_name   STRING(100),
  email       STRING(255),
  phone       STRING(20),
  status      STRING(16),
  created_at  TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp = true),
  updated_at  TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp = true)
) PRIMARY KEY (customer_id);

CREATE TABLE IdentityMap (
  id_type     STRING(16) NOT NULL,
  id_value    STRING(255) NOT NULL,
  customer_id STRING(36) NOT NULL,
  created_at  TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp = true)
) PRIMARY KEY (id_type, id_value);

CREATE INDEX IdentityByCustomer ON IdentityMap(customer_id);

CREATE TABLE Interaction (
  customer_id  STRING(36) NOT NULL,
  event_ts     TIMESTAMP NOT NULL,
  event_id     STRING(64) NOT NULL,
  event_type   STRING(64) NOT NULL,
  channel      STRING(16),
  intent       STRING(64),
  agent_id     STRING(32),
  duration_sec INT64,
  summary      STRING(MAX),
  source       STRING(32) NOT NULL,
  processed_at TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp = true)
) PRIMARY KEY (customer_id, event_ts DESC, event_id),
  INTERLEAVE IN PARENT Customer ON DELETE CASCADE,
  ROW DELETION POLICY (OLDER_THAN(event_ts, INTERVAL 90 DAY));
