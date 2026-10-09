#!/bin/sh
set -e

# Docker Engine from Docker's own apt repo, at install time — straight
# from docs.docker.com/engine/install/debian (trixie is supported). The
# wizard's Docker page creates the arcnode network and verifies; Docker
# picks that network's address range, never us.
apt-get install -y ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
# shellcheck disable=SC1091 # /etc/os-release exists only on the target
cat > /etc/apt/sources.list.d/docker.sources <<SOURCES
Types: deb
URIs: https://download.docker.com/linux/debian
Suites: $(. /etc/os-release && echo "$VERSION_CODENAME")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
SOURCES
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
# In the chroot nothing starts; enable it so it's up on first boot.
systemctl enable docker
