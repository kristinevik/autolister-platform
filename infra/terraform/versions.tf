terraform {
  required_version = ">= 1.3.0, < 2.0.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 4.44"
    }
  }

  # State lives in a versioned bucket, created once by hand (docs/runbook.md):
  #   terraform init -backend-config="bucket=<project>-terraform-state"
  backend "gcs" {
    prefix = "autolister"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
