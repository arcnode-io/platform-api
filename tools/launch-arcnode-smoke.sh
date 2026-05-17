#!/usr/bin/env bash
# Launch a defense-variant smoke stack from the local CfnService.
#
# Renders the template via `uv run python` (no platform-api server
# needed), uploads to S3 so CFN's --template-url path is reused, and
# kicks off the stack with a real DTM URL.
#
# DTM is the gotcha: UserData curls --fail-on-error on the URL before
# starting docker compose. example.invalid kills the script. We use
# the industrial-fixtures DTM pre-uploaded to s3://arcnode-public/seed/.
#
# Usage:
#   ./launch-arcnode-smoke.sh                          # auto-pick stack name
#   ./launch-arcnode-smoke.sh <STACK_NAME>             # caller-named
#
# After CREATE_COMPLETE: `aws ssm start-session --target <i-...>` to
# poke around. Tear down with ./teardown-arcnode-smoke.sh <STACK>.

set -euo pipefail

DTM_URL="${DTM_URL:-https://arcnode-public.s3.us-east-1.amazonaws.com/seed/industrial-fixtures.json}"
OWM_KEY="${OWM_KEY:-00000000000000000000000000000000}"  # dummy — non-weather smoke
SITE_ID="${SITE_ID:-arcnode_smoke}"
STACK_NAME="${1:-arcnode-smoke-defense-$(date -u +%Y%m%d-%H%M%S)}"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE_FILE="/tmp/${STACK_NAME}.yaml"

echo "→ rendering defense template"
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
    deployment_context=DeploymentContext.DEFENSE_FORWARD,
)
with open('${TEMPLATE_FILE}', 'w') as f:
    f.write(yaml)
print(f'template_size={len(yaml)} bytes')
"

echo "→ creating stack: $STACK_NAME"
# Default ROLLBACK on failure → CFN tears everything down, no AWS spend
# after a bad launch. Set KEEP_FAILED=1 to override with DO_NOTHING for
# active debug (lets you SSM into the half-deployed EC2 to read cloud-init
# logs — but you MUST tear down manually after).
ON_FAILURE="${KEEP_FAILED:+DO_NOTHING}"
ON_FAILURE="${ON_FAILURE:-ROLLBACK}"
aws cloudformation create-stack \
    --stack-name "$STACK_NAME" \
    --template-body "file://${TEMPLATE_FILE}" \
    --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND \
    --parameters "ParameterKey=OpenweathermapApiKey,ParameterValue=${OWM_KEY}" \
    --tags Key=arcnode-smoke,Value=phase5 Key=auto-teardown,Value=true \
    --on-failure "$ON_FAILURE" \
    --output text --query 'StackId'

echo "$STACK_NAME"
echo "→ tail events:  aws cloudformation describe-stack-events --stack-name $STACK_NAME"
echo "→ wait done:    until [[ \"\$(aws cloudformation describe-stacks --stack-name $STACK_NAME --query 'Stacks[0].StackStatus' --output text)\" =~ ^(CREATE_COMPLETE|.*FAILED|ROLLBACK.*) ]]; do sleep 30; done"
echo "→ teardown:     ./tools/teardown-arcnode-smoke.sh $STACK_NAME"
