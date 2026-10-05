#!/usr/bin/env bash
set -euo pipefail

# Builds the arcnode dev-loop appliance ISO: a stock Debian netinst image
# remastered with this directory's preseed.cfg + patched boot configs, so a
# reinstall on the dedicated dev laptop runs fully unattended. See
# MANUAL_TESTS.md for what to flash it to and what to check afterward.
#
# Reason: this is dev-loop scaffolding, not the per-order product ISO build.
# See MANUAL_TESTS.md's header before extending this to per-order dtm.json
# baking without re-deriving requirements for that actual flow.

ISO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$ISO_DIR/../.." && pwd)"
SOURCE_ISO="/tmp/debian-13.7.0-amd64-netinst.iso"
OUTPUT_ISO="/tmp/debian-13.7.0-amd64-netinst-arcnode.iso"
SOURCE_URL="https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/debian-13.7.0-amd64-netinst.iso"
# Verified against the real download — see MANUAL_TESTS.md.
EXPECTED_SHA256="a7ef94ac2fb9a7fec454552abd629b7cc9d5155c886165a45649f5ce6167e355"

if [[ ! -f "$SOURCE_ISO" ]]; then
  echo "Downloading source ISO..."
  curl -fL -o "$SOURCE_ISO" "$SOURCE_URL"
fi

echo "Verifying source ISO checksum..."
echo "${EXPECTED_SHA256}  ${SOURCE_ISO}" | sha256sum -c -

rm -f "$OUTPUT_ISO"

xorriso -indev "$SOURCE_ISO" \
  -outdev "$OUTPUT_ISO" \
  -boot_image any replay \
  -map "$ISO_DIR/preseed.cfg" /preseed.cfg \
  -map "$ISO_DIR/setup.sh" /setup.sh \
  -map "$ISO_DIR/docker-compose.yaml" /docker-compose.yaml \
  -map "$ISO_DIR/grub.cfg" /boot/grub/grub.cfg \
  -map "$ISO_DIR/gtk.cfg" /isolinux/gtk.cfg \
  -map "$ISO_DIR/txt.cfg" /isolinux/txt.cfg \
  -map "$REPO_ROOT/src/wizard" /wizard-src/src/wizard \
  -map "$REPO_ROOT/src/__init__.py" /wizard-src/src/__init__.py

echo "Verifying preseed.cfg + setup.sh + wizard source landed correctly in the built ISO..."
MOUNT_DIR="$(mktemp -d)"
sudo mount -o loop,ro "$OUTPUT_ISO" "$MOUNT_DIR"
diff "$MOUNT_DIR/preseed.cfg" "$ISO_DIR/preseed.cfg"
diff "$MOUNT_DIR/setup.sh" "$ISO_DIR/setup.sh"
diff "$MOUNT_DIR/docker-compose.yaml" "$ISO_DIR/docker-compose.yaml"
diff "$MOUNT_DIR/wizard-src/src/wizard/main.py" "$REPO_ROOT/src/wizard/main.py"
diff "$MOUNT_DIR/wizard-src/src/wizard/Dockerfile" "$REPO_ROOT/src/wizard/Dockerfile"
sudo umount "$MOUNT_DIR"
rmdir "$MOUNT_DIR"

echo "Built: $OUTPUT_ISO"
echo
echo "Flash it (confirm the device with lsblk first — see MANUAL_TESTS.md):"
echo "  sudo dd if=$OUTPUT_ISO of=/dev/sdX bs=4M status=progress conv=fsync"
