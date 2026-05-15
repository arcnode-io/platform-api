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
# paho-mqtt v2 — VERSION1 callback API would warn at runtime, VERSION2 is the
# supported callback shape for new code (extra `properties` arg, etc.).
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_message = on_message
client.connect(BROKER, 1883, keepalive=60)
client.subscribe(TOPIC)
print(f"subscribed to {TOPIC} on {BROKER}:1883", flush=True)
client.loop_forever()
