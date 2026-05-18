#!/usr/bin/env bash
# Poll a CFN stack until it reaches a terminal state. Exits 0 on
# CREATE_COMPLETE, 1 on anything else (FAILED, ROLLBACK_*, etc.).
#
# Usage: ./smoke-wait-stack-ready.sh <STACK_NAME> [TIMEOUT_SECONDS]
set -euo pipefail

STACK_NAME="${1:?stack name required}"
TIMEOUT_SECONDS="${2:-1500}"

START=$(date +%s)
while true; do
    STATUS=$(aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --region us-east-1 \
        --query 'Stacks[0].StackStatus' \
        --output text 2>&1)

    case "$STATUS" in
        CREATE_COMPLETE)
            echo "✓ stack ready: $STACK_NAME"
            exit 0
            ;;
        CREATE_IN_PROGRESS)
            ;;  # keep polling
        *)
            echo "✗ stack failed: $STATUS"
            aws cloudformation describe-stack-events \
                --stack-name "$STACK_NAME" \
                --region us-east-1 \
                --query 'StackEvents[?ResourceStatus==`CREATE_FAILED`].[LogicalResourceId,ResourceStatusReason]' \
                --output table | head -20
            exit 1
            ;;
    esac

    ELAPSED=$(( $(date +%s) - START ))
    if [ "$ELAPSED" -gt "$TIMEOUT_SECONDS" ]; then
        echo "✗ timeout after ${TIMEOUT_SECONDS}s (still $STATUS)"
        exit 1
    fi
    sleep 30
done
