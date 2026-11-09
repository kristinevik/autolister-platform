resource "google_artifact_registry_repository" "images" {
  location      = var.region
  repository_id = "autolister"
  format        = "DOCKER"
  description   = "Autolister images, tagged with the commit they were built from."
  depends_on    = [google_project_service.apis]
}
