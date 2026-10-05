# Manual test checklist — arcnode appliance walking skeleton

**Scope:** this whole `src/iso/` module is dev-loop scaffolding for fast
iteration on one dedicated physical laptop. It is NOT the per-order product
ISO build — see `README.md` for why live-build was abandoned and what
"per-order" actually requires later. Don't carry these defaults (whole-disk
wipe, `joe`/`j03` account, fixed hostname) into that future work without
re-deriving them for that actual flow.

Verification discipline: only a full reinstall from the real ISO, on the
real hardware, with zero manual steps, counts. A human typing commands at
the console (even if it "proves the logic works") does not verify the
automated pipeline.

## Prereqs

- Dedicated dev laptop, plugged in, powered off
- A USB drive to flash to (currently `/dev/sda`, 59.5G "SD Transcend" —
  **always confirm with `lsblk` before `dd`**, device names aren't stable)

## Procedure

1. `src/iso/build.sh` — downloads + verifies the source ISO (first run only),
   remasters it, verifies the preseed landed correctly.
2. `lsblk -o NAME,SIZE,RM,TRAN,MODEL` — confirm the target device.
3. `sudo dd if=/tmp/debian-13.7.0-amd64-netinst-arcnode.iso of=/dev/sdX bs=4M status=progress conv=fsync`
4. Boot the laptop from the drive. Walk away — it's fully unattended from
   here (locale/partitioning/account/late_command all preseeded).
5. Once it's back up, check from another machine on the network.

## Checklist

- [ ] Install completed with **zero manual intervention** (no prompts were
      sat through — if you had to click anything, something's not preseeded
      and that's a bug in `preseed.cfg`, not a one-off)
- [ ] `cat /var/log/arcnode-late-command.log` on the box shows a clean run
      through all of `setup.sh`'s `==> [n/7]` progress lines, no errors —
      this is the authoritative pass/fail signal; check it first before
      re-flashing anything over any other symptom below
- [ ] Console login banner reads `ArcNode EMS` (figlet)
- [ ] `systemctl is-active arcnode-dummy` on the box reports `active`
- [ ] `hostname -I` on the box, then from this machine: `curl -I http://<ip>`
      returns `HTTP/1.1 200 OK` serving the real ems-hmi SPA shell
- [ ] `docker ps` on the box shows `arcnode-hmi` running; `systemctl status
      arcnode-hmi-docker.service` shows `active (exited)` (correct steady
      state for a oneshot + `RemainAfterExit=yes` unit, not a failure)

## Known gotchas — do not reintroduce

- `setup.sh` must strip the dead `deb cdrom:` sources.list entry **before**
  its one `apt-get update` call (needed for Docker's brand-new-to-apt repo).
  Confirmed via `/var/log/installer/syslog` timestamps on a real install:
  `finish-install.d/07preseed` (fires `late_command`) always runs before
  `finish-install.d/10apt-cdrom-setup` (which would otherwise comment out
  that entry itself) — so at `late_command` time the cdrom entry is always
  still active, and `apt-get update` deterministically fails with exit 100
  on it otherwise. `curl`/`figlet` install fine with no update at all (base
  install's already-fetched package lists cover them). No public writeup
  covers this specific ordering interaction — confirmed absent via direct
  search.
- Containers that need to survive reboot must use Docker's own `--restart
  unless-stopped` policy, not a systemd unit wrapping a foregrounded
  `docker run` with its own `Restart=`. The latter was tried and confirmed
  broken on real hardware (unit showed enabled, `docker.service` showed
  active, but `docker ps` showed nothing running) — likely because its
  `network-online.target` dependency never resolves on this box's plain
  ifupdown/DHCP networking (no NetworkManager/systemd-networkd). The
  one-shot-bootstrap-then-docker-owns-it pattern in `setup.sh` is the fix.

## Credentials

`joe` / `j03` — throwaway dev-iteration password, not a real secret. Never
use this account/password scheme for anything customer-facing.
