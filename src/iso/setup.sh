#!/bin/sh
set -e

# arcnode appliance setup — runs once, inside the target chroot, via
# preseed late_command. Each phase echoes progress since this is otherwise
# a silent stretch of the install. See MANUAL_TESTS.md and README.md.
#
# Scope right now: SSH access only. The customer pastes their SSH public
# key into the first-boot wizard and can then log in. Everything else
# (Docker, PostgreSQL, the EMS containers) was removed to restart from a
# clean base — git history has it.

# Reason: the log redirect lives HERE, not in preseed.cfg's late_command
# invocation. `in-target sh /root/setup.sh > logfile` would put the `>`
# outside the in-target call, resolved by the live installer environment's
# OWN shell — writing to its ephemeral RAM filesystem, gone forever at
# reboot, never actually landing in /target. Confirmed the hard way: a
# real setup.sh failure left no log at all on the installed system.
# Self-redirecting from inside the chroot is correct regardless of how
# this script gets invoked.
exec > /var/log/arcnode-late-command.log 2>&1

echo "==> arcnode setup starting"
mkdir -p /etc/arcnode

echo "==> [1/4] Preparing apt (cdrom fix) and updating"
apt-get install -y figlet
# Reason: finish-install.d/07preseed (which runs this script) always runs
# before finish-install.d/10apt-cdrom-setup (which comments out the
# installer's own dead `deb cdrom:` sources.list entry) — confirmed from
# /var/log/installer/syslog timestamps on a real install. apt-get update
# fails on that dead entry unless stripped first.
sed -i "/^deb cdrom:/s/^/#/" /etc/apt/sources.list
apt-get update

echo "==> [2/4] Installing the SSH daemon"
# The Debian installer only installs OpenSSH if "SSH server" is ticked in
# tasksel — an attended install can easily skip it. Install it either way
# (a no-op when it's already there); SSH is how the customer gets in once
# the wizard has installed their key.
apt-get install -y openssh-server
systemctl enable ssh

echo "==> [3/4] Setting up the first-boot setup wizard (native)"
# Native, not Docker: python3-fastapi/uvicorn/pydantic are real Debian
# packages (confirmed via apt-cache against trixie) — no PyPI/pip
# dependency at all. classy_fastapi (used elsewhere in this repo) has no
# Debian package, so wizard_controller.py uses plain FastAPI APIRouter.
# Runs as root: it writes the customer's key into their ~/.ssh.
apt-get install -y python3 python3-fastapi python3-uvicorn python3-pydantic python3-yaml
# This box is on-prem, so the wizard creates the SSH key pair. (Cloud boxes
# get `deployment: cloud` from EC2 UserData — their launch key pair already
# works, and the wizard must leave it alone.)
cat > /etc/arcnode/wizard-cfg.yml <<'EOF'
deployment: on-prem
EOF
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

echo "==> [4/4] Writing MOTD"
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
  printf '\nSetup: http://%s:8080\n' "$IP"
} > /etc/motd
echo "$(date -Is) motd written successfully"
EOF
chmod 0755 /usr/local/sbin/arcnode-motd-ip.sh

# Description doubles as the boot screen's "A start job is running for …"
# line while the login prompt below is held back.
cat > /etc/systemd/system/arcnode-motd-ip.service <<'EOF'
[Unit]
Description=ArcNode: waiting for a network address (login opens once connected)

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/arcnode-motd-ip.sh

[Install]
WantedBy=multi-user.target
EOF
systemctl enable arcnode-motd-ip.service

# Hold tty1's login prompt until the IP is known, so the first login always
# shows the real setup URL — not a placeholder that only updates on the
# next login. A oneshot has no start timeout, so this waits on the real
# condition, not a guessed window. Only tty1: Alt+F2 still gives a login
# (showing the "waiting for network" motd) if the network never comes up.
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/arcnode-wait-for-ip.conf <<'EOF'
[Unit]
After=arcnode-motd-ip.service
Wants=arcnode-motd-ip.service
EOF

echo "==> arcnode setup complete"
