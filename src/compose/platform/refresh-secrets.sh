#!/bin/bash
# Writes /opt/arcnode-platform/secrets.env from Secrets Manager, using the
# instance role. Runs at first boot (UserData) and on every deploy (CI through
# SSM), so a new secret only needs a Secrets Manager entry and a line here.
# Usage: refresh-secrets.sh <aws-region>
set -euo pipefail
REGION="$1"
cd /opt/arcnode-platform
umask 077
: > secrets.env.new
for pair in \
  POSTGRES_PASSWORD=arcnode-platform/postgres-password \
  RESEND_API_KEY=arcnode-platform/resend-api-key \
  NAMECHEAP_API_KEY=arcnode-platform/namecheap-api-key \
  SITE_TOKEN_SECRET=arcnode-platform/site-token-secret \
  PRESIGN_ACCESS_KEY_ID=arcnode-platform/presign-access-key-id \
  PRESIGN_SECRET_ACCESS_KEY=arcnode-platform/presign-secret-access-key; do
  name="${pair%%=*}"
  secret="${pair#*=}"
  value=$(aws secretsmanager get-secret-value --region "$REGION" \
    --secret-id "$secret" --query SecretString --output text)
  printf '%s=%s\n' "$name" "$value" >> secrets.env.new
done
mv secrets.env.new secrets.env
