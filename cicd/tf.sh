#!/bin/sh
# Run Terraform for one stack in one environment (used by all Cloud Build pipelines).
#   cicd/tf.sh <foundation|data|runtime> <plan|apply|destroy|output> [-var=...]
# Needs: ENV, TF_STATE_BUCKET. "output" saves the stack's outputs to .deploy/<stack>-outputs.json.
set -eu

STACK="$1"
ACTION="$2"
shift 2

ROOT="$(pwd)"
cd "platform/terraform/stacks/${STACK}"
export TF_IN_AUTOMATION=1
VARFILE="../../envs/${ENV}/terraform.tfvars"

terraform init -input=false \
  -backend-config="bucket=${TF_STATE_BUCKET}" \
  -backend-config="prefix=cdp/${ENV}/${STACK}"

case "${ACTION}" in
  plan)    terraform plan -input=false -lock=false -var-file="${VARFILE}" "$@" ;;
  apply)   terraform apply -input=false -auto-approve -var-file="${VARFILE}" "$@" ;;
  destroy) terraform destroy -input=false -auto-approve -var-file="${VARFILE}" "$@" ;;
  output)  mkdir -p "${ROOT}/.deploy"
           terraform output -json > "${ROOT}/.deploy/${STACK}-outputs.json" ;;
  *)       echo "unknown action ${ACTION}" >&2; exit 2 ;;
esac
