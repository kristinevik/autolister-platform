# Instructions flow one way, engine to signer, through a single topic. The engine
# may only publish to it and the signer may only consume from it.

resource "google_pubsub_topic" "instructions" {
  name       = "autolister-instructions"
  depends_on = [google_project_service.apis]
}

resource "google_pubsub_subscription" "signer" {
  name                       = "autolister-signer"
  topic                      = google_pubsub_topic.instructions.id
  enable_message_ordering    = true    # each account's instructions arrive in the order issued
  ack_deadline_seconds       = 600     # longer than the slowest step: mining a cancellation
  message_retention_duration = "3600s" # an instruction expires after an hour anyway

  expiration_policy {
    ttl = "" # never delete the subscription for inactivity
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "300s"
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dead_letter.id
    max_delivery_attempts = 5
  }
}

resource "google_pubsub_topic" "dead_letter" {
  name       = "autolister-instructions-dead-letter"
  depends_on = [google_project_service.apis]
}

# Dead-lettered instructions are kept for a week, for investigation.
resource "google_pubsub_subscription" "dead_letter" {
  name                       = "autolister-instructions-dead-letter"
  topic                      = google_pubsub_topic.dead_letter.id
  message_retention_duration = "604800s"

  expiration_policy {
    ttl = ""
  }
}

resource "google_pubsub_topic_iam_member" "engine_publishes" {
  topic  = google_pubsub_topic.instructions.id
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.engine.email}"
}

resource "google_pubsub_topic_iam_member" "operators_publish" {
  for_each = var.operators
  topic    = google_pubsub_topic.instructions.id
  role     = "roles/pubsub.publisher"
  member   = each.value
}

resource "google_pubsub_subscription_iam_member" "signer_consumes" {
  subscription = google_pubsub_subscription.signer.id
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${google_service_account.signer.email}"
}

# Pub/Sub's own service agent moves undeliverable messages to the dead-letter topic.
locals {
  pubsub_agent = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_pubsub_topic_iam_member" "agent_dead_letters" {
  topic  = google_pubsub_topic.dead_letter.id
  role   = "roles/pubsub.publisher"
  member = local.pubsub_agent
}

resource "google_pubsub_subscription_iam_member" "agent_forwards" {
  subscription = google_pubsub_subscription.signer.id
  role         = "roles/pubsub.subscriber"
  member       = local.pubsub_agent
}
