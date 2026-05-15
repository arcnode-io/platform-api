#!/bin/sh
# Seed the ERCOT solar historical reference dataset into the timeseries
# database — TimescaleDB-native variant for Tiger Cloud (commercial) and
# ISO variants. Static analyst-API training data, NOT live broker
# ingest — the `measurements` table (managed separately) is the live
# slice.
#
# Format: pg_dump --format=directory of a TimescaleDB hypertable.
# Restores cleanly when the destination DB has the timescaledb
# extension enabled (Tiger Cloud, ISO bring-your-own-TS). For Aurora
# pg_partman destinations, use the -plain variant instead.
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

# Directory format can't be streamed — extract to tempdir then point
# pg_restore at it.
TMPDIR=$(mktemp -d)
curl -fsSL https://arcnode-public.s3.us-east-1.amazonaws.com/seed/ercot-solar-timeseries.tar.gz \
  | tar -xz -C "$TMPDIR"
pg_restore --format=directory --dbname "$TIMESERIES_URL" --no-owner --no-privileges "$TMPDIR"
rm -rf "$TMPDIR"

psql "$TIMESERIES_URL" -c \
  "INSERT INTO arcnode_seed_markers (slice) VALUES ('ercot_solar_timeseries') ON CONFLICT DO NOTHING"

echo "ercot_solar_timeseries seeded"
