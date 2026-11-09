# Each service is one container on its own small VM: Container-Optimized OS,
# shielded boot, no public address and no way in (network.tf). Each VM belongs to
# a managed instance group of one, so a VM that dies is recreated, and a deploy
# (a new image tag) replaces it. The old VM always stops before the new one
# starts: there is never more than one signer.

locals {
  registry_host = "${var.region}-docker.pkg.dev"
  registry      = "${local.registry_host}/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"

  services = {
    engine = {
      service_account = google_service_account.engine.email
      env = {
        AUTOLISTER_GCP_PROJECT     = var.project_id
        AUTOLISTER_TRADING_ENABLED = tostring(var.trading_enabled)
      }
    }
    signer = {
      service_account = google_service_account.signer.email
      env = {
        AUTOLISTER_GCP_PROJECT     = var.project_id
        AUTOLISTER_SIGNING_ENABLED = tostring(var.signing_enabled)
        AUTOLISTER_MAX_FEE_GWEI    = tostring(var.max_fee_gwei)
      }
    }
  }
}

# The newest stable COS image at apply time: applying is also how the VMs get patched.
data "google_compute_image" "cos" {
  family  = "cos-stable"
  project = "cos-cloud"
}

resource "google_compute_instance_template" "service" {
  for_each     = local.services
  name_prefix  = "autolister-${each.key}-"
  machine_type = "e2-small"
  tags         = ["autolister"]
  labels       = { service = each.key }

  disk {
    source_image = data.google_compute_image.cos.self_link
    disk_type    = "pd-balanced"
    disk_size_gb = 10
    boot         = true
    auto_delete  = true
  }

  network_interface {
    subnetwork = google_compute_subnetwork.autolister.id
    # No access_config block, so no public IP.
  }

  service_account {
    email  = each.value.service_account
    scopes = ["cloud-platform"] # IAM decides what it can do
  }

  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  metadata = {
    user-data = templatefile("${path.module}/cloud-init.yaml.tftpl", {
      service       = each.key
      image         = "${local.registry}/${each.key}:${var.image_tag}"
      registry_host = local.registry_host
      env           = each.value.env
    })
    google-logging-enabled    = "true"
    google-monitoring-enabled = "true"
    enable-oslogin            = "TRUE"
    block-project-ssh-keys    = "true"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "google_compute_instance_group_manager" "service" {
  for_each           = local.services
  name               = "autolister-${each.key}"
  base_instance_name = "autolister-${each.key}"
  zone               = var.zone
  target_size        = 1

  version {
    instance_template = google_compute_instance_template.service[each.key].id
  }

  update_policy {
    type                  = "PROACTIVE"
    minimal_action        = "REPLACE"
    replacement_method    = "RECREATE"
    max_surge_fixed       = 0
    max_unavailable_fixed = 1
  }
}
