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
| 4 | real payload: Docker + the actual ems-hmi image, docker-native restart | `arcnode-hmi` container, `--restart unless-stopped`, survives reboot with zero systemd-vs-docker fighting |
| 5 | `late_command` triggers a real fetched script, not an inline one-liner | `setup.sh` copied from install media, run in the target chroot |
| … | first real **daemon-layer** (native, non-docker) service, then the rest (postgres+timescale+pgvector, neo4j, ollama+models), then the full docker layer (hivemq + remaining app services) | not yet started — see Roadmap |

MinIO was tried here first and cut: upstream retired the community edition's
binary/Docker distribution entirely (dl.min.io now 410s, Docker Hub images
delisted, repo archived) while this walking skeleton had zero actual
consumers of it — nothing in this codebase talks to S3/MinIO today, mlflow
included (it runs sqlite + local filesystem artifacts, see
`src/compose/*/docker-compose.yaml`). Picking a real object-storage backend
is deferred until something actually needs one.

Per the real deployment diagram (`~/arcnode/ems/readme.md`'s On-Prem
diagram), **daemons** (the DBs, Ollama) and **docker_runtime** (the
app services) are two distinct layers — mirrors
`~/engineering-with-ai/tooling-playbooks/main.yml` +
`dev-services-setup.yml` almost exactly (same native-install-then-docker-
compose split, same services). Building depth-first by layer (all daemons,
then all docker services), not a thin vertical slice through both at once.

## Architecture

- **`preseed.cfg`** answers every routine installer question (locale,
  partitioning — guided, whole-disk, no LVM yet — account) so a real-hardware
  install runs start to finish with zero clicking. This part is dev-loop
  scaffolding only, not product config (see `MANUAL_TESTS.md`).
- **`preseed.cfg`'s `late_command`** copies `setup.sh` from the install
  media into the target and runs it there — the real rehearsal of the
  product mechanism (auto-provisioning before first boot, no manual steps,
  no login required after). `late_command` itself stopped being able to
  hold the actual provisioning logic once it needed three levels of nested
  shell quoting for one container; `setup.sh` is the growing, readable home
  for everything it sets up, one `==> [n/N]`-logged phase at a time.
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

Rest of the daemon layer — postgres + TimescaleDB + pgvector extensions,
Neo4j, Ollama + models (ported from
`~/engineering-with-ai/tooling-playbooks/dev-services-setup.yml`, same
proven sequence) · then the docker layer (hivemq + der_control_api +
industrial_gateway + analyst_server/agent/model + mlflow + prometheus +
grafana, via a real `docker compose` file, not more one-off bootstrap
units per container) · per-order parameterization (a real `dtm.json` baked
in per this repo's own order flow — separate, later work; don't carry this
module's dev-loop defaults into that design without re-deriving them) ·
dynamic motd secrets-nag (only needed once something requires a secret
that *can't* be auto-generated, e.g. a third-party API key) · OS hardening,
revisited only if a real need shows up, not preemptively.
