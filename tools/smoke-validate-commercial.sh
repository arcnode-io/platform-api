#!/usr/bin/env bash
# Assert the commercial smoke broker leg published rows to Tiger Cloud
# under our site_id, then clean those rows out to keep the test DB tidy.
#
# Env contract:
#   TIGERDATA_CONNECTION_STRING — psql-compatible URL with creds
#   SITE_ID                     — value the smoke deploy used for SITE_ID
#                                 (gateway scopes MQTT topics + DB writes)
#
# Usage: ./smoke-validate-commercial.sh
set -euo pipefail

: "${TIGERDATA_CONNECTION_STRING:?Tiger URL required}"
: "${SITE_ID:?site_id required}"

# Give telemetry-writer ~60s to subscribe + persist after the stack
# reports CREATE_COMPLETE. Containers race-init for a few seconds.
sleep 60

COUNT=$(psql "$TIGERDATA_CONNECTION_STRING" -tA -c \
    "SELECT COUNT(*) FROM measurements WHERE site_id = '${SITE_ID}'")

echo "rows for site_id=${SITE_ID}: $COUNT"

if [ "$COUNT" -gt 0 ]; then
    echo "✓ broker leg validated — rows persisted"
    # Clean up so the CI test DB doesn't accumulate per-pipeline cruft
    psql "$TIGERDATA_CONNECTION_STRING" -c \
        "DELETE FROM measurements WHERE site_id = '${SITE_ID}'"
    exit 0
else
    echo "✗ no rows from ${SITE_ID} — broker leg broken"
    exit 1
fi
