# ARCNODE Appliance ISO 📦

> Stock Debian netinst, remastered with a preseed file so it installs fully
> unattended and drops the EMS stack in via the installer's own
> `late_command` hook. No control node, no self-convergence loop — install
> once, done.

## History

Folded in from the now-defunct `platform-ems-iso` repo, which tried two
prior approaches before this one:

1. **live-build + GRUB + preseed + d-i** (custom live/installer ISO). Weeks
   of firmware-class debugging taught the lesson: **the install medium was
   our biggest bug surface and it wasn't the product.**
2. **Hetzner `installimage` + Ansible self-converge** (re-converges every
   boot, airgap image/collection bundling, OS hardening). Months of work and
   real Hetzner spend, got nowhere further than the walking skeleton table
   below ever showed.

Both are preserved at git tags `archive/live-build-approach` and
`archive/ansible-hetzner-approach` in `platform-ems-iso` — if that repo gets
deleted, those tags (and this history) go with it unless preserved first.

The appliance is now a **plain, fully-preseeded Debian netinst install**,
proved in small increments on a real local laptop (no cloud dependency, free
iteration) before the next increment lands. "Install once, done" — no
Ansible, no re-converge loop; idempotency only matters for safe retry within
a single install.

## Walking skeleton

Every row below was proven via a real, fully-unattended reinstall — see
`MANUAL_TESTS.md` for the exact checklist and the one confirmed installer
gotcha worth not reintroducing.

| step | capability | proof |
|---|---|---|
| 1 | `late_command` can write a static file | motd echo → login shows it |
| 2 | `late_command` can install + run a real package | `apt-get install nginx` → `curl` reachable post-reboot, zero login steps |
| 3 | `late_command` can set up a persistent daemon | unit file + `systemctl enable` (works offline/in a chroot) → placeholder `arcnode-dummy.service` active every boot |
| … | real provisioning payload (Docker, EMS stack) behind the daemon pattern | not yet started |

## Architecture

- **`preseed.cfg`** answers every routine installer question (locale,
  partitioning — guided, whole-disk, no LVM yet — account) so a real-hardware
  install runs start to finish with zero clicking. This part is dev-loop
  scaffolding only, not product config (see `MANUAL_TESTS.md`).
- **`preseed.cfg`'s `late_command`** is the one piece that's a real
  rehearsal of the product mechanism: auto-provisioning before first boot,
  no manual steps, no login required after.
- **`grub.cfg` / `gtk.cfg` / `txt.cfg`** are the stock Debian boot configs
  with one line inserted (`preseed/file=/cdrom/preseed.cfg`) so both BIOS
  and UEFI boot paths pick up the preseed automatically.
- **`build.sh`** remasters the stock netinst ISO with the above via
  `xorriso -boot_image any replay` (non-destructive — preserves the
  dual BIOS+UEFI hybrid boot catalog).

## Provision (dev loop)

```sh
src/iso/build.sh                                  # downloads, verifies, remasters
lsblk -o NAME,SIZE,RM,TRAN,MODEL                   # confirm the USB device — don't guess
sudo dd if=/tmp/debian-13.7.0-amd64-netinst-arcnode.iso of=/dev/sdX bs=4M status=progress conv=fsync
```

Boot the laptop from it. Fully unattended from power-on to a running,
network-reachable system — see `MANUAL_TESTS.md` for what to check
afterward.

## Roadmap

Real provisioning payload behind the systemd-unit pattern (Docker, EMS
stack) · per-order parameterization (a real `dtm.json` baked in per this
repo's own order flow — separate, later work; don't carry this module's
dev-loop defaults into that design without re-deriving them) · secrets
handling · OS hardening, revisited only if a real need shows up, not
preemptively.
