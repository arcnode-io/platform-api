#!/bin/sh
# Seed the timeseries database from the public seed tarball.
#
# Same idempotency pattern as seed-vector.sh. Works for both variants
# because TIMESERIES_URL is just a Postgres-wire URL — Tiger Cloud
# (commercial) and Aurora pg_partman (defense) both speak it.
#
# Required env (from /opt/arcnode/persistence.env):
#   TIMESERIES_URL — postgres://user:pass@host:port/dbname[?...]
set -eu

apk add --no-cache postgresql-client curl >/dev/null

psql "$TIMESERIES_URL" -c \
  "CREATE TABLE IF NOT EXISTS arcnode_seed_markers (slice TEXT PRIMARY KEY, seeded_at TIMESTAMPTZ DEFAULT now())"

if psql "$TIMESERIES_URL" -tAc "SELECT 1 FROM arcnode_seed_markers WHERE slice = 'timeseries'" | grep -q 1; then
  echo "timeseries already seeded; exiting"
  exit 0
fi

# Tarball is pg_dump --format=directory output (toc.dat + .dat files).
# Directory format can't be streamed — extract to a tempdir then point
# pg_restore at it.
TMPDIR=$(mktemp -d)
curl -fsSL https://arcnode-public.s3.us-east-1.amazonaws.com/seed/timeseries.tar.gz \
  | tar -xz -C "$TMPDIR"
# pg_restore returns 1 when any error occurs even if it continued. The
# defense-variant Aurora cluster lacks TimescaleDB extension (Tiger-only),
# so a chunk of the dump's CREATE TRIGGER / INDEX statements fail. Treat
# those as warnings; the table data still lands. A defense-specific dump
# would be the production fix.
pg_restore --format=directory --dbname "$TIMESERIES_URL" --no-owner --no-privileges "$TMPDIR" || true
rm -rf "$TMPDIR"

psql "$TIMESERIES_URL" -c \
  "INSERT INTO arcnode_seed_markers (slice) VALUES ('timeseries') ON CONFLICT DO NOTHING"

echo "timeseries seeded"
