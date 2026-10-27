# Runtime: billed by the hour. Applied by the deploy pipeline (cicd/deploy.yaml),
# destroyed by the teardown pipeline (cicd/teardown.yaml).
# Spanner, Pub/Sub, Customer API (Cloud Run), mock sources (Cloud Run jobs).
# The Dataflow care pipeline is a release, not infrastructure: the deploy pipeline starts or
# updates it (cicd/deploy_care_job.sh) and the teardown pipeline stops it (cicd/stop_care_job.sh).

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
  migrations_dir = "${path.module}/../../../../contracts/spanner/migrations"
  # Every ordered migration file, comments stripped, split into single DDL statements.
  ddl = flatten([
    for f in sort(fileset(local.migrations_dir, "*.sql")) : [
      for s in split(";", replace(file("${local.migrations_dir}/${f}"), "/--[^\n]*/", "")) :
      trimspace(s) if trimspace(s) != ""
    ]
  ])

  sa = {
    dataflow     = "cdp-dataflow@${var.project_id}.iam.gserviceaccount.com"
    customer_api = "cdp-customer-api@${var.project_id}.iam.gserviceaccount.com"
    sources      = "cdp-sources@${var.project_id}.iam.gserviceaccount.com"
  }
  common_env = {
    GCP_PROJECT      = var.project_id
    SPANNER_INSTANCE = google_spanner_instance.cdp.name
    SPANNER_DATABASE = google_spanner_database.cdp.name
  }
  world_uri = "gs://${var.project_id}-cdp-world/world/people.parquet"
}

# ── Spanner ───────────────────────────────────────────────────────────────────

resource "google_spanner_instance" "cdp" {
  name             = "cdp-instance"
  config           = "regional-${var.region}"
  display_name     = "CDP instance" # 4-30 characters
  processing_units = var.spanner_processing_units
  force_destroy    = true
  labels           = var.labels
}

resource "google_spanner_database" "cdp" {
  instance            = google_spanner_instance.cdp.name
  name                = "cdp"
  ddl                 = local.ddl
  deletion_protection = false
}

resource "google_spanner_database_iam_member" "access" {
  for_each = {
    dataflow     = { member = local.sa.dataflow, role = "roles/spanner.databaseUser" }
    sources      = { member = local.sa.sources, role = "roles/spanner.databaseUser" }
    customer_api = { member = local.sa.customer_api, role = "roles/spanner.databaseReader" }
  }
  instance = google_spanner_instance.cdp.name
  database = google_spanner_database.cdp.name
  role     = each.value.role
  member   = "serviceAccount:${each.value.member}"
}

# ── Pub/Sub: the contact-centre vendor's stream ───────────────────────────────

resource "google_pubsub_topic" "vendor_care_ctr" {
  name                       = "vendor-care-ctr"
  message_retention_duration = "604800s" # 7 days: replay window
  labels                     = var.labels
}

resource "google_pubsub_subscription" "care_pipeline" {
  name                       = "vendor-care-ctr-pipeline"
  topic                      = google_pubsub_topic.vendor_care_ctr.id
  ack_deadline_seconds       = 60
  message_retention_duration = "604800s"
  retain_acked_messages      = true # allows seek/replay of processed messages
  labels                     = var.labels

  expiration_policy {
    ttl = "" # never expire
  }
}

resource "google_pubsub_topic_iam_member" "vendor_publishes" {
  topic  = google_pubsub_topic.vendor_care_ctr.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${local.sa.sources}"
}

resource "google_pubsub_subscription_iam_member" "dataflow_consumes" {
  for_each     = toset(["roles/pubsub.subscriber", "roles/pubsub.viewer"])
  subscription = google_pubsub_subscription.care_pipeline.name
  role         = each.value
  member       = "serviceAccount:${local.sa.dataflow}"
}

# ── Customer API (Cloud Run service, authenticated callers only) ──────────────

resource "google_cloud_run_v2_service" "customer_api" {
  name                = "customer-api"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false
  labels              = var.labels

  template {
    service_account = local.sa.customer_api
    scaling {
      min_instance_count = var.api_min_instances
      max_instance_count = 3
    }
    containers {
      image = var.customer_api_image
      resources {
        limits = { cpu = "1", memory = "1Gi" }
      }
      dynamic "env" {
        for_each = local.common_env
        content {
          name  = env.key
          value = env.value
        }
      }
      startup_probe {
        http_get { path = "/actuator/health" }
        initial_delay_seconds = 5
        period_seconds        = 5
        failure_threshold     = 24
      }
    }
  }
  depends_on = [google_spanner_database_iam_member.access]
}

# Only the smoke-test identity is granted invoke here; channels get their own grants.
resource "google_cloud_run_v2_service_iam_member" "smoke_invoker" {
  name     = google_cloud_run_v2_service.customer_api.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:cdp-smoke@${var.project_id}.iam.gserviceaccount.com"
}

# ── Mock source systems (Cloud Run jobs) ──────────────────────────────────────

resource "google_cloud_run_v2_job" "sources" {
  for_each = {
    "cdp-seed"        = ["cdp_sources.world.seed", "--count", "10000"]
    "cdp-care-vendor" = ["cdp_sources.care.mock_vendor", "--count", "50"]
  }
  name                = each.key
  location            = var.region
  deletion_protection = false
  labels              = var.labels

  template {
    template {
      service_account = local.sa.sources
      timeout         = "1800s"
      max_retries     = 0
      containers {
        image = var.sources_image
        args  = each.value
        resources {
          limits = { cpu = "1", memory = "1Gi" }
        }
        dynamic "env" {
          for_each = merge(local.common_env, { CDP_WORLD_URI = local.world_uri })
          content {
            name  = env.key
            value = env.value
          }
        }
      }
    }
  }
  depends_on = [google_spanner_database_iam_member.access]
}
