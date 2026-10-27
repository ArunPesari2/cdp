output "dataflow_bucket" {
  value = google_storage_bucket.dataflow.name
}

output "world_uri" {
  value = "gs://${google_storage_bucket.world.name}/world/people.parquet"
}
