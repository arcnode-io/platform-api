#!/bin/sh
set -e

# PostgreSQL 17 + TimescaleDB + pgvector, at install time — ported from
# tooling-playbooks' dev-services-setup.yml. The wizard's PostgreSQL page
# opens it to the range Docker picked, sets the customer's password,
# creates the databases + extensions and verifies. Safe to re-run.
#
# Not ported from the playbook, on purpose:
# - the pg_ctlcluster Perl-taint patch: Trixie's -wT still starts fine
#   (systemd's PATH is clean) — confirmed on a debian:trixie container
# - collation refresh: only matters after glibc upgrades, not a fresh box
# - building pgvector from git: Debian ships postgresql-17-pgvector
# - pg_hba 0.0.0.0/0: only the arcnode network's range gets in, written by
#   the wizard once Docker has picked it

apt-get install -y postgresql postgresql-17-pgvector curl ca-certificates

install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://packagecloud.io/timescale/timescaledb/gpgkey \
  -o /etc/apt/keyrings/timescaledb.asc
# shellcheck disable=SC1091 # /etc/os-release exists only on the target
echo "deb [signed-by=/etc/apt/keyrings/timescaledb.asc] https://packagecloud.io/timescale/timescaledb/debian/ $(. /etc/os-release && echo "$VERSION_CODENAME") main" \
  > /etc/apt/sources.list.d/timescaledb.list
apt-get update
apt-get install -y timescaledb-2-postgresql-17
# Sizes memory/worker settings for this machine and adds timescaledb to
# shared_preload_libraries.
timescaledb-tune --yes --quiet

# The wizard owns its access rule in its own file (PostgreSQL 16+ reads
# pg_hba include_dir); Debian's pg_hba.conf stays as shipped plus this line.
PG=/etc/postgresql/17/main
install -d -o postgres -g postgres -m 0700 "$PG/pg_hba.d"
grep -qxF "include_dir pg_hba.d" "$PG/pg_hba.conf" \
  || echo "include_dir pg_hba.d" >> "$PG/pg_hba.conf"

# Postgres listens on the arcnode network's gateway, an address that only
# exists once Docker has brought its bridge up — so start after Docker.
install -d /etc/systemd/system/postgresql@17-main.service.d
cat > /etc/systemd/system/postgresql@17-main.service.d/arcnode-after-docker.conf <<'UNIT'
[Unit]
After=docker.service
Wants=docker.service
UNIT
