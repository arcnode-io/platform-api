#!/bin/sh
set -e

# NVIDIA driver, at install time — the wizard's hardware check and Ollama
# both need it. The installer's final reboot loads the module.
#
# Reason: NVIDIA's own repo, not Debian's nvidia-driver. Debian's 550 is
# unmaintained with known security issues and can't drive Blackwell;
# wiki.debian.org/NvidiaGraphicsDrivers recommends NVIDIA's repo + the open
# kernel modules for Turing and newer — every datacenter GPU we'd see.
#
# Compute-only (headless): nvidia-driver-cuda (ships nvidia-smi) + the open
# DKMS module. The nvidia-open metapackage would also drag in X11 tools.
#
# Secure Boot: DKMS-built modules won't load until their key is enrolled
# (mokutil). The wizard's hardware check flags that, with the command.
apt-get install -y linux-headers-amd64 dkms curl ca-certificates
KEYRING=/tmp/cuda-keyring.deb
curl -fsSL https://developer.download.nvidia.com/compute/cuda/repos/debian13/x86_64/cuda-keyring_1.1-1_all.deb -o "$KEYRING"
dpkg -i "$KEYRING"
rm "$KEYRING"
apt-get update
apt-get install -y nvidia-driver-cuda nvidia-kernel-open-dkms
# Fail the install here, not at first boot, if the module didn't build.
dkms status nvidia | grep -q installed
