#!/usr/bin/env bash
# Cancel any running cdp-care-vendor execution (it may be generating load until stopped) before the
# runtime stack, and with it the topic it publishes to, is destroyed.
# Needs: REGION, CLOUDSDK_CORE_PROJECT.
set -euo pipefail

JOB="cdp-care-vendor"

# A running execution has no completionTime yet. If the job doesn't exist (runtime already
# destroyed), the list fails and there is nothing to cancel.
RUNNING=$(gcloud run jobs executions list --job="${JOB}" --region="${REGION}" \
  --filter="-status.completionTime:*" --format="value(metadata.name)" 2>/dev/null || true)

if [ -z "${RUNNING}" ]; then
  echo "== No running ${JOB} execution"
  exit 0
fi

for EXECUTION in ${RUNNING}; do
  echo "== cancel ${EXECUTION}"
  gcloud run jobs executions cancel "${EXECUTION}" --region="${REGION}" --quiet
done
