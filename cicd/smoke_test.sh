#!/usr/bin/env bash
# End-to-end smoke test after a deploy:
#   seed customers (idempotent) -> vendor sends 1 contact for a known customer
#   -> Dataflow -> Spanner -> the contact is visible through the Customer API.
# Needs: REGION, CLOUDSDK_CORE_PROJECT. Runs as cdp-deployer; calls the API as cdp-smoke.
set -euo pipefail
trap 'echo "FAIL: smoke test stopped at line ${LINENO}" >&2' ERR

PROJECT="${CLOUDSDK_CORE_PROJECT}"
SMOKE_SA="cdp-smoke@${PROJECT}.iam.gserviceaccount.com"

echo "== Seeding customers (idempotent)"
gcloud run jobs execute cdp-seed --region="${REGION}" --wait

PHONE=$(gcloud spanner databases execute-sql cdp --instance=cdp-instance --format=json \
  --sql="SELECT phone FROM Customer ORDER BY customer_id LIMIT 1" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["rows"][0][0])')
URL=$(gcloud run services describe customer-api --region="${REGION}" --format="value(status.url)")
TOKEN=$(gcloud auth print-identity-token --impersonate-service-account="${SMOKE_SA}" \
  --audiences="${URL}" --include-email 2>/dev/null)
echo "== Test customer ${PHONE}, API ${URL}, caller ${SMOKE_SA}"

latest_contact() {
  curl -sS --fail-with-body -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" \
    -d "{\"query\":\"{ customer(phone: \\\"${PHONE}\\\") { recentInteractions(limit: 1) { eventId } } }\"}" \
    "${URL}/graphql" \
  | python3 -c 'import json,sys; r=json.load(sys.stdin)["data"]["customer"]["recentInteractions"]; print(r[0]["eventId"] if r else "none")'
}

BEFORE=$(latest_contact)
echo "== Latest contact before: ${BEFORE}"

gcloud run jobs execute cdp-care-vendor --region="${REGION}" --wait \
  --args="cdp_sources.care.mock_vendor,--count=1,--phone=${PHONE},--dup-pct=0,--unknown-pct=0,--invalid-pct=0"
SENT=$(date +%s)

# A fresh deploy includes Dataflow worker start-up, so allow up to 10 minutes.
for _ in $(seq 1 60); do
  AFTER=$(latest_contact)
  if [ "${AFTER}" != "${BEFORE}" ]; then
    echo "PASS: contact ${AFTER} visible through the API $(( $(date +%s) - SENT ))s after it was sent"
    exit 0
  fi
  sleep 10
done
echo "FAIL: contact not visible through the API after 10 minutes" >&2
exit 1
