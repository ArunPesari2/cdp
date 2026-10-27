#!/usr/bin/env bash
# Start the care pipeline (Dataflow streaming job) from this release's Flex Template, or update the
# running job in place, then wait until it is running.
#   cicd/deploy_care_job.sh <gs:// path of the Flex Template file>
# Needs: ENV, REGION, CLOUDSDK_CORE_PROJECT, and .deploy/runtime-outputs.json (cicd/tf.sh runtime output).
# Job settings per environment: platform/terraform/envs/<env>/care-pipeline.env.
set -euo pipefail

TEMPLATE="$1"
PROJECT="${CLOUDSDK_CORE_PROJECT}"
JOB_NAME="care-pipeline"
. "platform/terraform/envs/${ENV}/care-pipeline.env"

# Resource names come from the runtime stack, not retyped here.
output() {
  python3 -c 'import json,sys; print(json.load(open(".deploy/runtime-outputs.json"))[sys.argv[1]]["value"])' "$1"
}
SUBSCRIPTION=$(output care_subscription)
SPANNER_INSTANCE=$(output spanner_instance)
SPANNER_DATABASE=$(output spanner_database)

ARGS=(
  --region="${REGION}"
  --template-file-gcs-location="${TEMPLATE}"
  --parameters="subscription=${SUBSCRIPTION},spanner_instance=${SPANNER_INSTANCE},spanner_database=${SPANNER_DATABASE}"
  --service-account-email="cdp-dataflow@${PROJECT}.iam.gserviceaccount.com"
  --temp-location="gs://${PROJECT}-cdp-dataflow/temp"
  --staging-location="gs://${PROJECT}-cdp-dataflow/staging"
  --worker-machine-type="${CARE_MACHINE_TYPE}"
  --num-workers=1
  --max-workers="${CARE_MAX_WORKERS}"
  --enable-streaming-engine
  --additional-user-labels="app=cdp,env=${ENV}"
  --format="value(job.id)"
)

RUNNING=$(gcloud dataflow jobs list --region="${REGION}" --status=active \
  --filter="name=${JOB_NAME}" --format="value(id)" | head -n 1)
if [ -n "${RUNNING}" ]; then
  echo "== Updating running job ${RUNNING} in place"
  ARGS+=(--update)
else
  echo "== Starting a new ${JOB_NAME} job"
fi

JOB_ID=$(gcloud dataflow flex-template run "${JOB_NAME}" "${ARGS[@]}")
echo "== Job ${JOB_ID} launched from ${TEMPLATE}; waiting until it is running"

# Launching includes starting the launcher VM, so allow up to 15 minutes.
for _ in $(seq 1 90); do
  STATE=$(gcloud dataflow jobs describe "${JOB_ID}" --region="${REGION}" --format="value(currentState)")
  case "${STATE}" in
    JOB_STATE_RUNNING)
      echo "PASS: job ${JOB_ID} is running"
      exit 0 ;;
    JOB_STATE_FAILED|JOB_STATE_CANCELLED|JOB_STATE_DRAINED)
      echo "FAIL: job ${JOB_ID} ended in ${STATE}; see the Dataflow console for its logs" >&2
      exit 1 ;;
  esac
  sleep 10
done
echo "FAIL: job ${JOB_ID} not running after 15 minutes (last state ${STATE})" >&2
exit 1
