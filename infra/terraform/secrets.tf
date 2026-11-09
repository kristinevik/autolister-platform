# Terraform creates the secrets and decides who may read each one, but never
# holds a value: an operator adds those with `gcloud secrets versions add`
# (docs/runbook.md), so no secret reaches Terraform state or this repository.

locals {
  secret_readers = merge(
    {
      "instruction-hmac-key" = ["engine", "signer"]
      "alchemy-api-key"      = ["engine"]
      "nftbank-api-key"      = ["engine"]
      "looksrare-api-key"    = ["signer"]
      "eth-rpc-url"          = ["signer"]
    },
    { for id in local.account_ids : "wallet-${id}" => ["signer"] },
  )

  secret_bindings = merge([
    for secret, readers in local.secret_readers : {
      for reader in readers : "${secret}/${reader}" => { secret = secret, reader = reader }
    }
  ]...)
}

resource "google_secret_manager_secret" "secrets" {
  for_each  = local.secret_readers
  secret_id = each.key

  replication {
    automatic = true
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_iam_member" "readers" {
  for_each  = local.secret_bindings
  secret_id = google_secret_manager_secret.secrets[each.value.secret].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.workloads[each.value.reader]}"
}

# The break-glass cancel-all seals its instructions with the HMAC key.
resource "google_secret_manager_secret_iam_member" "operators" {
  for_each  = var.operators
  secret_id = google_secret_manager_secret.secrets["instruction-hmac-key"].id
  role      = "roles/secretmanager.secretAccessor"
  member    = each.value
}

# Record every read of a secret. Data Access audit logs are off by default; with
# them on, monitoring.tf can alert when anyone but the signer reads a wallet key.
resource "google_project_iam_audit_config" "secret_reads" {
  project = var.project_id
  service = "secretmanager.googleapis.com"

  audit_log_config {
    log_type = "DATA_READ"
  }
}
