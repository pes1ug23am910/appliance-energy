CREATE TABLE devices (
 device_id varchar(64) PRIMARY KEY,
 name varchar(120) NOT NULL,
 desired_revision bigint NOT NULL DEFAULT 0 CHECK (desired_revision >= 0),
 desired_power boolean NOT NULL DEFAULT false,
 desired_speed integer NOT NULL DEFAULT 0 CHECK (desired_speed BETWEEN 0 AND 100),
 reported_revision bigint NOT NULL DEFAULT 0 CHECK (reported_revision >= 0),
 reported_power boolean NOT NULL DEFAULT false,
 reported_speed integer NOT NULL DEFAULT 0 CHECK (reported_speed BETWEEN 0 AND 100),
 reported_boot uuid,
 reported_sequence bigint,
 reported_observed_at timestamptz,
 last_seen timestamptz,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE commands (
 command_id uuid PRIMARY KEY,
 device_id varchar(64) NOT NULL REFERENCES devices(device_id),
 expected_revision bigint NOT NULL,
 revision bigint NOT NULL,
 power boolean NOT NULL,
 speed_percent integer NOT NULL CHECK (speed_percent BETWEEN 0 AND 100),
 expires_at timestamptz NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 attempted_at timestamptz,
 status varchar(24) NOT NULL CHECK (status IN ('accepted','awaiting_device','confirmed','expired','superseded','outcome_unknown','rejected')),
 UNIQUE(device_id,revision)
);
CREATE INDEX commands_pending_expiry ON commands(expires_at) WHERE status IN ('accepted','awaiting_device');
CREATE TABLE telemetry (
 event_id uuid PRIMARY KEY,
 device_id varchar(64) NOT NULL REFERENCES devices(device_id),
 boot_id uuid NOT NULL,
 sequence bigint NOT NULL CHECK (sequence >= 0),
 event_time timestamptz NOT NULL,
 received_at timestamptz NOT NULL,
 payload jsonb NOT NULL,
 payload_hash varchar(64) NOT NULL,
 UNIQUE(device_id,boot_id,sequence)
);
CREATE INDEX telemetry_device_received ON telemetry(device_id,received_at DESC,event_id);
CREATE TABLE outbox (
 id bigserial PRIMARY KEY,
 kind varchar(16) NOT NULL CHECK (kind IN ('desired','receipt','telemetry')),
 dedup_key varchar(100) NOT NULL,
 device_id varchar(64) NOT NULL,
 payload jsonb NOT NULL,
 attempts integer NOT NULL DEFAULT 0,
 available_at timestamptz NOT NULL DEFAULT now(),
 published_at timestamptz,
 last_error varchar(500),
 UNIQUE(kind,dedup_key)
);
CREATE INDEX outbox_pending ON outbox(available_at,id) WHERE published_at IS NULL;
CREATE TABLE quarantine (
 id bigserial PRIMARY KEY,
 topic varchar(256) NOT NULL,
 payload text NOT NULL,
 reason varchar(1000) NOT NULL,
 received_at timestamptz NOT NULL DEFAULT now()
);
