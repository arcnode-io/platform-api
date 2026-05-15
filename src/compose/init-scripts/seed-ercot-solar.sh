#!/bin/sh
# Seed the ERCOT solar historical reference dataset into the timeseries
# database. This is static analyst-API training data, NOT live broker
# ingest — the `measurements` table (partman-managed, fed by the
# telemetry-writer sidecar from MQTT) is separate.
#
# Tarball format: pg_dump --format=directory of a TimescaleDB-backed
# Tiger Cloud database. On Tiger the restore lands cleanly (TS extension
# present). On Aurora pg_partman (defense variant) the table rows still
# land but TimescaleDB-specific triggers/chunks fail at restore — that's
# tolerated with `|| true`; analyst-API reads the tables as plain
# Postgres. A defense-specific dump (no TS) is a future improvement.
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

if psql "$TIMESERIES_URL" -tAc "SELECT 1 FROM arcnode_seed_markers WHERE slice = 'ercot_solar'" | grep -q 1; then
  echo "ercot_solar already seeded; exiting"
  exit 0
fi

# Tarball is pg_dump --format=directory output (toc.dat + .dat files).
# Directory format can't be streamed — extract to a tempdir then point
# pg_restore at it.
TMPDIR=$(mktemp -d)
curl -fsSL https://arcnode-public.s3.us-east-1.amazonaws.com/seed/ercot-solar.tar.gz \
  | tar -xz -C "$TMPDIR"
# pg_restore returns 1 when any error occurs even if it continued — on
# Aurora the TimescaleDB-specific statements miss. `|| true` swallows
# the per-statement errors; table data still lands.
pg_restore --format=directory --dbname "$TIMESERIES_URL" --no-owner --no-privileges "$TMPDIR" || true
rm -rf "$TMPDIR"

psql "$TIMESERIES_URL" -c \
  "INSERT INTO arcnode_seed_markers (slice) VALUES ('ercot_solar') ON CONFLICT DO NOTHING"

echo "ercot_solar seeded"
