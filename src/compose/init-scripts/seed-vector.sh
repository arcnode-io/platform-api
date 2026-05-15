#!/bin/sh
# Seed the Aurora ems_vector database from the public seed tarball.
#
# Idempotent: a DB-side marker table tracks per-slice seeded state.
# Marker survives EC2 instance replacement (CFN updates that swap the EC2
# but keep Aurora alive). Re-run = exit 0 fast, no duplicate inserts.
#
# Required env (from /opt/arcnode/persistence.env):
#   VECTOR_URL — postgres://user:pass@host:port/dbname
set -eu

apk add --no-cache postgresql-client curl >/dev/null

psql "$VECTOR_URL" -c \
  "CREATE TABLE IF NOT EXISTS arcnode_seed_markers (slice TEXT PRIMARY KEY, seeded_at TIMESTAMPTZ DEFAULT now())"

if psql "$VECTOR_URL" -tAc "SELECT 1 FROM arcnode_seed_markers WHERE slice = 'vector'" | grep -q 1; then
  echo "vector already seeded; exiting"
  exit 0
fi

# Tarball is pg_dump --format=directory output (toc.dat + .dat files).
# Directory format can't be streamed — extract to a tempdir then point
# pg_restore at it.
TMPDIR=$(mktemp -d)
curl -fsSL https://arcnode-public.s3.us-east-1.amazonaws.com/seed/vector.tar.gz \
  | tar -xz -C "$TMPDIR"
pg_restore --format=directory --dbname "$VECTOR_URL" --no-owner --no-privileges "$TMPDIR"
rm -rf "$TMPDIR"

psql "$VECTOR_URL" -c \
  "INSERT INTO arcnode_seed_markers (slice) VALUES ('vector') ON CONFLICT DO NOTHING"

echo "vector seeded"
