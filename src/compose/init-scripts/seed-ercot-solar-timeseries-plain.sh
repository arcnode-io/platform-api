#!/bin/sh
# Seed the ERCOT solar historical reference dataset into the timeseries
# database. Static analyst-API training data, NOT live broker ingest —
# the `measurements` table (partman-managed, fed by the telemetry-writer
# sidecar from MQTT) is separate.
#
# Format: plain pg_dump (gzipped). Source was a TimescaleDB hypertable
# on Tiger Cloud; we re-baked it to a plain table so it lands cleanly
# on Aurora (no TS extension) AND on Tiger (TS extension just doesn't
# get used for this static set — partitioning buys nothing for a
# fixed snapshot).
#
# Idempotency: a DB-side marker tracks per-slice seeded state. Marker
# survives EC2 instance replacement.
#
# Required env (from /opt/arcnode/secrets.env):
#   TIMESERIES_URL — postgres://user:pass@host:port/dbname[?...]
set -eu

apk add --no-cache postgresql-client curl >/dev/null

psql "$TIMESERIES_URL" -c \
  "CREATE TABLE IF NOT EXISTS arcnode_seed_markers (slice TEXT PRIMARY KEY, seeded_at TIMESTAMPTZ DEFAULT now())"

if psql "$TIMESERIES_URL" -tAc "SELECT 1 FROM arcnode_seed_markers WHERE slice = 'ercot_solar_timeseries'" | grep -q 1; then
  echo "ercot_solar_timeseries already seeded; exiting"
  exit 0
fi

curl -fsSL https://arcnode-public.s3.us-east-1.amazonaws.com/seed/ercot-solar-timeseries.sql.gz \
  | gunzip \
  | psql "$TIMESERIES_URL"

psql "$TIMESERIES_URL" -c \
  "INSERT INTO arcnode_seed_markers (slice) VALUES ('ercot_solar_timeseries') ON CONFLICT DO NOTHING"

echo "ercot_solar_timeseries seeded"
