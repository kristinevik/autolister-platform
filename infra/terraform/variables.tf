variable "project_id" {
  description = "The Google Cloud project Autolister runs in."
  type        = string
}

variable "region" {
  description = "Region for every regional resource."
  type        = string
  default     = "europe-north1"
}

variable "zone" {
  description = "Zone for the two VMs."
  type        = string
  default     = "europe-north1-a"
}

variable "image_tag" {
  description = "Image tag to run: the commit SHA that CI built and pushed. Apply from that same commit."
  type        = string
}

variable "trading_enabled" {
  description = "Engine kill switch. False keeps the engine observing and logging, but it publishes nothing."
  type        = bool
  default     = true
}

variable "signing_enabled" {
  description = "Signer kill switch. False stops the signer consuming instructions; queued ones expire."
  type        = bool
  default     = true
}

variable "max_fee_gwei" {
  description = "The most the signer pays per unit of gas for a cancellation. Raise it if cancellations stall during a gas spike."
  type        = number
  default     = 50
}

variable "operators" {
  description = "Members allowed to run the break-glass cancel-all, e.g. \"group:oncall@example.com\"."
  type        = set(string)
  default     = []
}

variable "github_repository" {
  description = "The repository (\"owner/name\") whose main branch may push images."
  type        = string
}

variable "alert_email" {
  description = "Where alerts are sent."
  type        = string
}
