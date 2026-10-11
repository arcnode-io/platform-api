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
  RESEND_API_KEY=arcnode-platform/resend-api-key; do
  name="${pair%%=*}"
  secret="${pair#*=}"
  value=$(aws secretsmanager get-secret-value --region "$REGION" \
    --secret-id "$secret" --query SecretString --output text)
  printf '%s=%s\n' "$name" "$value" >> secrets.env.new
done
mv secrets.env.new secrets.env
