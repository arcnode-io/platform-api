#!/bin/sh
set -e

# test-mode.sh — the one command that lets an under-spec x86 box (no NVIDIA
# GPU, SATA disk, a friend's old PC) through the wizard for testing.
# setup.sh installs it as /usr/local/sbin/test-mode.sh: run `sudo
# test-mode.sh`, then reload the wizard. The hardware check still runs —
# against the lowest minimums the stack actually works on. Nothing in the
# wizard UI shows test mode.
#
# Not a production path: real sites need the hardware setup.sh specs.

if [ "$(id -u)" -ne 0 ]; then
  echo "test-mode.sh changes /etc/arcnode — run it as: sudo test-mode.sh" >&2
  exit 1
fi

# Reason for each floor: 4 vCPUs — Neo4j (Java), PostgreSQL, Ollama on CPU
# and the EMS containers run at once; 16 GiB — Neo4j alone is a fixed 8 GB
# (4g heap + 4g page cache), plus ~6 for the rest + OS; no GPU — Ollama falls
# back to CPU; 100 GB SATA — Debian, images, DBs and tiny models fit.
# Tiny models (~1 GB together) at an 8k context: the production 128k
# context x 2 parallel requests would need ~29 GB of KV cache on CPU.
sed -i \
  -e 's/^  vcpus: .*/  vcpus: 4/' \
  -e 's/^  memory_gib: .*/  memory_gib: 16/' \
  -e 's/^  gpus: .*/  gpus: 0/' \
  -e 's/^  gpu_memory_gb: .*/  gpu_memory_gb: 0/' \
  -e 's/^  disk_gb: .*/  disk_gb: 100/' \
  -e 's/^  disk_nvme: .*/  disk_nvme: false/' \
  -e 's/^  chat_model: .*/  chat_model: qwen3:0.6b/' \
  -e 's/^  embedding_model: .*/  embedding_model: qwen3-embedding:0.6b/' \
  -e 's/^  context_length: .*/  context_length: 8192/' \
  /etc/arcnode/wizard-cfg.yml
# A box from the generic base ISO has no order (a per-order ISO carries
# one) — give it the test site's: 1 compute module + 1 BESS module.
if [ ! -d /etc/arcnode/order ]; then
  cp -r /usr/local/share/arcnode/test-order /etc/arcnode/order
fi
systemctl restart arcnode-wizard

echo "Test mode on: lowered the hardware minimums, tiny Ollama models, the test site if there was no order. Reload the setup page and check hardware again."
