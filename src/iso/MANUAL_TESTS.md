# Manual test checklist — arcnode appliance

**Scope:** dev-loop scaffolding for fast iteration on one dedicated laptop.
Not the per-order product ISO — don't carry these defaults (whole-disk
wipe, `joe`/`j03` account, fixed hostname) into that without re-deriving
them.

Only a full reinstall from the real ISO on the real hardware counts.

## Prereqs

- Dedicated dev laptop, plugged in, powered off
- USB drive to flash (currently `/dev/sda`, 59.5G "SD Transcend" — **always
  confirm with `lsblk` before `dd`**, device names aren't stable)
- Your own `.pem` on the machine you'll log in from (EC2-style is fine)

## Procedure

1. `src/iso/build.sh`
2. `lsblk -o NAME,SIZE,RM,TRAN,MODEL` — confirm the target device
3. `sudo dd if=/tmp/debian-13.7.0-amd64-netinst-arcnode.iso of=/dev/sdX bs=4M status=progress conv=fsync`
4. Boot the laptop from the drive; the installer's routine questions are
   preseeded
5. After the reboot, run the checklist from another machine on the network

## Checklist

- [ ] Install finished with no prompts to click through (a prompt means
      something isn't preseeded — a `preseed.cfg` bug)
- [ ] `cat /var/log/arcnode-late-command.log` shows every `==> [n/4]` phase
      and `arcnode setup complete` — check this first on any failure
- [ ] The tty1 login prompt only appears once the box has an IP (boot shows
      `A start job is running for ArcNode: waiting for a network address…`
      until then); the first login's banner shows `ArcNode EMS` plus
      `Setup: http://<real-ip>:8080`
- [ ] `systemctl is-active ssh` → `active`
- [ ] Open the setup URL: an `ON-PREM` badge top right, one page — SSH access
- [ ] Paste the **`.pem` itself** → **Install & verify** → refused, with the
      `ssh-keygen -y -f private-key.pem` hint
- [ ] Paste the output of `ssh-keygen -y -f private-key.pem` → **Install &
      verify** → four green rows on the same page: SSH daemon running,
      answers SSH on port 22, key login allowed, your key is installed
- [ ] The fingerprint on the last row matches `ssh-keygen -lf private-key.pem`
      on your machine; page shows `ssh -i private-key.pem <account>@<ip>`
- [ ] `ssh -o PasswordAuthentication=no -i private-key.pem <account>@<ip>`
      logs in — proves your key, not the password, let you in
- [ ] `http://<ip>:8080` now returns 404

## Known gotchas — do not reintroduce

- `setup.sh` must strip the dead `deb cdrom:` sources.list entry **before**
  `apt-get update`. Confirmed via `/var/log/installer/syslog` timestamps:
  `finish-install.d/07preseed` (fires `late_command`) always runs before
  `finish-install.d/10apt-cdrom-setup`, so the cdrom entry is still active
  and `apt-get update` fails with exit 100 otherwise.
- The Debian installer **does** show a progress indicator during
  `late_command` (an earlier, web-sourced claim that it doesn't was wrong —
  corrected on real hardware).
- Motd's IP took five iterations; all fixes stay: `ip route get 1.1.1.1`'s
  src address, not `hostname -I` (other interfaces can sort first); a route
  watch, not an `if-up.d` hook (`allow-hotplug` WiFi never runs it on first
  boot); loop forever re-checking with `timeout 2` per wait (closes the
  `ip monitor` subscribe race), never a guessed timeout with a fallback;
  reject `169.254.*` link-local addresses. Full log at
  `/var/log/arcnode-motd-ip.log`.

## Credentials

`joe` / `j03` — throwaway dev-iteration password, not a real secret. Never
use this account/password scheme for anything customer-facing.
