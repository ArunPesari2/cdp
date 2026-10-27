# Foundation: long-lived, ~free, applied by a platform admin (not by CI).
# APIs, Artifact Registry, service accounts and their roles, budget.
# Cloud Build pipelines (cicd/*.yaml) are started by hand with `gcloud builds submit`; see README.

terraform {
  required_version = ">= 1.5"
  required_providers {
    google = { source = "hashicorp/google", version = "~> 6.0" }
  }
  backend "gcs" {}
}

provider "google" {
  project               = var.project_id
  region                = var.region
  user_project_override = true
  billing_project       = var.project_id
}

locals {
  services = [
    "artifactregistry.googleapis.com",
    "bigquery.googleapis.com",
    "billingbudgets.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "dataflow.googleapis.com",
    "iam.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "pubsub.googleapis.com",
    "run.googleapis.com",
    "spanner.googleapis.com",
    "storage.googleapis.com",
  ]

  # One identity per component, least privilege.
  service_accounts = {
    dataflow     = { id = "cdp-dataflow", name = "CDP Dataflow workers" }
    customer_api = { id = "cdp-customer-api", name = "CDP Customer API (Cloud Run)" }
    sources      = { id = "cdp-sources", name = "CDP mock source systems (Cloud Run jobs)" }
    deployer     = { id = "cdp-deployer", name = "CDP CD: builds and deploys data + runtime stacks" }
    smoke        = { id = "cdp-smoke", name = "CDP smoke test: may only call the Customer API" }
  }
  runtime_identities = ["dataflow", "customer_api", "sources"]

  # Deployer manages the data and runtime stacks only; foundation stays with admins.
  deployer_roles = [
    "roles/bigquery.admin",
    "roles/dataflow.admin",
    "roles/logging.logWriter",
    "roles/pubsub.admin",
    "roles/run.admin",
    "roles/spanner.admin",
    "roles/storage.admin",
  ]
}

resource "google_project_service" "services" {
  for_each           = toset(local.services)
  service            = each.value
  disable_on_destroy = false
}

resource "google_service_account" "sa" {
  for_each     = local.service_accounts
  account_id   = each.value.id
  display_name = each.value.name
  depends_on   = [google_project_service.services]
}

resource "google_artifact_registry_repository" "cdp" {
  location      = var.region
  repository_id = "cdp"
  format        = "DOCKER"
  description   = "CDP container images"
  labels        = var.labels
  depends_on    = [google_project_service.services]

  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = 10
    }
  }
}

# ── Runtime identities ────────────────────────────────────────────────────────

# dataflow.developer: the Flex Template launcher runs as this account and must find and
# update the running job on each release (in-place streaming update).
resource "google_project_iam_member" "dataflow_worker" {
  for_each = toset(["roles/dataflow.worker", "roles/dataflow.developer", "roles/monitoring.metricWriter", "roles/logging.logWriter"])
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.sa["dataflow"].email}"
}

# Google client libraries (Spanner) export their own built-in metrics.
resource "google_project_iam_member" "client_metrics" {
  for_each = toset(["sources", "customer_api"])
  project  = var.project_id
  role     = "roles/monitoring.metricWriter"
  member   = "serviceAccount:${google_service_account.sa[each.value].email}"
}

resource "google_artifact_registry_repository_iam_member" "dataflow_reader" {
  location   = google_artifact_registry_repository.cdp.location
  repository = google_artifact_registry_repository.cdp.name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.sa["dataflow"].email}"
}

# ── CD identity (cdp-deployer) ────────────────────────────────────────────────

resource "google_project_iam_member" "deployer" {
  for_each = toset(local.deployer_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.sa["deployer"].email}"
}

resource "google_artifact_registry_repository_iam_member" "deployer_writer" {
  location   = google_artifact_registry_repository.cdp.location
  repository = google_artifact_registry_repository.cdp.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.sa["deployer"].email}"
}

# The deployer may run workloads as the runtime identities, and only those.
resource "google_service_account_iam_member" "deployer_act_as" {
  for_each           = toset(local.runtime_identities)
  service_account_id = google_service_account.sa[each.value].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.sa["deployer"].email}"
}

# The smoke test calls the Customer API as cdp-smoke (invoker only, granted in the runtime
# stack); the deployer mints short-lived ID tokens for it by impersonation.
resource "google_service_account_iam_member" "deployer_impersonates_smoke" {
  service_account_id = google_service_account.sa["smoke"].name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.sa["deployer"].email}"
}

# ── Budget alert ──────────────────────────────────────────────────────────────

data "google_project" "this" {}

resource "google_billing_budget" "cdp" {
  count           = var.billing_account_id == "" ? 0 : 1
  billing_account = var.billing_account_id
  display_name    = "CDP ${var.project_id}"

  budget_filter {
    projects = ["projects/${data.google_project.this.number}"]
  }
  amount {
    specified_amount {
      units = tostring(var.monthly_budget)
    }
  }
  dynamic "threshold_rules" {
    for_each = [0.5, 0.8, 1.0]
    content {
      threshold_percent = threshold_rules.value
    }
  }
  depends_on = [google_project_service.services]
}
