#!/usr/bin/env bash
# Launch a commercial-variant smoke stack from the local CfnService.
#
# Renders the commercial template (Aurora + customer-supplied Aura/Tiger URLs
# as CFN Secrets Manager entries) and kicks off the stack.
#
# Required env:
#   AURA_CONNECTION_STRING       — neo4j+s://user:pass@host:port
#   TIGERDATA_CONNECTION_STRING  — postgres://user:pass@host:port/db?sslmode=require
#
# Usage:
#   ./launch-arcnode-smoke-commercial.sh                    # auto-pick stack name
#   ./launch-arcnode-smoke-commercial.sh <STACK_NAME>       # caller-named

set -euo pipefail

: "${AURA_CONNECTION_STRING:?must export AURA_CONNECTION_STRING}"
: "${TIGERDATA_CONNECTION_STRING:?must export TIGERDATA_CONNECTION_STRING}"

DTM_URL="${DTM_URL:-https://arcnode-public.s3.us-east-1.amazonaws.com/seed/industrial-fixtures.json}"
OWM_KEY="${OWM_KEY:-00000000000000000000000000000000}"  # dummy — non-weather smoke
SITE_ID="${SITE_ID:-arcnode_smoke}"
WHOLESALE_MARKET="${WHOLESALE_MARKET:-ercot}"
SETTLEMENT_POINT="${SETTLEMENT_POINT:-HB_NORTH}"
STACK_NAME="${1:-arcnode-smoke-commercial-$(date -u +%Y%m%d-%H%M%S)}"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE_FILE="/tmp/${STACK_NAME}.yaml"

echo "→ rendering commercial template"
cd "$REPO_ROOT"
uv run python -c "
import uuid
from src.cfn.cfn_service import CfnService
from src.cfn.persistence.persistence_service import PersistenceService
from src.orders.configurator_payload import DeploymentContext

duid = str(uuid.uuid4())
print(f'deployment_uuid={duid}')
yaml = CfnService(persistence=PersistenceService()).render_template(
    deployment_uuid=duid,
    dtm_url='${DTM_URL}',
    ems_mode='sim',
    site_id='${SITE_ID}',
    wholesale_market='${WHOLESALE_MARKET}',
    settlement_point='${SETTLEMENT_POINT}',
    deployment_context=DeploymentContext.COMMERCIAL,
)
with open('${TEMPLATE_FILE}', 'w') as f:
    f.write(yaml)
print(f'template_size={len(yaml)} bytes')
"

echo "→ creating stack: $STACK_NAME"
# Default ROLLBACK on failure → CFN tears everything down, no AWS spend
# after a bad launch. Set KEEP_FAILED=1 to override with DO_NOTHING for
# active debug.
ON_FAILURE="${KEEP_FAILED:+DO_NOTHING}"
ON_FAILURE="${ON_FAILURE:-ROLLBACK}"
aws cloudformation create-stack \
    --stack-name "$STACK_NAME" \
    --template-body "file://${TEMPLATE_FILE}" \
    --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND \
    --parameters \
        "ParameterKey=OpenweathermapApiKey,ParameterValue=${OWM_KEY}" \
        "ParameterKey=GraphConnectionUrl,ParameterValue=${AURA_CONNECTION_STRING}" \
        "ParameterKey=TimeseriesConnectionUrl,ParameterValue=${TIGERDATA_CONNECTION_STRING}" \
    --tags Key=arcnode-smoke,Value=commercial Key=auto-teardown,Value=true \
    --on-failure "$ON_FAILURE" \
    --output text --query 'StackId'

echo "$STACK_NAME"
echo "→ teardown: ./tools/teardown-arcnode-smoke.sh $STACK_NAME"
