# Data: long-lived, cents per month. BigQuery datasets/tables and Cloud Storage buckets.
# History survives `down`; only the runtime stack is destroyed between sessions.

terraform {
  required_version = ">= 1.5"
  required_providers {
    google = { source = "hashicorp/google", version = "~> 6.0" }
  }
  backend "gcs" {}
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  contracts = "${path.module}/../../../../contracts/bigquery"
  sa = {
    dataflow = "cdp-dataflow@${var.project_id}.iam.gserviceaccount.com"
    sources  = "cdp-sources@${var.project_id}.iam.gserviceaccount.com"
  }
}

# ── Cloud Storage ─────────────────────────────────────────────────────────────

resource "google_storage_bucket" "dataflow" {
  name                        = "${var.project_id}-cdp-dataflow"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = true
  labels                      = var.labels

  lifecycle_rule {
    condition {
      age            = 7
      matches_prefix = ["temp/", "staging/"]
    }
    action { type = "Delete" }
  }
}

resource "google_storage_bucket" "world" {
  name                        = "${var.project_id}-cdp-world"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = true
  labels                      = var.labels
}

resource "google_storage_bucket_iam_member" "dataflow_bucket" {
  bucket = google_storage_bucket.dataflow.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${local.sa.dataflow}"
}

resource "google_storage_bucket_iam_member" "sources_world" {
  bucket = google_storage_bucket.world.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${local.sa.sources}"
}

# ── BigQuery ──────────────────────────────────────────────────────────────────

resource "google_bigquery_dataset" "core" {
  dataset_id                 = "core"
  location                   = var.bq_location
  description                = "Resolved, deduplicated customer data (history)"
  labels                     = var.labels
  delete_contents_on_destroy = true
}

resource "google_bigquery_dataset" "ops" {
  dataset_id                 = "ops"
  location                   = var.bq_location
  description                = "Operational data: dead letters, reconciliation"
  labels                     = var.labels
  delete_contents_on_destroy = true
}

resource "google_bigquery_table" "interactions" {
  dataset_id          = google_bigquery_dataset.core.dataset_id
  table_id            = "interactions"
  deletion_protection = false
  schema              = file("${local.contracts}/core/interactions.json")
  clustering          = ["customer_id", "channel"]

  time_partitioning {
    type  = "DAY"
    field = "event_ts"
  }
}

resource "google_bigquery_table" "dead_letter" {
  dataset_id          = google_bigquery_dataset.ops.dataset_id
  table_id            = "dead_letter"
  deletion_protection = false
  schema              = file("${local.contracts}/ops/dead_letter.json")
  clustering          = ["source", "error_code"]

  time_partitioning {
    type  = "DAY"
    field = "failed_ts"
  }
}

resource "google_bigquery_dataset_iam_member" "dataflow_writes" {
  for_each   = { core = google_bigquery_dataset.core.dataset_id, ops = google_bigquery_dataset.ops.dataset_id }
  dataset_id = each.value
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${local.sa.dataflow}"
}
