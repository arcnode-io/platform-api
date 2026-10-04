#!/bin/sh
set -e

# arcnode appliance dev-loop setup — see MANUAL_TESTS.md and README.md for
# scope. Runs once, inside the target chroot, via late_command. Each phase
# echoes progress since this is otherwise a silent, opaque stretch of the
# install from the person watching the screen.
#
# Ordering here reflects a real dependency analysis, not just the order
# things got built in: Docker has no dependency on the daemon layer (and
# vice versa — they only contend on the apt lock, so still serialized, but
# not because one needs the other); the wizard needs Docker; the app layer
# (ems-hmi, standing in for the real EMS stack) needs the wizard's output
# (secrets.env) before it's meaningful to expose, enforced via a systemd
# .path unit watching the wizard's apply-marker, not a boot-order guess.
#
# TARGET_USER: reuse whatever account the installer actually created
# (preseed.cfg's passwd/username) instead of inventing dedicated per-daemon
# system users — same "if they have root, dedicated users buy nothing"
# reasoning already applied to secrets. UID 1000 is the first real account
# on any fresh Debian install, so this works without hardcoding the name
# here too and risking it drifting out of sync with preseed.cfg.
TARGET_USER=$(getent passwd 1000 | cut -d: -f1)
echo "==> arcnode setup starting — target user: $TARGET_USER"

mkdir -p /etc/arcnode
touch /etc/arcnode/secrets.env
chmod 0600 /etc/arcnode/secrets.env

echo "==> [1/8] Installing Docker + compose plugin"
apt-get install -y curl figlet
# Reason: finish-install.d/07preseed (which runs this script) always runs
# before finish-install.d/10apt-cdrom-setup (which comments out the
# installer's own dead `deb cdrom:` sources.list entry) — confirmed from
# /var/log/installer/syslog timestamps on a real install. apt-get update
# fails on that dead entry unless stripped first.
sed -i "/^deb cdrom:/s/^/#/" /etc/apt/sources.list
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
# shellcheck disable=SC1091 # /etc/os-release is a runtime-only file on the target, not something to statically follow
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
systemctl enable docker

echo "==> [2/8] Writing MOTD"
figlet "ArcNode EMS" > /etc/motd

echo "==> [3/8] Writing ems-hmi's runtime config overlay"
# Per handoff from the ems-hmi frontend-engineer session (ems-hmi c9c7843):
# the image no longer bakes a site — it reads /opt/arcnode/hmi-cfg.customer.yml
# (nginx serves it at /cfg.customer.yml) and fails closed ("HMI configuration
# error") without it. Exact same shape as cfn_resources.py's cloud UserData
# (siteId/deploymentName/deviceApiUri/chatApiUri/mqttUri) — "arcnode-dev" is
# a dev-loop placeholder, not real per-order site identity (that pipeline
# doesn't exist yet). Written here, not gated on the wizard: this content
# doesn't depend on anything the wizard collects, only arcnode-hmi's own
# startup is gated on the wizard, for the product-level reason below.
mkdir -p /opt/arcnode
cat > /opt/arcnode/hmi-cfg.customer.yml <<'EOF'
siteId: arcnode-dev
deploymentName: arcnode-dev
deviceApiUri: /api
chatApiUri: ""
mqttUri: ""
EOF

echo "==> [4/8] Setting up placeholder daemon (arcnode-dummy)"
cat > /etc/systemd/system/arcnode-dummy.service <<'EOF'
[Unit]
Description=arcnode dummy placeholder daemon

[Service]
ExecStart=/usr/bin/sleep infinity
Restart=always

[Install]
WantedBy=multi-user.target
EOF
systemctl enable arcnode-dummy.service

echo "==> [5/8] Setting up MinIO (native daemon — storage layer, not docker)"
# Ported from ~/engineering-with-ai/tooling-playbooks/templates/minio.service.j2
# (proven, year-maintained reference) — same binary/systemd shape, user
# changed from a dedicated minio system user to TARGET_USER (per above),
# and root credentials auto-generated instead of left at MinIO's
# well-known, network-scannable "minioadmin:minioadmin" default — unlike
# local-root-access secrets, default network-facing credentials are a real,
# remotely-exploitable risk class, not security theater.
curl -fsSL https://dl.min.io/server/minio/release/linux-amd64/minio -o /usr/local/bin/minio
chmod +x /usr/local/bin/minio

mkdir -p /data/minio
chown "$TARGET_USER":"$TARGET_USER" /data/minio
chmod 0750 /data/minio

