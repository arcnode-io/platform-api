#!/bin/sh
set -e

# Ollama from its pinned release archive, at install time — the manual
# install from docs.ollama.com/linux (not the curl | sh script: pinned and
# checksum-verified instead). The wizard's Ollama page moves it onto the
# arcnode gateway, downloads the models and starts it.
OLLAMA_VERSION="v0.34.4"
OLLAMA_SHA256="c238986e61d40c0cc5f4a9b9e40b9eea104350b77efa34741fc134e105cb9533"
apt-get install -y ca-certificates curl zstd
curl -fsSL -o /tmp/ollama.tar.zst \
  "https://github.com/ollama/ollama/releases/download/${OLLAMA_VERSION}/ollama-linux-amd64.tar.zst"
echo "${OLLAMA_SHA256}  /tmp/ollama.tar.zst" | sha256sum -c -
tar --zstd -xf /tmp/ollama.tar.zst -C /usr
rm /tmp/ollama.tar.zst

# Its own system account, in video + render so it can open the GPU devices
# — each only if it exists, same as Ollama's own install.sh.
useradd -r -s /bin/false -U -m -d /var/lib/ollama ollama
for group in video render; do
  if getent group "$group" >/dev/null; then usermod -a -G "$group" ollama; fi
done
# Explicit owner: useradd -m leaves an already-existing home root's.
install -d -o ollama -g ollama /var/lib/ollama /var/lib/ollama/models

# Off until the wizard's page has put it on the gateway. After Docker for
# the same reason as PostgreSQL + Neo4j: that address only exists once
# Docker's bridge is up.
cat > /etc/systemd/system/ollama.service <<'UNIT'
[Unit]
Description=Ollama
After=docker.service
Wants=docker.service

[Service]
ExecStart=/usr/bin/ollama serve
User=ollama
Group=ollama
Environment="OLLAMA_MODELS=/var/lib/ollama/models"
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
