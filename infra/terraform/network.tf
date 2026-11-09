# A private network. No VM has a public address and nothing may connect in, not
# even SSH: logs go to Cloud Logging, and a broken VM is replaced, not repaired.
# Outbound traffic leaves through Cloud NAT.

resource "google_compute_network" "autolister" {
  name                    = "autolister"
  auto_create_subnetworks = false
  depends_on              = [google_project_service.apis]
}

resource "google_compute_subnetwork" "autolister" {
  name                     = "autolister"
  network                  = google_compute_network.autolister.id
  region                   = var.region
  ip_cidr_range            = "10.10.0.0/24"
  private_ip_google_access = true # Google APIs without going through the NAT
}

# GCP denies ingress by default; this makes it explicit, and logs any attempt.
resource "google_compute_firewall" "deny_all_ingress" {
  name          = "autolister-deny-all-ingress"
  network       = google_compute_network.autolister.id
  direction     = "INGRESS"
  priority      = 65534
  source_ranges = ["0.0.0.0/0"]

  deny {
    protocol = "all"
  }

  log_config {
    metadata = "INCLUDE_ALL_METADATA"
  }
}

resource "google_compute_router" "autolister" {
  name    = "autolister"
  network = google_compute_network.autolister.id
  region  = var.region
}

resource "google_compute_router_nat" "autolister" {
  name                               = "autolister"
  router                             = google_compute_router.autolister.name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}
