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
- [ ] `hostname -I` on the box, then from this machine: `curl -I http://<ip>`
      returns `HTTP/1.1 200 OK` with `Server: nginx`
- [ ] Console login banner reads `ArcNode EMS` (figlet)
- [ ] `systemctl is-active arcnode-dummy` on the box reports `active`
- [ ] `cat /var/log/arcnode-late-command.log` on the box shows a clean run,
      no errors — this is the authoritative pass/fail signal if anything
      above fails; check it first before re-flashing anything

## Known gotcha — do not reintroduce

`late_command` must NOT run `apt-get update`. Confirmed via
`/var/log/installer/syslog` timestamps on a real install:
`finish-install.d/07preseed` (fires `late_command`) always runs before
`finish-install.d/10apt-cdrom-setup` (comments out the installer's own
`deb cdrom:` sources.list entry). So at the moment `late_command` runs, the
cdrom entry is still active, and `apt-get update` deterministically fails
with exit 100 on it — not flaky, structural. `apt-get install` works fine
off the base install's already-fetched package lists; it doesn't need its
own `update` first. No public writeup covers this specific ordering
interaction — confirmed absent via direct search.

## Credentials

`joe` / `j03` — throwaway dev-iteration password, not a real secret. Never
use this account/password scheme for anything customer-facing.
