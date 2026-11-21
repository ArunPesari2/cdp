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

# value(rows[0][0]): gcloud prints the first column of the first row itself (no JSON parser needed),
# and prints nothing if the query returns no rows. Demo customers (@example.com, see
# sources/cdp_sources/demo_stories.py) are skipped so the smoke contact never lands in their story.
PHONE=$(gcloud spanner databases execute-sql cdp --instance=cdp-instance --format="value(rows[0][0])" \
  --sql="SELECT phone FROM Customer WHERE email NOT LIKE '%@example.com' ORDER BY customer_id LIMIT 1")
[ -n "${PHONE}" ] || { echo "FAIL: no customer in Spanner after seeding" >&2; exit 1; }
URL=$(gcloud run services describe customer-api --region="${REGION}" --format="value(status.url)")
TOKEN=$(gcloud auth print-identity-token --impersonate-service-account="${SMOKE_SA}" \
  --audiences="${URL}" --include-email 2>/dev/null)
echo "== Test customer ${PHONE}, API ${URL}, caller ${SMOKE_SA}"

# The API answers in compact JSON: {"data":{"customer":{"recentInteractions":[{"eventId":"..."}]}}}.
# sed prints the eventId, or nothing when the list is empty (the query asks for exactly one field).
latest_contact() {
  curl -sS --fail-with-body -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" \
    -d "{\"query\":\"{ customer(phone: \\\"${PHONE}\\\") { recentInteractions(limit: 1) { eventId } } }\"}" \
    "${URL}/graphql" \
  | sed -n 's/.*"eventId":"\([^"]*\)".*/\1/p'
}

BEFORE=$(latest_contact)
echo "== Latest contact before: ${BEFORE:-none}"

gcloud run jobs execute cdp-care-vendor --region="${REGION}" --wait \
  --args="cdp_sources.care.mock_vendor,--count=1,--phone=${PHONE},--dup-pct=0,--unknown-pct=0,--invalid-pct=0"
SENT=$(date +%s)

# A fresh deploy includes Dataflow worker start-up, so allow up to 10 minutes.
for _ in $(seq 1 60); do
  AFTER=$(latest_contact)
  if [ -n "${AFTER}" ] && [ "${AFTER}" != "${BEFORE}" ]; then
    echo "PASS: contact ${AFTER} visible through the API $(( $(date +%s) - SENT ))s after it was sent"
    exit 0
  fi
  sleep 10
done
echo "FAIL: contact not visible through the API after 10 minutes" >&2
exit 1
