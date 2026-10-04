#!/bin/sh
set -e

# arcnode appliance dev-loop setup — see MANUAL_TESTS.md and README.md for
# scope. Runs once, inside the target chroot, via late_command. Each phase
# echoes progress since this is otherwise a silent, opaque stretch of the
# install from the person watching the screen.
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

echo "==> [1/6] Installing Docker + compose plugin"
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

echo "==> [2/6] Writing MOTD"
figlet "ArcNode EMS" > /etc/motd

echo "==> [3/6] Setting up placeholder daemon (arcnode-dummy)"
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

echo "==> [4/6] Setting up ems-hmi (docker)"
# One-shot bootstrap, not a long-running wrapper: Docker's own
# --restart unless-stopped policy owns the container's lifecycle from here
# on — the daemon resumes it on every future boot with zero systemd
# involvement. docker inspect guard makes every later boot's run of this
# same unit a safe no-op. Restart=on-failure covers only the
# before-network-is-ready case on the very first attempt.
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
ExecStart=/bin/sh -c "docker inspect arcnode-hmi >/dev/null 2>&1 || docker run -d --name arcnode-hmi --restart unless-stopped -p 80:80 public.ecr.aws/y1d2j6a8/ems-hmi:latest"

[Install]
WantedBy=multi-user.target
EOF
systemctl enable arcnode-hmi-docker.service

echo "==> [5/6] Setting up MinIO (native daemon — storage layer, not docker)"
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

echo "==> [6/6] Enabling services"
systemctl daemon-reload
systemctl enable minio

echo "==> arcnode setup complete"
