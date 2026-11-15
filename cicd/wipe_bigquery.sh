#!/usr/bin/env bash
# Delete the BigQuery history (core.interactions, ops.dead_letter) so the next deploy starts empty.
# Needs: WIPE_BIGQUERY, CLOUDSDK_CORE_PROJECT. Skipped unless WIPE_BIGQUERY=true.
#
# Drops the tables instead of DELETE/TRUNCATE: the pipeline uses streaming inserts, and DML is refused
# on rows still in the streaming buffer (up to ~90 minutes after the last insert). The datasets and
# their IAM stay; the next deploy's deploy-data step (Terraform, data stack) recreates the tables
# from contracts/bigquery. A dropped table can still be restored within BigQuery's 7-day time travel
# window, e.g. bq cp "core.interactions@<epoch_ms>" core.interactions
set -euo pipefail

if [ "${WIPE_BIGQUERY}" != "true" ]; then
  echo "== WIPE_BIGQUERY=${WIPE_BIGQUERY}: keeping BigQuery history"
  exit 0
fi

for TABLE in core.interactions ops.dead_letter; do
  REF="${CLOUDSDK_CORE_PROJECT}:${TABLE}"
  if bq show "${REF}" >/dev/null 2>&1; then
    echo "== drop ${TABLE}"
    bq rm -f -t "${REF}"
  else
    echo "== ${TABLE} not found, nothing to drop"
  fi
done
