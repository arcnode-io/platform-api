#!/usr/bin/env bash
set -euo pipefail

# Builds the ArcNode appliance ISO: the stock Debian netinst image plus
# setup.sh, its phases and the wizard source, hooked in via preseed.cfg's
# late_command. The install itself is the standard attended Debian one.

ISO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$ISO_DIR/../.." && pwd)"
SOURCE_ISO="/tmp/debian-13.7.0-amd64-netinst.iso"
# Output dir is the one optional arg — CI passes the repo, so the ISO
# lands outside the build container.
OUTPUT_ISO="${1:-/tmp}/arcnode-ems-amd64.iso"
SOURCE_URL="https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/debian-13.7.0-amd64-netinst.iso"
# Verified against the real download.
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
  -map "$ISO_DIR/phases" /phases \
  -map "$ISO_DIR/grub.cfg" /boot/grub/grub.cfg \
  -map "$ISO_DIR/gtk.cfg" /isolinux/gtk.cfg \
  -map "$ISO_DIR/txt.cfg" /isolinux/txt.cfg \
  -map "$REPO_ROOT/src/wizard" /wizard-src/src/wizard \
  -map "$REPO_ROOT/src/__init__.py" /wizard-src/src/__init__.py

echo "Verifying preseed.cfg + setup.sh + wizard source landed correctly in the built ISO..."
# Reason: extract with xorriso instead of loop-mounting — no root needed, so
# this runs the same on a laptop and in CI's container.
CHECK_DIR="$(mktemp -d)"
xorriso -osirrox on -indev "$OUTPUT_ISO" \
  -extract /preseed.cfg "$CHECK_DIR/preseed.cfg" \
  -extract /setup.sh "$CHECK_DIR/setup.sh" \
  -extract /phases "$CHECK_DIR/phases" \
  -extract /wizard-src/src/wizard/main.py "$CHECK_DIR/main.py"
diff "$CHECK_DIR/preseed.cfg" "$ISO_DIR/preseed.cfg"
diff "$CHECK_DIR/setup.sh" "$ISO_DIR/setup.sh"
diff -r "$CHECK_DIR/phases" "$ISO_DIR/phases"
diff "$CHECK_DIR/main.py" "$REPO_ROOT/src/wizard/main.py"
rm -rf "$CHECK_DIR"

echo "Built: $OUTPUT_ISO"
echo
echo "Flash it (confirm the device with lsblk first):"
echo "  sudo dd if=$OUTPUT_ISO of=/dev/sdX bs=4M status=progress conv=fsync"
