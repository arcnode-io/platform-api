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
# Postgres) does, not after.
#
# Docker and PostgreSQL themselves are NOT installed here anymore — only
# Docker's apt repo gets configured here (cheap, no live daemon needed).
# The actual `apt-get install` for both, plus Postgres's role/db
# bootstrap, is deferred to arcnode-daemon-layer.service, gated on the
# wizard's apply-marker the same way the docker_runtime layer already
# was — so installing them can eventually show real, live progress
# through the wizard's own UI instead of happening silently before
# anyone's looking. The app layer (ems-hmi, standing in for the real EMS
# stack) needs BOTH the wizard's output (secrets.env) AND the daemon
# layer actually installed before it's meaningful to expose — enforced
# via systemd's own unit dependencies (Requires=/After=, Wants=/Before=),
# not a boot-order guess or a poll-and-retry hack. Proven first on a
# local Vagrant/QEMU VM (src/iso/vagrant/), not guessed: an earlier
# version gated docker_runtime on the daemon layer via Requires=/After=
# alone and it silently never started, because the one-shot .path trigger
# had already fired (and aborted) once before the daemon layer finished —
# Requires=/After= only stops something from starting early, it doesn't
# retroactively start it once a dependency becomes ready later. The fix:
# the daemon layer unit itself declares Wants=/Before= on docker_runtime,
# so completing successfully actively pulls it in next, every time,
# regardless of what triggered the daemon layer in the first place.

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

echo "==> [1/8] Preparing apt (cdrom fix + Docker's repo) and updating"
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

echo "==> [2/8] Setting up the first-boot setup wizard (native)"
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

echo "==> [3/8] Setting up the daemon layer (Docker + PostgreSQL), gated on the wizard"
# Docker's repo was already configured in phase 1 (chroot-safe, no live
# daemon needed); the actual package installs — and Postgres's role/db
# bootstrap — happen here instead, deferred to first real boot, gated on
# the same wizard apply-marker as the docker_runtime layer. Re-runs
# `apt-get update` itself (cheap, idempotent) rather than trusting
# phase 1's cache is still fresh by the time a person actually finishes
# the wizard, which could be minutes or longer after boot.
#
# device-api (the next real consumer, not yet in this walking skeleton)
# hard-fails at boot without DOCUMENT_URL — a real postgres connection
# string, per its own TypeOrmModule.forRootAsync ("DOCUMENT_URL is
# required"). Role + database creation needs a LIVE server, so that's
# bootstrapped here too, in the same script, after postgresql actually
# starts — no separate deferred unit needed now that this whole phase
# already runs at a point where live daemons are expected to work.
cat > /usr/local/sbin/arcnode-daemon-layer.sh <<'EOF'
#!/bin/sh
set -e
exec >> /var/log/arcnode-daemon-layer.log 2>&1
echo "$(date -Is) arcnode-daemon-layer starting"

apt-get update

echo "$(date -Is) installing Docker..."
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
systemctl enable --now docker
echo "$(date -Is) Docker installed and active: $(systemctl is-active docker)"

# Verify, playbook-style: "active" only means systemd started it — the
# daemon actually answering API calls is what docker_runtime needs.
if DOCKER_VERSION=$(docker info --format '{{.ServerVersion}}') && [ -n "$DOCKER_VERSION" ]; then
  echo "$(date -Is) verify docker: ok (server $DOCKER_VERSION)"
else
  echo "$(date -Is) verify docker: FAILED (docker info got no server answer)"
  exit 1
fi

echo "$(date -Is) installing PostgreSQL..."
apt-get install -y postgresql
systemctl enable --now postgresql
echo "$(date -Is) PostgreSQL installed and active: $(systemctl is-active postgresql)"

echo "$(date -Is) bootstrapping postgres role/db..."
# Idempotent: re-running this must be a no-op once the role exists —
# same guard shape as the `docker image inspect ... ||` pattern the
# docker-based units use.
if runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='device_api'" | grep -q 1; then
  echo "$(date -Is) device_api role already exists, skipping"
else
  # hex, not base64 -- this goes straight into a postgres:// URL below,
  # and base64's default alphabet (+/=) is not URL-safe in that position.
  DOCUMENT_PW=$(openssl rand -hex 24)
  runuser -u postgres -- psql -c "CREATE ROLE device_api WITH LOGIN PASSWORD '$DOCUMENT_PW'"
  runuser -u postgres -- createdb -O device_api document
  echo "DOCUMENT_URL=postgres://device_api:$DOCUMENT_PW@localhost:5432/document" >> /etc/arcnode/secrets.env
  echo "$(date -Is) device_api role/db created, DOCUMENT_URL written"
