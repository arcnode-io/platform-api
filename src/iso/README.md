# ARCNODE Appliance ISO 📦

> Stock Debian netinst, remastered with a preseed file so its own routine
> questions (locale/partitioning/account) need zero clicking, then drops
> the EMS stack in via the installer's own `late_command` hook. This is
> attended provisioning, not a walk-away install — a person is at the
> wizard choosing real passwords under their own policy. No control node,
> no self-convergence loop — install once, done.

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

Every row below was proven via a real reinstall (the installer's own
questions preseeded, same as always) — see
`MANUAL_TESTS.md` for the exact checklist and the one confirmed installer
gotcha worth not reintroducing.

| step | capability | proof |
|---|---|---|
| 1 | `late_command` can write a static file | motd echo → login shows it |
| 2 | `late_command` can install + run a real package | `apt-get install nginx` → `curl` reachable post-reboot, zero login steps |
| 3 | `late_command` can set up a persistent daemon | unit file + `systemctl enable` (works offline/in a chroot) → placeholder `arcnode-dummy.service` active every boot |
| 4 | real payload: Docker + the actual ems-hmi image, docker-native restart | `arcnode-hmi` container, `--restart unless-stopped`, survives reboot with zero systemd-vs-docker fighting |
| 5 | `late_command` triggers a real fetched script, not an inline one-liner | `setup.sh` copied from install media, run in the target chroot |
| 6 | the wizard runs **natively**, not in Docker — starts before Docker/Postgres even finish installing | `apt-get install python3-fastapi python3-uvicorn python3-pydantic` (real Debian packages, confirmed via apt-cache — no PyPI/pip dependency); plain FastAPI `APIRouter`, not `classy_fastapi` (no Debian package for it) |
| 7 | first real **daemon-layer** (native, non-docker) service — and the first test of `policy-rc.d` against a *native* package's postinst, not a `docker build`/`run` | PostgreSQL 17 (apt) + `arcnode-postgres-bootstrap.service` creates the `device_api` role/`document` db on first real boot, writes `DOCUMENT_URL` to `secrets.env` |
| 8 | docker_runtime layer migrated from one-off `docker run` per container to a real `docker-compose.yaml` — same `docker compose up -d` mechanism EC2 UserData already proves | `arcnode-docker-runtime.service` (gated on the wizard, same `.path` pattern as before) runs `docker compose up -d` against `/opt/arcnode/docker-compose.yaml` — needed because `ems-hmi`'s nginx hardcodes compose-style service-name hostnames (`device-api:3000`, `hivemq:8000`) that only resolve on a shared compose network |
| … | add HiveMQ + device-api (needs `AUTH_JWT_SECRET` + MQTT creds — machine-generated, not wizard-collected, per `auth_secrets.py`'s own categorization) to that same compose file, then the rest of the daemon layer (timescale+pgvector, neo4j, ollama+models) and docker layer | not yet started — see Roadmap |

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
- **`docker-compose.yaml`** is the docker_runtime layer (`ems-hmi` today,
  more services as they land) — copied by `late_command` to
  `/opt/arcnode/docker-compose.yaml`, brought up by
  `arcnode-docker-runtime.service` via `docker compose up -d` once the
  wizard's applied. Not the commercial/defense compose files verbatim:
  those assume cloud-managed persistence this appliance doesn't have.
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

Boot the laptop from it. The installer's own questions need no clicking;
from the wizard on, this is attended — see `MANUAL_TESTS.md` for the full
checklist.

## Roadmap

Rest of the daemon layer — TimescaleDB + pgvector extensions, Neo4j,
Ollama + models (ported from
`~/engineering-with-ai/tooling-playbooks/dev-services-setup.yml`, same
proven sequence) · rest of the docker layer in `docker-compose.yaml`
(hivemq + device-api + der_control_api + industrial_gateway +
analyst_server/agent/model + mlflow + prometheus + grafana) · per-order
parameterization (a real `dtm.json` baked
in per this repo's own order flow — separate, later work; don't carry this
module's dev-loop defaults into that design without re-deriving them) ·
dynamic motd secrets-nag (only needed once something requires a secret
that *can't* be auto-generated, e.g. a third-party API key) · OS hardening,
revisited only if a real need shows up, not preemptively.
