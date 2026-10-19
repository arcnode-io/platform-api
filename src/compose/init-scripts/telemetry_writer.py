"""Subscribe to broker telemetry, INSERT into the timeseries DB.

The MQTT → DB bridge for the EMS stack. We own this rather than relying
on a broker plugin so the path works on any MQTT broker we deploy
(HiveMQ CE in production today; Mosquitto / VerneMQ if we ever swap).
Subscribes to ``sites/+/devices/+/measurements/+/+`` per the topic
contract in system_adr §9 and writes one row per publish.

Env contract (compose env_file: /opt/arcnode/secrets.env):
    TIMESERIES_URL    - postgres://user:pass@host:port/dbname
    BROKER            - broker hostname on the compose network (default: hivemq)
    CFG_CUSTOMER_PATH - the deployment's overlay; ``retention_days`` is how
                        long measurements are kept (the customer picks it)
"""

import json
import os

import paho.mqtt.client as mqtt
import psycopg2
import yaml
from psycopg2.extensions import connection

BROKER = os.environ.get("BROKER", "hivemq")
# Broker runs File RBAC since v1 — authenticate as the arcnode_telemetry_writer
# identity (sub measurements). Password from env; anonymous is rejected.
MQTT_USERNAME = os.environ.get("MQTT_USERNAME", "arcnode_telemetry_writer")
MQTT_PASSWORD = os.environ.get("MQTT_TELEMETRY_WRITER_PASSWORD", "")
TOPIC = "sites/+/devices/+/measurements/+/+"

INSERT_SQL = (
    "INSERT INTO measurements "
    "(ts, site_id, device_id, measurement, unit, value) "
    "VALUES (%s::timestamptz, %s, %s, %s, %s, %s::jsonb)"
)

# Idempotent schema bootstrap — runs every restart, on every deployment.
# Defense uses Aurora + pg_partman (no TimescaleDB), so the hypertable
# call must be conditional on the extension being present. Tiger Cloud
# ships TimescaleDB preinstalled; on-prem operators install it on
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


def on_connect(
    client: mqtt.Client,
    _userdata: object,
    _flags: object,
    reason_code: object,
    _properties: object = None,
) -> None:
    """(Re-)subscribe on every successful connect, including reconnects.

    Reason: an MQTT subscription is broker-side session state, not
    client-side — a broker restart wipes it, and paho-python has no
    auto-resubscribe (unlike mqtt.js's `resubscribe: true`). paho calls
    on_connect on every successful connection including reconnects, so
    subscribing here (not once at module level) is what keeps this alive
    across a broker blip. Without it: publishing still works, so nothing
    looks wrong, but this bridge silently stops persisting all telemetry
    forever with no error.
    """
    client.subscribe(TOPIC)
    print(
        f"subscribed to {TOPIC} on {BROKER}:1883 (reason_code={reason_code})",
        flush=True,
    )


def on_message(
    _client: mqtt.Client,
    conn: connection,
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


def bootstrap_schema(conn: connection) -> None:
    """Create measurements if it's missing. On defense the Aurora bootstrap
    Lambda already made it (partitioned), so every statement is a no-op there."""
    with conn.cursor() as cur:
        for stmt in SCHEMA_SQL:
            cur.execute(stmt)
    print("measurements bootstrap done", flush=True)


def apply_retention(conn: connection, days: int) -> None:
    """Keep `days` of measurements; older rows get dropped by the database itself.

    TimescaleDB (commercial, on-prem) runs a retention job; pg_partman (defense)
    drops expired partitions when its pg_cron maintenance runs. Re-applied on
    every start, so a changed window takes over from the old one.
    """
    window = f"{days} days"
    with conn.cursor() as cur:
        cur.execute(
            "SELECT extname FROM pg_extension "
            "WHERE extname IN ('timescaledb', 'pg_partman')"
        )
        extensions = {row[0] for row in cur.fetchall()}
        if "timescaledb" in extensions:
            # Reason: add_retention_policy won't change an existing policy's window.
            cur.execute(
                "SELECT remove_retention_policy('measurements', if_exists => true)"
            )
            cur.execute(
                "SELECT add_retention_policy('measurements', drop_after => %s::interval)",
                (window,),
            )
        elif "pg_partman" in extensions:
            cur.execute(
                "UPDATE partman.part_config "
                "SET retention = %s, retention_keep_table = false "
                "WHERE parent_table = 'public.measurements'",
                (window,),
            )
            if cur.rowcount != 1:
                raise RuntimeError("measurements isn't registered with pg_partman")
        else:
            raise RuntimeError(
                "no retention for measurements: the database has neither "
                "TimescaleDB nor pg_partman, so old rows would fill the disk"
            )
    print(f"measurements retention: {window}", flush=True)


def load_retention_days(path: str) -> int:
    """`retention_days` from the deployment's overlay."""
    with open(path) as f:
        return int(yaml.safe_load(f)["retention_days"])


def main() -> None:
    """Bootstrap the table, apply the retention window, then bridge MQTT → DB forever."""
    conn = psycopg2.connect(os.environ["TIMESERIES_URL"])
    conn.autocommit = True
    bootstrap_schema(conn)
    apply_retention(conn, load_retention_days(os.environ["CFG_CUSTOMER_PATH"]))
    # paho-mqtt v2 — VERSION1 callback API would warn at runtime, VERSION2 is the
    # supported callback shape for new code (extra `properties` arg, etc.).
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, userdata=conn)
    client.on_connect = on_connect
    client.on_message = on_message
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.connect(BROKER, 1883, keepalive=60)
    client.loop_forever()


if __name__ == "__main__":
    main()
