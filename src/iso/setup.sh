#!/bin/sh
set -e

# arcnode appliance dev-loop setup — see MANUAL_TESTS.md and README.md for
# scope. Runs once, inside the target chroot, via late_command. Each phase
# echoes progress since this is otherwise a silent, opaque stretch of the
# install from the person watching the screen.
#
# Ordering here reflects a real dependency analysis, not just the order
# things got built in: the wizard runs natively (apt-installed
# python3-fastapi, not Docker) specifically so it can start immediately —
# it has NO dependency on Docker, Postgres, or anything else here, and
# comes right after the one apt-get update everything else also needs.
# Reason it's not a Docker container: the Debian installer's own screen
# shows zero progress for anything late_command does (confirmed — see
# MANUAL_TESTS.md), so the one thing that actually can show the person
# real progress (the wizard) needs to exist before the slow stuff (Docker,
# Postgres) does, not after. The app layer (ems-hmi, standing in for the
# real EMS stack) needs the wizard's output (secrets.env) before it's
# meaningful to expose, enforced via a systemd .path unit watching the
# wizard's apply-marker, not a boot-order guess.

# Reason: the log redirect lives HERE, not in preseed.cfg's late_command
# invocation. `in-target sh /root/setup.sh > logfile` would put the `>`
# outside the in-target call, resolved by the live installer environment's
# OWN shell — writing to its ephemeral RAM filesystem, gone forever at
# reboot, never actually landing in /target. Confirmed the hard way: a
# real setup.sh failure left no log at all on the installed system.
# Self-redirecting from inside the chroot is correct regardless of how
# this script gets invoked.
exec > /var/log/arcnode-late-command.log 2>&1

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

echo "==> [1/9] Preparing apt (cdrom fix + Docker's repo) and updating"
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
# One update covers everything below that isn't in the base install's own
# already-fetched lists (Docker's brand-new repo, and — unverified whether
# actually needed, but harmless either way — python3-fastapi/postgresql).
apt-get update

echo "==> [2/9] Setting up the first-boot setup wizard (native)"
# Native, not Docker: python3-fastapi/uvicorn/pydantic are real Debian
# packages (confirmed via apt-cache against trixie) — installable from the
# same local mirror as everything else, no PyPI/pip dependency at all.
# classy_fastapi (used elsewhere in this repo) has no Debian package, so
# wizard_controller.py uses plain FastAPI APIRouter instead — see its own
# header comment. This has zero dependency on Docker, Postgres, or
# anything below: it can and should start before any of that finishes.
apt-get install -y python3 python3-fastapi python3-uvicorn python3-pydantic
cat > /etc/systemd/system/arcnode-wizard.service <<'EOF'
[Unit]
Description=arcnode first-boot setup wizard (native)

[Service]
WorkingDirectory=/opt/arcnode-wizard-src
Environment=PYTHONPATH=/opt/arcnode-wizard-src
ExecStart=/usr/bin/python3 -m src.wizard.main
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl enable arcnode-wizard.service

echo "==> [3/9] Installing Docker + compose plugin"
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
systemctl enable docker

echo "==> [4/9] Installing PostgreSQL (native daemon)"
# Reason: device-api (the next real consumer, not yet in this walking
# skeleton) hard-fails at boot without DOCUMENT_URL — a real postgres
# connection string, per its own TypeOrmModule.forRootAsync
# ("DOCUMENT_URL is required"). This is just the first piece of that:
# install + enable here, same chroot-safe shape as Docker above —
# postgresql's postinst tries to start the service immediately after
# install, and policy-rc.d denies that the same way it already does for
# Docker (this is the first real test of that same constraint against a
# *native* package's postinst, not a docker build/run — confirmed via
# this exact reinstall, see MANUAL_TESTS.md). Role + database creation
# needs a LIVE server, so that's deferred to
# arcnode-postgres-bootstrap.service on first real boot, same split as
# every other daemon here.
apt-get install -y postgresql
systemctl enable postgresql

cat > /usr/local/sbin/arcnode-postgres-bootstrap.sh <<'EOF'
#!/bin/sh
set -e
# Idempotent: this re-runs every boot ([Install] WantedBy=), must be a
# no-op once the role exists — same guard shape as the
# `docker image inspect ... ||` pattern the docker-based units use.
if runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='device_api'" | grep -q 1; then
  echo "device_api role already exists, skipping"
  exit 0
fi

# hex, not base64 -- this goes straight into a postgres:// URL below, and
# base64's default alphabet (+/=) is not URL-safe in that position.
DOCUMENT_PW=$(openssl rand -hex 24)
runuser -u postgres -- psql -c "CREATE ROLE device_api WITH LOGIN PASSWORD '$DOCUMENT_PW'"
runuser -u postgres -- createdb -O device_api document

echo "DOCUMENT_URL=postgres://device_api:$DOCUMENT_PW@localhost:5432/document" >> /etc/arcnode/secrets.env
EOF
chmod 0755 /usr/local/sbin/arcnode-postgres-bootstrap.sh

cat > /etc/systemd/system/arcnode-postgres-bootstrap.service <<'EOF'
[Unit]
Description=arcnode postgres role+database bootstrap (run once)
After=postgresql.service
Requires=postgresql.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/arcnode-postgres-bootstrap.sh

[Install]
WantedBy=multi-user.target
EOF
systemctl enable arcnode-postgres-bootstrap.service

