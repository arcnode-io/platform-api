# ARCNODE Appliance ISO 📦

> Stock Debian netinst with the standard attended install, plus ArcNode's
> own provisioning via the installer's `late_command` hook. A person then
> runs the first-boot wizard. Install once, done.

## Scope right now

`setup.sh` installs SSH, the NVIDIA driver, Docker, PostgreSQL 17
(+ TimescaleDB, pgvector), Neo4j and Ollama, then the first-boot wizard
finishes each one on its own page, in dependency order: hardware check →
SSH key → Docker network → PostgreSQL → Neo4j → Ollama → Site (the order's
site + devices). The EMS containers, one page each, and the SSH password
lock-down come next.

## Per-order ISO

CI publishes the generic base ISO to `s3://arcnode-public/iso/`. For each
on-prem order, platform-api's orchestrator bakes the order into it
(`iso_service.py`): `/order/site.yml` (site id, market, settlement point)
and `/order/dtm.json` (edp-api's device topology), added with the same
`xorriso -boot_image any replay` — seconds per order, no Debian rebuild.
The portal links it (presigned, 7 days). At install, `late_command` copies
`/order` to the box and the wizard's Site page hands it to the EMS
containers.

A box from the base ISO has no order, and the Site page says where to get
one. `sudo test-mode.sh` gives it the test site in `phases/test-order/`
instead: edp-api's real generator output for 1 compute module, plus 1 BESS
module and rack from edp-api's templates.

## Architecture

- **`preseed.cfg`** — only the `late_command` hook; the installer asks
  every routine question itself. The hook copies `setup.sh`, `phases/`,
  the wizard source and (per-order ISO only) `/order` onto the target and
  runs `setup.sh` in the chroot.
- **`setup.sh`** — the provisioning itself, one logged `==> [n/N]` phase at
  a time (each daemon's install lives in `phases/`): apt fix-up, OpenSSH,
  NVIDIA, Docker, PostgreSQL, Neo4j, the wizard (native, apt-installed FastAPI —
  no PyPI), and the motd that shows the wizard's URL.
- **`grub.cfg` / `gtk.cfg` / `txt.cfg`** — stock Debian boot configs plus
  `preseed/file=/cdrom/preseed.cfg`, so BIOS and UEFI both pick it up.
- **`build.sh`** — remasters the stock netinst ISO via `xorriso -boot_image
  any replay` (keeps the hybrid BIOS+UEFI boot catalog).
- **Wizard** — `src/wizard/`, SSH access → review → install. Validates
  the pasted public key with `ssh-keygen` (refuses a pasted private key),
  appends it to `~/.ssh/authorized_keys` of the account created in the
  installer (UID 1000), then the wizard 404s for good. Hardware minimums and
  Ollama models come from `/etc/arcnode/wizard-cfg.yml`, which `setup.sh` writes.

## HTTPS with your own certificate

The HMI always answers on `http://<box ip>/`. For a name your laptops trust, the
wizard's optional **HTTPS certificate** page makes the key and a signing request on
the box; your IT signs it with your internal CA and you paste back the certificate.
Nothing calls ArcNode, then or later.

Your IT can do the same by hand:

```bash
# the signed certificate, followed by any intermediates, and its key
sudo install -m 0644 chain.pem   /opt/arcnode/tls/server.pem
sudo install -m 0600 server.key  /opt/arcnode/tls/server-key.pem
# the utility-facing DER ingress (8443) serves the same certificate
sudo install -m 0644 chain.pem   /opt/arcnode/der-control-tls/cert.pem
sudo install -m 0600 server.key  /opt/arcnode/der-control-tls/key.pem
cd /opt/arcnode
sudo docker compose -f docker-compose.yaml -f docker-compose.onprem.yaml up -d --force-recreate https-ingress der-control-ingress
```

## Build + flash

```sh
src/iso/build.sh                                  # downloads, verifies, remasters
lsblk -o NAME,SIZE,RM,TRAN,MODEL                   # confirm the USB device — don't guess
sudo dd if=/tmp/arcnode-ems-amd64.iso of=/dev/sdX bs=4M status=progress conv=fsync
```

Boot it, answer the standard Debian installer (pick a network mirror),
then open the `Setup:` URL the console login banner shows.
