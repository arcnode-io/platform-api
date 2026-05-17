"""Subscribe to broker telemetry, INSERT into the timeseries DB.

The MQTT → DB bridge for the EMS stack. We own this rather than relying
on a broker plugin so the path works on any MQTT broker we deploy
(HiveMQ CE in production today; Mosquitto / VerneMQ if we ever swap).
Subscribes to ``sites/+/devices/+/measurements/+/+`` per the topic
contract in system_adr §9 and writes one row per publish.

Env contract (compose env_file: /opt/arcnode/secrets.env):
    TIMESERIES_URL  - postgres://user:pass@host:port/dbname
    BROKER          - broker hostname on the compose network (default: hivemq)
"""

import json
import os

import paho.mqtt.client as mqtt
import psycopg2

TIMESERIES_URL = os.environ["TIMESERIES_URL"]
BROKER = os.environ.get("BROKER", "hivemq")
TOPIC = "sites/+/devices/+/measurements/+/+"

INSERT_SQL = (
    "INSERT INTO measurements "
    "(ts, site_id, device_id, measurement, unit, value) "
    "VALUES (%s::timestamptz, %s, %s, %s, %s, %s::jsonb)"
)

# Idempotent schema bootstrap — runs every restart, three-tier safe.
# Defense uses Aurora + pg_partman (no TimescaleDB), so the hypertable
# call must be conditional on the extension being present. Tiger Cloud
# ships TimescaleDB preinstalled; airgapped operators install it on
# their self-hosted Postgres. Same INSERT signature everywhere so
# consumer code doesn't branch.
SCHEMA_SQL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS measurements (
        ts          TIMESTAMPTZ NOT NULL,
        site_id     TEXT        NOT NULL,
        device_id   TEXT        NOT NULL,
        measurement TEXT        NOT NULL,
        unit        TEXT        NOT NULL,
        value       JSONB       NOT NULL
    )
    """,
    """
    DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
            PERFORM create_hypertable('measurements', 'ts', if_not_exists => TRUE);
        END IF;
    END $$
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_measurements_lookup
        ON measurements (site_id, device_id, measurement, ts DESC)
    """,
)


def on_message(
    _client: mqtt.Client,
    _userdata: object,
    msg: mqtt.MQTTMessage,
    _properties: object = None,
) -> None:
    """Parse a single MQTT publish and INSERT one row into measurements."""
    # Topic: sites/{site}/devices/{device}/measurements/{measurement}/{unit}
    parts = msg.topic.split("/")
    if len(parts) != 7:
        print(f"skip unexpected topic shape: {msg.topic}", flush=True)
        return
    _, site, _, device, _, meas, unit = parts
    try:
        payload = json.loads(msg.payload)
        ts = payload["ts"]
        value = payload["value"]
    except (json.JSONDecodeError, KeyError) as e:
        print(f"skip malformed payload on {msg.topic}: {e}", flush=True)
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                INSERT_SQL,
                (ts, site, device, meas, unit, json.dumps(value)),
            )
        print(f"wrote: {site}/{device}/{meas}/{unit} = {value}", flush=True)
    except psycopg2.Error as e:
        print(f"insert failed on {msg.topic}: {e}", flush=True)


conn = psycopg2.connect(TIMESERIES_URL)
conn.autocommit = True
# Per-statement try: on defense the Aurora bootstrap Lambda already
# created the table + index as the master user, and telemetry-writer
# connects as ems_ts_app (GRANT ALL, but not the owner). Postgres
# requires ownership for CREATE INDEX even with IF NOT EXISTS — log
# and continue. On commercial (Tiger) + airgapped (self-hosted) the
# writer creates first → owns → all statements succeed.
with conn.cursor() as _cur:
    for _stmt in SCHEMA_SQL:
        try:
            _cur.execute(_stmt)
        except psycopg2.Error as _e:
            print(f"schema bootstrap skip: {_e}", flush=True)
print("measurements bootstrap done", flush=True)
# paho-mqtt v2 — VERSION1 callback API would warn at runtime, VERSION2 is the
# supported callback shape for new code (extra `properties` arg, etc.).
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_message = on_message
client.connect(BROKER, 1883, keepalive=60)
client.subscribe(TOPIC)
print(f"subscribed to {TOPIC} on {BROKER}:1883", flush=True)
client.loop_forever()
