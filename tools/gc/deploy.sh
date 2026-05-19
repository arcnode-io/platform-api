#!/usr/bin/env bash
# Deploy arcnode-gc — daily orphan-sweep Lambda.
#
# Builds a zip of handler.py, inlines it into the CFN template, deploys.
# Idempotent — re-runs are CFN updates.
#
# Usage:  ./deploy.sh

set -euo pipefail

STACK_NAME="${STACK_NAME:-arcnode-gc}"
REGION="${AWS_REGION:-us-east-1}"

cd "$(dirname "$0")"

# Inline handler.py into the CFN template (avoids S3 upload + LambdaCode
# S3Bucket/S3Key wiring). Indent so the YAML key nests right.
python3 -c "
src = open('handler.py').read()
tpl = open('arcnode-gc.yaml').read()
indented = '\n'.join('          ' + line for line in src.splitlines())
print(tpl.replace('          PLACEHOLDER_REPLACED_BY_DEPLOY_SCRIPT', indented))
" > /tmp/arcnode-gc-rendered.yaml

aws cloudformation deploy \
    --stack-name "$STACK_NAME" \
    --template-file /tmp/arcnode-gc-rendered.yaml \
    --capabilities CAPABILITY_NAMED_IAM \
    --region "$REGION" \
    --no-fail-on-empty-changeset

echo "deployed. invoke once to verify:"
echo "  aws lambda invoke --function-name arcnode-gc --region $REGION /tmp/gc-out.json && cat /tmp/gc-out.json"
