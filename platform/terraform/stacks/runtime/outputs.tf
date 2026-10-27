output "customer_api_url" {
  value = google_cloud_run_v2_service.customer_api.uri
}

output "spanner_instance" {
  value = google_spanner_instance.cdp.name
}

output "spanner_database" {
  value = google_spanner_database.cdp.name
}

# Read by cicd/deploy_care_job.sh (via cicd/tf.sh runtime output) to start the care pipeline.
output "care_subscription" {
  value = google_pubsub_subscription.care_pipeline.name
}
