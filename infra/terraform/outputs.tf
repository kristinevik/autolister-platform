output "artifact_registry" {
  description = "Where CI pushes images: the ARTIFACT_REGISTRY repository secret."
  value       = local.registry
}

output "artifact_registry_host" {
  description = "The ARTIFACT_REGISTRY_HOST repository secret."
  value       = local.registry_host
}

output "workload_identity_provider" {
  description = "The WORKLOAD_IDENTITY_PROVIDER repository secret."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "ci_service_account" {
  description = "The CI_SERVICE_ACCOUNT repository secret."
  value       = google_service_account.ci.email
}

output "secrets_to_populate" {
  description = "Secrets that need a value; add one to each with gcloud (docs/runbook.md)."
  value       = sort(keys(google_secret_manager_secret.secrets))
}
