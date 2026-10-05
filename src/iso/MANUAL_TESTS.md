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
4. Boot the laptop from the drive. The installer's own routine questions
   (locale/partitioning/account) are preseeded — no clicking through those.
   This is attended provisioning from there: once the wizard comes up
   (fast — see below), someone's at it, choosing real passwords under
   their own policy. Not a walk-away/unattended install.
5. Once it's back up, check from another machine on the network.

## Checklist

- [ ] Install completed with **zero manual intervention** (no prompts were
      sat through — if you had to click anything, something's not preseeded
      and that's a bug in `preseed.cfg`, not a one-off)
- [ ] `cat /var/log/arcnode-late-command.log` on the box shows a clean run
      through all of `setup.sh`'s `==> [n/9]` progress lines, no errors —
      this is the authoritative pass/fail signal; check it first before
      re-flashing anything over any other symptom below. **Two things to
      scrutinize first this round:** phase 2 (the wizard, native —
      `apt-get install python3-fastapi` is a new package set, confirm it
      actually resolved rather than needing a repo we don't have), and
      phase 4 (PostgreSQL — first test of `policy-rc.d` against a
      *native* package's postinst, not a `docker build`/`run`)
- [ ] `systemctl is-active arcnode-wizard` reports `active`; `curl -I
      http://<ip>:8080/setup` returns `HTTP/1.1 200 OK` — check this
      **before** waiting for the rest of the log to finish scrolling.
      This is the whole point of running it natively: it should be up and
      answering long before Docker/Postgres are done installing, not
      after
- [ ] Console login banner reads `ArcNode EMS` (figlet) **and** shows a
      `Setup: http://<real-ip>:8080/setup` line underneath with the box's
      actual DHCP IP. No banner at all means `arcnode-motd-ip.service`
      is still blocked waiting on a route (check `systemctl status
      arcnode-motd-ip.service` — it should be `active (exited)`, not
      still `activating`) or `ip route get 1.1.1.1` itself isn't working
      on the box
- [ ] `systemctl is-active arcnode-dummy` on the box reports `active`
- [ ] `hostname -I` on the box, then from this machine: `curl -I http://<ip>`
      returns `HTTP/1.1 200 OK` serving the real ems-hmi SPA shell
- [ ] `docker compose -f /opt/arcnode/docker-compose.yaml ps` on the box
      shows `ems-hmi` running; `systemctl status
      arcnode-docker-runtime.service` shows `active (exited)` (correct
      steady state for a oneshot + `RemainAfterExit=yes` unit, not a
      failure)
- [ ] `systemctl is-active postgresql` reports `active`; `systemctl status
      arcnode-postgres-bootstrap.service` shows `active (exited)`
- [ ] `cat /etc/arcnode/secrets.env` shows a `DOCUMENT_URL=postgres://
      device_api:...@localhost:5432/document` line (hex password, not a
      placeholder)
- [ ] `psql "$(grep DOCUMENT_URL /etc/arcnode/secrets.env | cut -d= -f2-)"
      -c 'select 1'` on the box succeeds — confirms the generated
      credential actually authenticates, not just that the lines exist

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
- An earlier version of this doc claimed the Debian installer's screen
  shows zero progress during `late_command` (cited Debian bug #610525 +
  community reports). **Corrected directly on real hardware: preseed does
  show a progress indicator.** That research was real but wasn't checked
  against this specific install before being written down — direct
  observation on the actual target beats a web-sourced inference, every
  time. Doesn't undo the native-wizard decision (still correct on its own
  merit: no PyPI/pip dependency during provisioning), just don't restate
  "looks hung" as settled fact.
- `hostname -I` lists every interface, including Docker's own `docker0`
  bridge (172.17.0.1 by default) — confirmed on real hardware that its
  ordering put docker0 ahead of the real LAN NIC, so motd showed the
  bridge gateway instead of a usable IP. Fixed via `ip route get
  1.1.1.1`'s src address (the real outbound-route IP; works airgapped
  too, it's a routing-table lookup not a network probe) — don't go back
  to naively taking `hostname -I`'s first entry.
- Motd's IP went through five iterations before landing right (confirmed
  working on real hardware) — don't reintroduce any earlier bug.
  (1) A systemd unit polling `ip route get` up to 10 times (a guessed
  window) before falling back to a literal `<this-box-ip>` placeholder —
  wrong on real hardware, 10s wasn't long enough for DHCP. (2)
  `/etc/network/if-up.d/arcnode-motd`, which only fires via ifupdown's
  `auto`-interface sweep at boot — confirmed on real hardware this box's
  wireless interface is `allow-hotplug` (not `auto`), which that sweep
  skips entirely (and per real Debian source: `networking.service`'s own
  `--allow=hotplug` ExecStart is gated on `/run/network/restart-hotplug`,
  which doesn't exist on a fresh first boot either — allow-hotplug
  interfaces are brought up by a separate udev→`ifup@.service` path
  instead), so the hook silently never ran. Units in the field usually
  have Ethernet but not always, so this can't assume `auto` vs
  `allow-hotplug` either way. (3) `ip monitor route` alone — a real race
  between the initial `get_ip` check and the monitor's netlink
  subscription actually going live let a route-add event slip through
  with nothing left to catch it (confirmed stuck on real hardware,
  `activating` for 2+ minutes). (4) Loop forever re-checking `get_ip`
  directly with `timeout 2` bounding each wait (monitor as accelerant,
  not the only signal) — closed the race, but confirmed on real hardware
  it can latch onto a `169.254.x.x` **link-local** address (RFC 3927,
  Linux's own pre-DHCP self-assigned fallback) and treat that as done.
  (5, current) `get_ip` explicitly rejects `169.254.*` via the same
  "treat as not-ready, keep looping" path, logging which case fired. All
  of (1)-(4)'s fixes stay in place; this only narrows what counts as a
  real address. Full timestamped log at `/var/log/arcnode-motd-ip.log`
  (started, every attempt, link-local rejections, final success) so a
  6th failure is diagnosable from one `cat`, not another round of
  console photos. Verified pre-ship: fast path, the exact
  monitor-subscribe race, never-gives-up with nothing ever appearing, and
  the exact link-local scenario (starts with only a 169.254 route, waits,
  then picks up the real one once it replaces it) — all four, confirmed
  working on real hardware after.
- The post-apply redirect must poll the HMI's real reachability, not
  wait a fixed delay — `ems-hmi`'s container can take up to a minute to
  pull + start on first real boot (confirmed on real hardware), so a
  guessed `setTimeout` either fires at a dead port or wastes time.

## Credentials

`joe` / `j03` — throwaway dev-iteration password, not a real secret. Never
use this account/password scheme for anything customer-facing.