fi

# Verify with the exact credential consumers will use — the idempotent
# branch above trusts secrets.env and the real role still agree, this
# proves it instead of handing off a stack that can't connect.
DOCUMENT_URL=$(sed -n 's/^DOCUMENT_URL=//p' /etc/arcnode/secrets.env)
if [ "$(psql "$DOCUMENT_URL" -tAc 'select current_user' 2>&1)" = "device_api" ]; then
  echo "$(date -Is) verify postgres: ok (DOCUMENT_URL authenticates as device_api)"
else
  echo "$(date -Is) verify postgres: FAILED (DOCUMENT_URL in /etc/arcnode/secrets.env does not authenticate)"
  exit 1
fi

echo "$(date -Is) arcnode-daemon-layer complete"
EOF
chmod 0755 /usr/local/sbin/arcnode-daemon-layer.sh

# Wants=/Before= on docker_runtime (not just the reverse Requires=/After=
# docker_runtime already declares on this unit): confirmed on a local
# Vagrant/QEMU VM that without this, docker_runtime's own .path trigger
# can fire and abort (dependency not ready yet) before this unit ever
# finishes, and nothing re-triggers it afterward — Requires=/After= alone
# only blocks an early start, it doesn't retroactively start something
# once its dependency becomes ready later. This unit actively pulling
# docker_runtime in on its own successful completion is what actually
# makes the chain work, regardless of what triggered this unit itself.
cat > /etc/systemd/system/arcnode-daemon-layer.service <<'EOF'
[Unit]
Description=arcnode daemon layer (Docker + Postgres), installed at wizard-apply time
Wants=arcnode-docker-runtime.service
Before=arcnode-docker-runtime.service
ConditionPathExists=/etc/arcnode/.wizard-applied

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/arcnode-daemon-layer.sh

[Install]
WantedBy=multi-user.target
EOF
systemctl enable arcnode-daemon-layer.service

cat > /etc/systemd/system/arcnode-daemon-layer.path <<'EOF'
[Unit]
Description=Wait for wizard apply before installing the daemon layer

[Path]
# PathChanged= (edge), not PathExists= (level): PathExists re-fires every
# time the unit goes inactive while the marker still exists, so a real
# failure (e.g. verify postgres) looped forever instead of staying
# "failed" — confirmed on the Vagrant VM. Once-per-boot runs come from
# the service's own WantedBy= + ConditionPathExists=, not this watcher.
PathChanged=/etc/arcnode/.wizard-applied
Unit=arcnode-daemon-layer.service

[Install]
WantedBy=multi-user.target
EOF
systemctl enable arcnode-daemon-layer.path

echo "==> [4/8] Writing MOTD"
# Static figlet banner — proven since the very first walking-skeleton
# step, zero risk.
figlet "ArcNode EMS" > /etc/motd

# Attempting the dynamic Setup-URL line again — same race-fixed logic
# that already passed all three tests last time (fast path, the exact
# monitor-subscribe race reproduced, and the never-gives-up property),
# now with full timestamped logging to its own file so a failure is
# diagnosable from one `cat`, not another round of console photos.
#
# Root cause research this time, not a guess: read Debian trixie's real
# networking.service unit (confirmed via a real debian:trixie container,
# not assumed) — its `--allow=hotplug` ExecStart line is gated on
# /run/network/restart-hotplug existing, which only happens after a
# PRIOR stop of networking.service, never on a fresh first boot. So
# allow-hotplug interfaces are structurally never brought up by
# networking.service on first boot at all; what actually brings them up
# is a separate udev rule (80-ifupdown.rules) starting a templated
# ifup@<iface>.service unit, asynchronously, outside networking.service
# entirely. This is exactly why hooking any specific ifupdown/udev code
# path is fragile — which one does the work depends on interface type —
# and why watching the kernel's own routing table directly (not any
# particular mechanism's hook point) is the structurally correct
# approach regardless of wired/wireless/auto/allow-hotplug.
cat > /usr/local/sbin/arcnode-motd-ip.sh <<'EOF'
#!/bin/sh
set -e
exec >> /var/log/arcnode-motd-ip.log 2>&1
echo "$(date -Is) arcnode-motd-ip starting"