MINIO_ROOT_PASSWORD=$(openssl rand -base64 24)
{
  echo "MINIO_ROOT_USER=arcnode"
  echo "MINIO_ROOT_PASSWORD=$MINIO_ROOT_PASSWORD"
} >> /etc/arcnode/secrets.env

cat > /etc/default/minio <<EOF
MINIO_ROOT_USER=arcnode
MINIO_ROOT_PASSWORD=$MINIO_ROOT_PASSWORD
MINIO_OPTS="--console-address :9001"
EOF
chmod 0600 /etc/default/minio

cat > /etc/systemd/system/minio.service <<EOF
[Unit]
Description=MinIO
Documentation=https://docs.min.io
Wants=network-online.target
After=network-online.target
AssertFileIsExecutable=/usr/local/bin/minio

[Service]
WorkingDirectory=/usr/local/
User=$TARGET_USER
Group=$TARGET_USER
EnvironmentFile=-/etc/default/minio
ExecStart=/usr/local/bin/minio server \$MINIO_OPTS /data/minio
Restart=always
LimitNOFILE=65536
TimeoutStopSec=infinity
SendSIGKILL=no

[Install]
WantedBy=multi-user.target
EOF

echo "==> [6/8] Setting up the first-boot setup wizard (docker)"
# wizard-src was copied in by late_command (outside the chroot, same as
# this script itself) to /opt/arcnode-wizard-src. Same constraint as
# arcnode-hmi: `docker build` ALSO needs the live daemon, which isn't
# running in this chroot — so build AND run both defer to the bootstrap
# unit's first real boot, not just the run step. /etc/arcnode is
# bind-mounted straight through so whatever the wizard writes (secrets.env,
# TLS cert/key) lands at the same host path main.py already hardcodes —
# one source of truth whether code runs natively or in a container.
cat > /etc/systemd/system/arcnode-wizard-docker.service <<'EOF'
[Unit]
Description=arcnode setup wizard bootstrap (docker, run once)
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
Restart=on-failure
RestartSec=5
ExecStart=/bin/sh -c "docker image inspect arcnode-wizard >/dev/null 2>&1 || docker build -f /opt/arcnode-wizard-src/src/wizard/Dockerfile -t arcnode-wizard /opt/arcnode-wizard-src; docker inspect arcnode-wizard-app >/dev/null 2>&1 || docker run -d --name arcnode-wizard-app --restart unless-stopped -p 8080:8080 -v /etc/arcnode:/etc/arcnode arcnode-wizard"

[Install]
WantedBy=multi-user.target
EOF
systemctl enable arcnode-wizard-docker.service

echo "==> [7/8] Setting up ems-hmi (docker), gated on the wizard"
# Product-level gate, not a literal data dependency for THIS container:
# ems-hmi's nginx just proxies /api/auth/* to device-api (not built yet in
# this walking skeleton) — device-api is what will actually read
# AUTH_OPERATOR_PW/AUTH_VIEWER_PW once it lands, not ems-hmi itself. But
# there's no point exposing the HMI as a visible entrypoint before the
# wizard has even run — logins can't work yet regardless. Rehearsing the
# gating mechanism here now so it's proven before device-api needs it for
# real.
#
# A systemd .path unit, not a boot-order guess or a poll-and-retry hack:
# PathExists= fires immediately if the marker already exists when the
# path unit starts (confirmed current behavior on systemd 257, Debian
# trixie's version — an old related bug was closed "version-too-ancient"
# against systemd 245 from 2020), so this is correct on every reboot
# after the first successful apply, not just the first time the marker
# file appears.
cat > /etc/systemd/system/arcnode-hmi-docker.service <<'EOF'
[Unit]
Description=arcnode hmi bootstrap (docker, run once)
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
Restart=on-failure
RestartSec=5
ExecStart=/bin/sh -c "docker inspect arcnode-hmi >/dev/null 2>&1 || docker run -d --name arcnode-hmi --restart unless-stopped -p 80:80 -v /opt/arcnode/hmi-cfg.customer.yml:/opt/arcnode/hmi-cfg.customer.yml:ro public.ecr.aws/y1d2j6a8/ems-hmi:latest"
EOF
cat > /etc/systemd/system/arcnode-hmi-docker.path <<'EOF'
[Unit]
Description=Wait for wizard apply before starting arcnode-hmi

[Path]
PathExists=/etc/arcnode/.wizard-applied
Unit=arcnode-hmi-docker.service

[Install]
WantedBy=multi-user.target
EOF
systemctl enable arcnode-hmi-docker.path

echo "==> [8/8] Enabling services"
systemctl daemon-reload
systemctl enable minio

echo "==> arcnode setup complete"
