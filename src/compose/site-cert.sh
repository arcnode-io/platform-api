#!/bin/bash
# A real DNS name and Let's Encrypt certificate for this box.
#
#   site-cert.sh issue   once at boot (systemd retries it on failure): tell platform-api this
#                        box's address, wait for the DNS name to resolve to it, get a certificate
#   site-cert.sh renew   weekly: renew if due, install if it changed
#
# Until `issue` succeeds the box keeps the self-signed certificate it booted with. The wizard
# (port 8080) and the HTTPS ingress both read /opt/arcnode/tls/server{,-key}.pem.
# Settings come from /etc/arcnode/site-cert.env (UserData writes it):
#   SITE_HOST, SITE_ADDRESS, SITE_CALLBACK_URL, SITE_TOKEN
set -euo pipefail

# shellcheck source=/dev/null
source /etc/arcnode/site-cert.env

TLS_DIR=/opt/arcnode/tls
LETSENCRYPT_DIR=/opt/arcnode/letsencrypt
WEBROOT=/opt/arcnode/acme
LIVE="$LETSENCRYPT_DIR/live/$SITE_HOST"
CERTBOT_IMAGE=certbot/certbot:v3.0.1

register_address() {
  curl -fsS --retry 5 --retry-delay 2 --retry-connrefused \
    -X POST "$SITE_CALLBACK_URL" \
    -H "X-Site-Token: $SITE_TOKEN" \
    -H 'Content-Type: application/json' \
    -d "{\"address\":\"$SITE_ADDRESS\"}"
  echo
}

# The readiness gate: the name resolves to this box. No guessed delay, no fallback.
wait_for_dns() {
  until [ "$(getent ahostsv4 "$SITE_HOST" | awk 'NR==1 {print $1}')" = "$SITE_ADDRESS" ]; do
    echo "waiting for $SITE_HOST to resolve to $SITE_ADDRESS"
    sleep 10
  done
}

ingress_container() {
  docker ps --format '{{.Names}}' | grep 'https-ingress' | head -n 1 || true
}

# Port 80 is free before the stack starts (standalone); once the ingress holds it, it serves
# /.well-known/acme-challenge from the webroot instead.
obtain_certificate() {
  mkdir -p "$WEBROOT" "$LETSENCRYPT_DIR"
  local common=(certonly --non-interactive --agree-tos --register-unsafely-without-email
    --keep-until-expiring -d "$SITE_HOST")
  if [ -n "$(ingress_container)" ]; then
    docker run --rm -v "$LETSENCRYPT_DIR:/etc/letsencrypt" -v "$WEBROOT:/var/www/acme" \
      "$CERTBOT_IMAGE" "${common[@]}" --webroot -w /var/www/acme
  else
    docker run --rm -p 80:80 -v "$LETSENCRYPT_DIR:/etc/letsencrypt" \
      "$CERTBOT_IMAGE" "${common[@]}" --standalone
  fi
}

install_certificate() {
  if cmp -s "$LIVE/fullchain.pem" "$TLS_DIR/server.pem"; then
    echo "certificate already installed"
    return
  fi
  install -m 0644 "$LIVE/fullchain.pem" "$TLS_DIR/server.pem"
  install -m 0600 "$LIVE/privkey.pem" "$TLS_DIR/server-key.pem"
  # The wizard reads its certificate at start; the ingress at reload.
  systemctl restart arcnode-wizard
  local ingress
  ingress="$(ingress_container)"
  if [ -n "$ingress" ]; then
    docker exec "$ingress" nginx -s reload
  fi
  echo "installed the certificate for $SITE_HOST"
}

case "${1:-}" in
  issue)
    register_address
    wait_for_dns
    obtain_certificate
    install_certificate
    ;;
  renew)
    obtain_certificate
    install_certificate
    ;;
  *)
    echo "usage: site-cert.sh issue|renew" >&2
    exit 2
    ;;
esac
