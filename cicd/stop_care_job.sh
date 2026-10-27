#!/usr/bin/env bash
# Stop the care pipeline before the runtime stack (its subscription and Spanner) is destroyed,
# and wait until it has stopped.
# Needs: ENV, REGION, CLOUDSDK_CORE_PROJECT.
# cancel or drain comes from CARE_ON_STOP in platform/terraform/envs/<env>/care-pipeline.env.
set -euo pipefail

JOB_NAME="care-pipeline"
. "platform/terraform/envs/${ENV}/care-pipeline.env"

case "${CARE_ON_STOP}" in
  cancel|drain) ;;
  *) echo "CARE_ON_STOP must be cancel or drain, got '${CARE_ON_STOP}'" >&2; exit 2 ;;
esac

active_jobs() {
  gcloud dataflow jobs list --region="${REGION}" --status=active \
    --filter="name=${JOB_NAME}" --format="value(id)"
}

IDS=$(active_jobs)
if [ -z "${IDS}" ]; then
  echo "== No running ${JOB_NAME} job"
  exit 0
fi

for ID in ${IDS}; do
  echo "== ${CARE_ON_STOP} job ${ID}"
  gcloud dataflow jobs "${CARE_ON_STOP}" "${ID}" --region="${REGION}"
done

# Draining finishes in-flight data first, so allow up to 20 minutes.
for _ in $(seq 1 120); do
  if [ -z "$(active_jobs)" ]; then
    echo "PASS: ${JOB_NAME} stopped"
    exit 0
  fi
  sleep 10
done
echo "FAIL: ${JOB_NAME} still running after 20 minutes" >&2
exit 1
