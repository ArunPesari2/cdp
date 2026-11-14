#!/bin/sh
# Run Terraform for one stack in one environment (used by all Cloud Build pipelines).
#   cicd/tf.sh <foundation|data|runtime> <plan|apply|destroy|output> [-var=...]
# Needs: ENV, TF_STATE_BUCKET. "output" saves each stack output to .deploy/<stack>/<name>.
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
  # One file per output, .deploy/<stack>/<name>, holding the bare value (-raw), so later steps read
  # it with cat and need no JSON parser. Plain "terraform output" lists "name = value" lines; sed
  # keeps the names. -raw only accepts strings, numbers and bools, so a list or map output fails here.
  output)  mkdir -p "${ROOT}/.deploy/${STACK}"
           for NAME in $(terraform output | sed -n 's/^\([A-Za-z0-9_-]*\) = .*/\1/p'); do
             terraform output -raw "${NAME}" > "${ROOT}/.deploy/${STACK}/${NAME}"
           done ;;
  *)       echo "unknown action ${ACTION}" >&2; exit 2 ;;
esac
