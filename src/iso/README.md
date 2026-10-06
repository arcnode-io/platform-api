# ARCNODE Appliance ISO 📦

> Stock Debian netinst, remastered with a preseed file, plus ArcNode's own
> provisioning via the installer's `late_command` hook. Attended: a person
> runs the first-boot wizard afterwards. Install once, done.

## Scope right now

**SSH access only.** The installed box runs OpenSSH (installed even if the
Debian installer's "SSH server" task was skipped) and a first-boot wizard
where the customer brings their own key: they paste the public half of
their `.pem` (`ssh-keygen -y -f private-key.pem`), and log in with
`ssh -i private-key.pem <their-account>@<box-ip>`. The private key never leaves
their machine.

Everything else that used to live here (Docker, PostgreSQL, the EMS
containers, the install-progress UI) was removed to restart from a clean
base — it's in git history. It comes back one daemon at a time, in
dependency order.

## History

Folded in from the defunct `platform-ems-iso` repo, which tried
live-build + d-i and then Hetzner `installimage` + Ansible self-converge
before this (tags `archive/live-build-approach` and
`archive/ansible-hetzner-approach` there). Lesson: the install medium was
the biggest bug surface and it wasn't the product — so this is a plain,
preseeded Debian netinst, proven in small increments on real hardware.

## Architecture

- **`preseed.cfg`** — dev-loop answers to the installer's routine questions
  (locale, whole-disk partitioning, account) so a reinstall needs no
  clicking. Dev scaffolding, not product config (see `MANUAL_TESTS.md`).
  Its `late_command` copies `setup.sh` + the wizard source onto the target
  and runs `setup.sh` in the chroot.
- **`setup.sh`** — the provisioning itself, one logged `==> [n/N]` phase at
  a time: apt fix-up, OpenSSH, the wizard (native, apt-installed FastAPI —
  no PyPI), and the motd that shows the wizard's URL.
- **`grub.cfg` / `gtk.cfg` / `txt.cfg`** — stock Debian boot configs plus
  `preseed/file=/cdrom/preseed.cfg`, so BIOS and UEFI both pick it up.
- **`build.sh`** — remasters the stock netinst ISO via `xorriso -boot_image
  any replay` (keeps the hybrid BIOS+UEFI boot catalog).
- **Wizard** — `src/wizard/`, SSH access → review → install. Validates
  the pasted public key with `ssh-keygen` (refuses a pasted private key),
  appends it to `~/.ssh/authorized_keys` of the account created in the
  installer (UID 1000), then the wizard 404s for good. Reads `deployment: cloud | on-prem` from
  `/etc/arcnode/wizard-cfg.yml` (`setup.sh` writes `on-prem`); the SSH
  step is on-prem only — in the cloud EC2 already set SSH up, so the step
  doesn't exist (`POST /api/ssh` 404s).

## Provision (dev loop)

```sh
src/iso/build.sh                                  # downloads, verifies, remasters
lsblk -o NAME,SIZE,RM,TRAN,MODEL                   # confirm the USB device — don't guess
sudo dd if=/tmp/debian-13.7.0-amd64-netinst-arcnode.iso of=/dev/sdX bs=4M status=progress conv=fsync
```

Then follow `MANUAL_TESTS.md`.
