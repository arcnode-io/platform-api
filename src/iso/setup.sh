#!/bin/sh
set -e

# arcnode appliance setup — runs once, inside the target chroot, via
# preseed late_command. Each phase echoes progress since this is otherwise
# a silent stretch of the install. See README.md.
#
# Scope right now: SSH, the NVIDIA driver, Docker, PostgreSQL, Neo4j — installed here, then
# each finished (hardware check, secret, verification) on its own page of
# the first-boot wizard. Docker + the EMS containers come back one at a time.

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
# The order a per-order ISO carries (late_command copied /cdrom/order). The
# generic base ISO has none; the wizard's Site page says where to get one.
if [ -d /root/arcnode-order ]; then
  cp -r /root/arcnode-order /etc/arcnode/order
fi

echo "==> [1/9] Preparing apt (cdrom fix) and updating"
apt-get install -y figlet
# Reason: finish-install.d/07preseed (which runs this script) always runs
# before finish-install.d/10apt-cdrom-setup (which comments out the
# installer's own dead `deb cdrom:` sources.list entry) — confirmed from
# /var/log/installer/syslog timestamps on a real install. apt-get update
# fails on that dead entry unless stripped first.
sed -i "/^deb cdrom:/s/^/#/" /etc/apt/sources.list
apt-get update

echo "==> [2/9] Installing the SSH daemon"
# The Debian installer only installs OpenSSH if "SSH server" is ticked in
# tasksel — an attended install can easily skip it. Install it either way
# (a no-op when it's already there); SSH is how the customer gets in once
# the wizard has installed their key.
apt-get install -y openssh-server
systemctl enable ssh
# The installer's account gets sudo too — every wizard hint uses it.
sh /root/arcnode-phases/sudo.sh

echo "==> [3/9] Installing the NVIDIA driver"
# Before everything that needs a GPU — the wizard's hardware check, Ollama.
sh /root/arcnode-phases/nvidia.sh

echo "==> [4/9] Installing Docker Engine"
# Before PostgreSQL: the wizard's Docker page creates the arcnode network,
# and the PostgreSQL page trusts whatever range Docker gave it.
sh /root/arcnode-phases/docker.sh

echo "==> [5/9] Installing PostgreSQL 17 + TimescaleDB + pgvector"
# Daemons in install-dependency order, one script each in phases/ (copied
# by late_command) so a daemon can be added or removed on its own. The
# wizard's PostgreSQL page sets the password and verifies.
sh /root/arcnode-phases/postgres.sh

echo "==> [6/9] Installing Neo4j"
# After Docker for the same reason as PostgreSQL: the wizard's Neo4j page
# listens on the arcnode gateway. Left off until that page sets the password.
sh /root/arcnode-phases/neo4j.sh

echo "==> [7/9] Installing Ollama"
# After Docker: the wizard's Ollama page listens on the arcnode gateway.
# Left off until that page has downloaded the models.
sh /root/arcnode-phases/ollama.sh

echo "==> [8/9] Setting up the first-boot setup wizard (native)"
# Native, not Docker: python3-fastapi/uvicorn/pydantic are real Debian
# packages (confirmed via apt-cache against trixie) — no PyPI/pip
# dependency at all. classy_fastapi (used elsewhere in this repo) has no
# Debian package, so wizard_controller.py uses plain FastAPI APIRouter.
# Runs as root: it writes the customer's key into their ~/.ssh.
apt-get install -y python3 python3-fastapi python3-uvicorn python3-pydantic python3-yaml
# On-prem: the wizard installs the customer's own SSH key. (Cloud boxes get
# `deployment: cloud` from EC2 UserData — their launch key pair already
# works.) Hardware minimums ≈ g6e.2xlarge (1x L40S 48 GB, 8 vCPU, 64 GiB).
# GPU budget, calibrated against `ollama ps` on a real box, at 128k context,
# 2 parallel, f16 KV, both models resident: gemma4:26b 24.9 GB +
# qwen3-embedding:4b 8.3 GB (at its own 8k context) +15% headroom = 38 GB,
# so 48 GB is the next real card size.
cat > /etc/arcnode/wizard-cfg.yml <<'EOF'
deployment: on-prem
hardware:
  vcpus: 8
  memory_gib: 64
  gpus: 1
  gpu_memory_gb: 48
  disk_gb: 1000
  disk_nvme: true
ollama:
  chat_model: gemma4:26b
  embedding_model: qwen3-embedding:4b
  context_length: 131072
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
# One command for testing on an under-spec box: sudo test-mode.sh
install -m 0755 /root/arcnode-phases/test-mode.sh /usr/local/sbin/test-mode.sh
mkdir -p /usr/local/share/arcnode
cp -r /root/arcnode-phases/test-order /usr/local/share/arcnode/test-order

echo "==> [9/9] Writing MOTD"
sh /root/arcnode-phases/motd.sh

echo "==> arcnode setup complete"
