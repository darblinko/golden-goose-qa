#!/usr/bin/env bash
#
# Completely remove the Golden Goose AWS test deployment.
#
# Order matters: `terraform destroy` fails on S3 buckets that still hold object
# versions, so this empties every versioned bucket first, defensively disables
# RDS deletion protection, then destroys, then proves nothing tagged with the
# project survived. It is idempotent: safe to re-run after a partial failure.
#
# Object Lock deviation: the buckets are versioning-only, with no
# Object Lock/immutability, precisely so this script can empty them for a clean
# teardown of a disposable test deploy. A retention-locked bucket cannot be
# emptied until its retention elapses; that is the correct trade for durable
# environments but the wrong one for throwaway infra.
#
# Usage:
#   AWS_PROFILE=<profile> scripts/teardown_aws.sh            # prompts to confirm
#   AWS_PROFILE=<profile> FORCE=1 scripts/teardown_aws.sh    # no prompt
#
# The same variables used for `terraform apply` must be resolvable at destroy
# time (Terraform requires every declared variable even to destroy). Provide
# them via a gitignored tfvars file (TFVARS_FILE=...) or TF_VAR_* env vars.
set -euo pipefail

AWS_PROFILE="${AWS_PROFILE:?set AWS_PROFILE to the profile used for terraform apply}"
AWS_REGION="${AWS_REGION:-us-east-1}"
PROJECT_TAG="${GG_PROJECT_TAG:-goldengoose}"
ENVIRONMENT="${GG_ENVIRONMENT:-dev}"
FORCE="${FORCE:-0}"
export AWS_PROFILE AWS_REGION AWS_DEFAULT_REGION="${AWS_REGION}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF_DIR="${TF_DIR:-${SCRIPT_DIR}/../infra/terraform/aws}"

# Prefer OpenTofu if that is what stood the stack up; fall back to terraform.
TF_BIN="${TF_BIN:-}"
if [[ -z "${TF_BIN}" ]]; then
  if command -v terraform >/dev/null 2>&1; then
    TF_BIN=terraform
  elif command -v tofu >/dev/null 2>&1; then
    TF_BIN=tofu
  else
    echo "error: neither terraform nor tofu found on PATH (set TF_BIN)" >&2
    exit 1
  fi
fi

log() { printf '\n=== %s ===\n' "$*"; }

require() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "error: required command not found: $1" >&2
    exit 1
  }
}

require aws
require jq

log "Preflight"
aws sts get-caller-identity >/dev/null || {
  echo "error: no valid AWS credentials for profile '${AWS_PROFILE}'" >&2
  exit 1
}
echo "profile=${AWS_PROFILE} region=${AWS_REGION} project=${PROJECT_TAG} environment=${ENVIRONMENT}"

if [[ "${FORCE}" != "1" ]]; then
  read -r -p "This DESTROYS all '${PROJECT_TAG}-${ENVIRONMENT}' AWS infra. Type 'destroy' to proceed: " reply
  [[ "${reply}" == "destroy" ]] || {
    echo "aborted"
    exit 1
  }
fi

# Resolve bucket names from Terraform state when possible; otherwise fall back
# to the naming convention in storage.tf so teardown still works if state is
# unreadable.
bucket_names() {
  local from_state
  if from_state="$("${TF_BIN}" -chdir="${TF_DIR}" output -json bucket_names 2>/dev/null)" &&
    [[ -n "${from_state}" && "${from_state}" != "null" ]]; then
    echo "${from_state}" | jq -r '.[]'
    return
  fi
  local suffix
  for suffix in documents artifacts backups; do
    echo "${PROJECT_TAG}-${ENVIRONMENT}-${suffix}"
  done
}

empty_bucket() {
  local bucket="$1"
  if ! aws s3api head-bucket --bucket "${bucket}" 2>/dev/null; then
    echo "  ${bucket}: absent, skipping"
    return
  fi
  echo "  ${bucket}: emptying all versions and delete markers"
  # Page through versions + delete markers, deleting up to 1000 keys per call.
  while true; do
    local batch
    batch="$(
      aws s3api list-object-versions --bucket "${bucket}" --max-items 1000 \
        --query '{Objects: (([Versions, DeleteMarkers][] || `[]`)[].{Key: Key, VersionId: VersionId})}' \
        --output json 2>/dev/null || echo '{"Objects":[]}'
    )"
    local count
    count="$(echo "${batch}" | jq '.Objects | length')"
    [[ "${count}" -gt 0 ]] || break
    echo "${batch}" | jq '. + {Quiet: true}' >/tmp/gg-delete-batch.json
    aws s3api delete-objects --bucket "${bucket}" --delete "file:///tmp/gg-delete-batch.json" >/dev/null
    echo "    deleted ${count}"
  done
  rm -f /tmp/gg-delete-batch.json
}

log "Emptying versioned S3 buckets"
while read -r bucket; do
  [[ -n "${bucket}" ]] && empty_bucket "${bucket}"
done < <(bucket_names)

log "Disabling RDS deletion protection (defensive; ignored if already off)"
aws rds modify-db-instance \
  --db-instance-identifier "${PROJECT_TAG}-${ENVIRONMENT}-pg" \
  --no-deletion-protection --apply-immediately >/dev/null 2>&1 ||
  echo "  no RDS instance or already unprotected"

log "terraform destroy"
DESTROY_ARGS=(-chdir="${TF_DIR}" destroy -auto-approve)
if [[ -n "${TFVARS_FILE:-}" ]]; then
  DESTROY_ARGS+=("-var-file=${TFVARS_FILE}")
fi
"${TF_BIN}" "${DESTROY_ARGS[@]}"

log "Verifying zero remaining tagged resources"
remaining="$(
  aws resourcegroupstaggingapi get-resources \
    --tag-filters "Key=project,Values=${PROJECT_TAG}" \
    --region "${AWS_REGION}" \
    --query 'ResourceTagMappingList[].ResourceARN' --output json
)"
count="$(echo "${remaining}" | jq 'length')"
if [[ "${count}" -gt 0 ]]; then
  echo "FAIL: ${count} resource(s) still tagged project=${PROJECT_TAG}:" >&2
  echo "${remaining}" | jq -r '.[]' >&2
  echo "(IAM roles and other global/untagged resources are not covered by the" >&2
  echo " regional tag API — check the console if this list is unexpectedly empty.)" >&2
  exit 1
fi

log "Teardown complete: no resources tagged project=${PROJECT_TAG} remain in ${AWS_REGION}"
