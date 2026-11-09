data "google_project" "this" {}

locals {
  # The accounts file the services ship with is also the source of truth here:
  # each account gets a wallet secret that only the signer can read.
  accounts    = yamldecode(file("${path.module}/../../config/accounts.yaml")).accounts
  account_ids = toset([for account in local.accounts : account.id])

  apis = toset([
    "artifactregistry.googleapis.com",
    "compute.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "pubsub.googleapis.com",
    "secretmanager.googleapis.com",
    "sts.googleapis.com",
  ])
}

resource "google_project_service" "apis" {
  for_each           = local.apis
  service            = each.value
  disable_on_destroy = false
}
