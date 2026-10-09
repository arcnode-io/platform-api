#!/bin/sh
set -e

# Neo4j Community from Neo4j's own apt repo, at install time — per
# neo4j.com/docs/operations-manual/current/installation/linux/debian. Pulls
# its own Java 21. The wizard's Neo4j page fixes its memory, moves it onto
# the arcnode gateway, changes the default password and starts it.
apt-get install -y ca-certificates curl
install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://debian.neo4j.com/neotechnology.gpg.key \
  -o /etc/apt/keyrings/neotechnology.asc
echo "deb [signed-by=/etc/apt/keyrings/neotechnology.asc] https://debian.neo4j.com stable latest" \
  > /etc/apt/sources.list.d/neo4j.list
apt-get update
# Pinned + held: the wizard's container check runs the same version's
# cypher-shell (NEO4J_VERSION in src/wizard/neo4j_verify.py).
apt-get install -y neo4j=1:2026.09.0
apt-mark hold neo4j

# The package enables it at boot, on localhost with the default password.
# Off until the wizard's page has set the customer's.
systemctl disable neo4j

# Neo4j listens on the arcnode network's gateway, an address that only
# exists once Docker has brought its bridge up — so start after Docker.
install -d /etc/systemd/system/neo4j.service.d
cat > /etc/systemd/system/neo4j.service.d/arcnode-after-docker.conf <<'UNIT'
[Unit]
After=docker.service
Wants=docker.service
UNIT