echo "==> [5/9] Writing MOTD"
# A real validation gate, not a guessed timeout — two iterations in:
# first was a 10x1s poll with a placeholder fallback, wrong on real
# hardware (10s wasn't long enough for DHCP). Second hooked
# /etc/network/if-up.d/, which only fires via ifupdown's `auto`-interface
# sweep — confirmed on real hardware this box's interfaces.d entry uses
# `allow-hotplug` (wireless, wpa-ssid/wpa-psk), which that sweep skips
# entirely, so the hook never ran at all. Per Joe: real units usually
# have Ethernet, but not always — can't assume `auto` vs `allow-hotplug`,
# wired vs wireless, or even ifupdown vs some other mechanism owning the
# interface.
#
# Fixed by watching the kernel's actual routing table directly instead
# of hooking any particular userspace mechanism: `ip monitor route`
# blocks on a real netlink event, firing the instant ANY subsystem adds
# a route — ifupdown, wpa_supplicant, whatever. Doesn't care who brought
# the interface up or how. Verified locally: confirmed the fast path (a
# route already exists) and the blocking path (no route yet, a route
# appears, the script unblocks immediately) both work correctly.
#
# `ip route get`'s src address (the real outbound-route IP), not
# `hostname -I`'s first entry: confirmed on real hardware that
# `hostname -I` lists every interface including docker0 (Docker's
# bridge, 172.17.0.1 by default), and its ordering put docker0 first —
# motd showed the bridge gateway, not the LAN IP a person would actually
# use to reach the box. Every deployment's LAN differs (this targets an
# industrial local network as often as not), so this derives the IP from
# the routing table instead of assuming anything about subnet ranges.
cat > /usr/local/sbin/arcnode-motd-ip.sh <<'EOF'
#!/bin/sh
set -e
get_ip() {
  ip route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p'
}
IP=$(get_ip)
if [ -z "$IP" ]; then
  # stdbuf -oL: `ip monitor` fully buffers its stdout when piped
  # otherwise, so `while read` never sees a line until a buffer's worth
  # accumulates (which may be never, for one single real event).
  stdbuf -oL ip monitor route 2>/dev/null | while read -r _; do
    IP=$(get_ip)
    [ -n "$IP" ] && break
  done
  # The while loop runs in a subshell (it's the right side of a pipe) —
  # IP set in there doesn't propagate out, so recompute once more here.
  IP=$(get_ip)
fi
[ -z "$IP" ] && exit 0
{
  figlet "ArcNode EMS"
  printf '\nSetup: http://%s:8080/setup\n' "$IP"
} > /etc/motd
EOF
chmod 0755 /usr/local/sbin/arcnode-motd-ip.sh

cat > /etc/systemd/system/arcnode-motd-ip.service <<'EOF'
[Unit]
Description=arcnode write the wizard URL into motd once a route exists

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/arcnode-motd-ip.sh

[Install]
WantedBy=multi-user.target
EOF
systemctl enable arcnode-motd-ip.service

echo "==> [6/9] Writing ems-hmi's runtime config overlay"
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

echo "==> [7/9] Setting up placeholder daemon (arcnode-dummy)"
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

echo "==> [8/9] Setting up the docker_runtime layer (compose), gated on the wizard"
# docker-compose.yaml (landed at /opt/arcnode/docker-compose.yaml by
# late_command) is the real mechanism — same `docker compose up -d`
# EC2 UserData already proves in cfn_resources.py, not a one-off `docker
# run` per container anymore. Switched from the old per-container systemd
# unit specifically because ems-hmi's nginx hardcodes compose-style
# service-name hostnames (http://device-api:3000, http://hivemq:8000) —
# those only resolve via Docker's embedded DNS on a shared compose
# network, which one-off `docker run` calls never had. `docker compose
# up -d` is naturally idempotent (confirmed: re-running it is a no-op
# once containers are already up), so no manual `docker inspect ... ||`
# guard needed the way the old per-container units required.
#
# Product-level gate, not a literal data dependency for ems-hmi
# specifically: there's no point exposing the HMI as a visible entrypoint
# before the wizard has even run — logins can't work yet regardless.
# Rehearsing the gating mechanism here now so it's proven before
# device-api needs it for real.
#
# A systemd .path unit, not a boot-order guess or a poll-and-retry hack:
# PathExists= fires immediately if the marker already exists when the
# path unit starts (confirmed current behavior on systemd 257, Debian
# trixie's version — an old related bug was closed "version-too-ancient"
# against systemd 245 from 2020), so this is correct on every reboot
# after the first successful apply, not just the first time the marker
# file appears.
cat > /etc/systemd/system/arcnode-docker-runtime.service <<'EOF'
[Unit]
Description=arcnode docker_runtime layer (docker compose, run once per boot)
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
Restart=on-failure
RestartSec=5
WorkingDirectory=/opt/arcnode
ExecStart=/usr/bin/docker compose -f /opt/arcnode/docker-compose.yaml up -d
EOF
cat > /etc/systemd/system/arcnode-docker-runtime.path <<'EOF'
[Unit]
Description=Wait for wizard apply before starting the docker_runtime layer

[Path]
PathExists=/etc/arcnode/.wizard-applied
Unit=arcnode-docker-runtime.service

[Install]
WantedBy=multi-user.target
EOF
systemctl enable arcnode-docker-runtime.path

echo "==> [9/9] Enabling services"
systemctl daemon-reload

echo "==> arcnode setup complete"
