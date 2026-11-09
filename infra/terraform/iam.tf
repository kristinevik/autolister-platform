# One service account per workload, each with only what it needs. Access to
# individual secrets, the topic and the subscription is granted on those
# resources (secrets.tf, pubsub.tf); project-wide, a workload may only write its
# own logs and metrics.

resource "google_service_account" "engine" {
  account_id   = "autolister-engine"
  display_name = "Autolister engine"
  description  = "Reads market data and publishes instructions. Cannot read wallet keys."
}

resource "google_service_account" "signer" {
  account_id   = "autolister-signer"
  display_name = "Autolister signer"
  description  = "Consumes instructions and signs orders. The only identity that can read wallet keys."
}

locals {
  workloads = {
    engine = google_service_account.engine.email
    signer = google_service_account.signer.email
  }
  workload_project_roles = ["roles/logging.logWriter", "roles/monitoring.metricWriter"]
}

resource "google_project_iam_member" "workloads" {
  for_each = {
    for pair in setproduct(keys(local.workloads), local.workload_project_roles) :
    "${pair[0]}/${pair[1]}" => { workload = pair[0], role = pair[1] }
  }
  project = var.project_id
  role    = each.value.role
  member  = "serviceAccount:${local.workloads[each.value.workload]}"
}

resource "google_artifact_registry_repository_iam_member" "workloads_pull" {
  for_each   = local.workloads
  location   = google_artifact_registry_repository.images.location
  repository = google_artifact_registry_repository.images.name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${each.value}"
}
