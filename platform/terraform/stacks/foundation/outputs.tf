output "registry" {
  value = "${google_artifact_registry_repository.cdp.location}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.cdp.repository_id}"
}

output "service_accounts" {
  value = { for k, sa in google_service_account.sa : k => sa.email }
}