get_ip() {
  # Confirmed on real hardware: attempt 7 found a 169.254.x.x address and
  # happily wrote it to motd — a link-local self-assigned address (RFC
  # 3927), which Linux can briefly hold before the real DHCP lease lands.
  # A route existing isn't enough; it has to be a REAL route. Rejected
  # explicitly rather than silently treated as "not ready yet" so the
  # log shows which case fired, not just another empty result.
  RAW=$(ip route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p')
  case "$RAW" in
    169.254.*)
      echo "$(date -Is) ignoring link-local address: $RAW" >&2
      ;;
    *)
      echo "$RAW"
      ;;
  esac
}

IP=$(get_ip)
echo "$(date -Is) initial get_ip: '${IP:-<empty>}'"

if [ -z "$IP" ]; then
  # WiFi can take noticeably longer than wired (association + DHCP vs.
  # just DHCP) — without this, the console shows the same static figlet
  # banner the whole time, indistinguishable from actually being stuck.
  {
    figlet "ArcNode EMS"
    printf '\nSetup: waiting for network... (see /var/log/arcnode-motd-ip.log)\n'
  } > /etc/motd
fi

ATTEMPT=0
while [ -z "$IP" ]; do
  ATTEMPT=$((ATTEMPT + 1))
  echo "$(date -Is) attempt $ATTEMPT: waiting up to 2s on ip monitor route..."
  # stdbuf -oL: `ip monitor` fully buffers its stdout when piped
  # otherwise, so the read below would never see a line until a buffer's
  # worth accumulates (which may be never, for one single real event).
  # timeout 2: the monitor is a wake-up accelerant, not the only signal —
  # bounds each wait so a route added in the race between our last check
  # and the monitor's subscription actually going live is still caught
  # on the next iteration, not missed forever. Never gives up, no
  # fallback output — just keeps re-checking the real condition.
  timeout 2 stdbuf -oL ip monitor route 2>/dev/null | { read -r _ || true; }
  IP=$(get_ip)
  echo "$(date -Is) attempt $ATTEMPT: get_ip now: '${IP:-<empty>}'"
done

echo "$(date -Is) got IP: $IP -- writing motd"
{
  figlet "ArcNode EMS"
  printf '\nSetup: http://%s:8080/setup\n' "$IP"
} > /etc/motd
echo "$(date -Is) motd written successfully"
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

echo "==> [5/8] Writing ems-hmi's runtime config overlay"
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

echo "==> [6/8] Setting up placeholder daemon (arcnode-dummy)"
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

echo "==> [7/8] Setting up the docker_runtime layer (compose), gated on the wizard"
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
# Two triggers, same split as the daemon layer: the .path unit
# (PathChanged=) catches the wizard's apply live; WantedBy= +
# ConditionPathExists= runs it once per boot after that. No level-trigger
# watcher, so a real failure stays "failed" instead of re-firing.
cat > /etc/systemd/system/arcnode-docker-runtime.service <<'EOF'
[Unit]
Description=arcnode docker_runtime layer (docker compose, run once per boot)
# arcnode-daemon-layer.service here too (not just docker.service): this
# only stops a too-early start. The thing that actually makes the chain
# work is the Wants=/Before= THAT unit declares on this one — see its own
# comment for why the reverse alone isn't enough.
After=docker.service arcnode-daemon-layer.service
Requires=docker.service arcnode-daemon-layer.service
ConditionPathExists=/etc/arcnode/.wizard-applied

[Service]
Type=oneshot
RemainAfterExit=yes
Restart=on-failure
RestartSec=5
WorkingDirectory=/opt/arcnode
ExecStart=/usr/bin/docker compose -f /opt/arcnode/docker-compose.yaml up -d

[Install]
WantedBy=multi-user.target
EOF
systemctl enable arcnode-docker-runtime.service
cat > /etc/systemd/system/arcnode-docker-runtime.path <<'EOF'
[Unit]
Description=Wait for wizard apply before starting the docker_runtime layer

[Path]
# PathChanged=, not PathExists= — see arcnode-daemon-layer.path.
PathChanged=/etc/arcnode/.wizard-applied
Unit=arcnode-docker-runtime.service

[Install]
WantedBy=multi-user.target
EOF
systemctl enable arcnode-docker-runtime.path

echo "==> [8/8] Enabling services"
systemctl daemon-reload

echo "==> arcnode setup complete"
