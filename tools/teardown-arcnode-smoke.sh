#!/usr/bin/env bash
# Tear down arcnode-smoke-* CloudFormation stacks safely.
#
# Handles the known gotchas:
#   - AuroraBootstrapCustomResource hangs Delete for ~60 min; on
#     DELETE_FAILED we retry with --retain-resources so CFN moves on.
#   - AOSS collection in CREATING refuses Delete; we wait until ACTIVE.
#   - Aurora + Neptune + AOSS each drain 5-15 min after delete-stack
#     returns; we poll until everything is gone before declaring victory.
#   - VPC quota (default 5) means we can't leave stacks half-deleted.
#
# Usage:
#   ./teardown-arcnode-smoke.sh                    # tear down ALL arcnode-smoke-* stacks
#   ./teardown-arcnode-smoke.sh <STACK_NAME>       # tear down one stack only
#
# Exit 0 on ALL CLEAR. Non-zero if we couldn't make progress.

set -euo pipefail

POLL_SECONDS="${POLL_SECONDS:-30}"
# CFN's default custom-resource timeout is 60 min. Hard cap a bit higher.
MAX_WAIT_SECONDS="${MAX_WAIT_SECONDS:-4200}"

log()  { printf '%s %s\n' "$(date -u +%H:%M:%S)" "$*"; }
warn() { printf '%s WARN %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }
err()  { printf '%s ERR  %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }

list_smoke_stacks() {
    aws cloudformation list-stacks \
        --stack-status-filter \
            DELETE_IN_PROGRESS DELETE_FAILED \
            CREATE_COMPLETE CREATE_IN_PROGRESS \
            UPDATE_COMPLETE UPDATE_IN_PROGRESS \
            ROLLBACK_COMPLETE ROLLBACK_IN_PROGRESS \
        --query 'StackSummaries[?contains(StackName, `arcnode-smoke`)].StackName' \
        --output text
}

stack_status() {
    aws cloudformation describe-stacks --stack-name "$1" 2>/dev/null \
        | jq -r '.Stacks[0].StackStatus // "DELETED"'
}

# Wait for any in-flight AOSS collection in this stack to leave CREATING.
# Delete will be refused while CREATING — AWS service-side constraint.
wait_for_aoss_active() {
    local stack="$1"
    local aoss_id
    aoss_id=$(aws cloudformation describe-stack-resource \
        --stack-name "$stack" --logical-resource-id AossCollection \
        --query 'StackResourceDetail.PhysicalResourceId' \
        --output text 2>/dev/null || true)
    [[ -z "$aoss_id" || "$aoss_id" == "None" ]] && return 0
    log "  AOSS collection $aoss_id — waiting for non-CREATING status"
    local elapsed=0
    while true; do
        local st
        st=$(aws opensearchserverless batch-get-collection --ids "$aoss_id" 2>/dev/null \
            | jq -r '.collectionDetails[0].status // "GONE"')
        case "$st" in
            CREATING)
                sleep "$POLL_SECONDS"
                elapsed=$((elapsed + POLL_SECONDS))
                if [[ $elapsed -gt 600 ]]; then
                    err "  AOSS stuck in CREATING > 10min — giving up"
                    return 1
                fi
                ;;
            *)
                log "  AOSS status: $st — proceeding with Delete"
                return 0
                ;;
        esac
    done
}

# Kick the first Delete + watch for DELETE_FAILED (Aurora bootstrap hang).
# On DELETE_FAILED, force with --retain-resources AuroraBootstrapCustomResource.
delete_one_stack() {
    local stack="$1"
    local start_status
    start_status=$(stack_status "$stack")
    log "stack $stack — start status $start_status"

    case "$start_status" in
        DELETE_COMPLETE|DELETED) return 0 ;;
        DELETE_IN_PROGRESS) ;;  # already in flight
        DELETE_FAILED)
            warn "  already DELETE_FAILED — force with retain"
            aws cloudformation delete-stack \
                --stack-name "$stack" \
                --retain-resources AuroraBootstrapCustomResource >/dev/null
            ;;
        *)
            wait_for_aoss_active "$stack" || true
            aws cloudformation delete-stack --stack-name "$stack" >/dev/null
            ;;
    esac

    local elapsed=0
    local forced=0
    while true; do
        local st
        st=$(stack_status "$stack")
        case "$st" in
            DELETE_COMPLETE|DELETED)
                log "  $stack — done"
                return 0
                ;;
            DELETE_FAILED)
                if [[ $forced -eq 1 ]]; then
                    err "  $stack — DELETE_FAILED after retain. Manual intervention needed."
                    aws cloudformation describe-stack-resources \
                        --stack-name "$stack" \
                        --query 'StackResources[?ResourceStatus==`DELETE_FAILED`].[LogicalResourceId,ResourceType]' \
                        --output table >&2
                    return 1
                fi
                warn "  $stack — DELETE_FAILED. Retrying with --retain-resources AuroraBootstrapCustomResource"
                aws cloudformation delete-stack \
                    --stack-name "$stack" \
                    --retain-resources AuroraBootstrapCustomResource >/dev/null
                forced=1
                ;;
        esac
        sleep "$POLL_SECONDS"
        elapsed=$((elapsed + POLL_SECONDS))
        if [[ $elapsed -gt $MAX_WAIT_SECONDS ]]; then
            err "  $stack — wait cap exceeded ($MAX_WAIT_SECONDS sec). Last status: $st"
            return 1
        fi
    done
}

confirm_all_clear() {
    local vpcs aurora neptune aoss smoke_stacks
    vpcs=$(aws ec2 describe-vpcs --query 'length(Vpcs)' --output text)
    aurora=$(aws rds describe-db-clusters --query 'length(DBClusters)' --output text)
    neptune=$(aws neptune describe-db-clusters --query 'length(DBClusters[?Engine==`neptune`])' --output text)
    aoss=$(aws opensearchserverless list-collections --query 'length(collectionSummaries)' --output text)
    smoke_stacks=$(aws cloudformation list-stacks \
        --stack-status-filter DELETE_IN_PROGRESS DELETE_FAILED CREATE_COMPLETE \
        --query 'length(StackSummaries[?contains(StackName, `arcnode-smoke`)])' \
        --output text)
    log "final: vpcs=$vpcs aurora=$aurora neptune=$neptune aoss=$aoss smoke_stacks=$smoke_stacks"
    if [[ $vpcs -le 1 && $aurora -eq 0 && $neptune -eq 0 && $aoss -eq 0 && $smoke_stacks -eq 0 ]]; then
        log "ALL CLEAR — zero billable smoke resources remain"
        return 0
    fi
    warn "non-zero resources still alive — bill is still growing"
    return 1
}

main() {
    local stacks
    if [[ $# -ge 1 ]]; then
        stacks="$1"
    else
        stacks=$(list_smoke_stacks)
    fi

    if [[ -z "$stacks" ]]; then
        log "no arcnode-smoke-* stacks found"
        confirm_all_clear
        return $?
    fi

    log "tearing down: $stacks"
    local failed=0
    for s in $stacks; do
        delete_one_stack "$s" || failed=1
    done

    confirm_all_clear || failed=1
    return $failed
}

main "$@"
