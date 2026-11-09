# Alerts come from two places: the services' structured logs, where every line
# carries an "event" field, and Pub/Sub's own metrics. Each alert links to the
# runbook entry that says what to do.

locals {
  runbook = "https://github.com/${var.github_repository}/blob/main/docs/runbook.md"

  # Log events that need a person, with their runbook entries.
  alerting_events = {
    emergency_stop = { title = "A listing was refused by the emergency stop", runbook = "emergency-stop" }
    rejected       = { title = "The signer rejected an instruction", runbook = "rejected-instruction" }
    error          = { title = "A service hit an unexpected error", runbook = "service-error" }
  }
}

resource "google_monitoring_notification_channel" "email" {
  display_name = "Autolister on-call"
  type         = "email"
  labels       = { email_address = var.alert_email }
  depends_on   = [google_project_service.apis]
}

resource "google_logging_metric" "events" {
  for_each    = local.alerting_events
  name        = "autolister/${each.key}"
  description = each.value.title
  filter      = "resource.type=\"gce_instance\" AND jsonPayload.event=\"${each.key}\""

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
  }
}

resource "google_monitoring_alert_policy" "events" {
  for_each              = local.alerting_events
  display_name          = "Autolister: ${each.value.title}"
  combiner              = "OR"
  notification_channels = [google_monitoring_notification_channel.email.id]

  conditions {
    display_name = each.value.title
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.events[each.key].name}\" AND resource.type=\"gce_instance\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_SUM"
        cross_series_reducer = "REDUCE_SUM"
      }
    }
  }

  documentation {
    content   = "Runbook: ${local.runbook}#${each.value.runbook}"
    mime_type = "text/markdown"
  }
}

# The engine logs one "market" (or, outside the rewards window, "paused") event
# per cycle. Silence means it has stopped.
resource "google_logging_metric" "engine_cycles" {
  name        = "autolister/engine_cycles"
  description = "Completed engine cycles"
  filter      = "resource.type=\"gce_instance\" AND jsonPayload.event=(\"market\" OR \"paused\")"

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
  }
}

resource "google_monitoring_alert_policy" "engine_silent" {
  display_name          = "Autolister: the engine has stopped cycling"
  combiner              = "OR"
  notification_channels = [google_monitoring_notification_channel.email.id]

  conditions {
    display_name = "No engine cycle for 10 minutes"
    condition_absent {
      filter   = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.engine_cycles.name}\" AND resource.type=\"gce_instance\""
      duration = "600s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }

  documentation {
    content   = "Runbook: ${local.runbook}#engine-silent"
    mime_type = "text/markdown"
  }
}

resource "google_monitoring_alert_policy" "signer_backlog" {
  display_name          = "Autolister: instructions are waiting for the signer"
  combiner              = "OR"
  notification_channels = [google_monitoring_notification_channel.email.id]

  conditions {
    display_name = "Oldest unacknowledged instruction is over 10 minutes old"
    condition_threshold {
      filter          = "metric.type=\"pubsub.googleapis.com/subscription/oldest_unacked_message_age\" AND resource.type=\"pubsub_subscription\" AND resource.label.subscription_id=\"${google_pubsub_subscription.signer.name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 600
      duration        = "0s"

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MAX"
      }
    }
  }

  documentation {
    content   = "Runbook: ${local.runbook}#signer-backlog"
    mime_type = "text/markdown"
  }
}

resource "google_monitoring_alert_policy" "dead_letters" {
  display_name          = "Autolister: an instruction was dead-lettered"
  combiner              = "OR"
  notification_channels = [google_monitoring_notification_channel.email.id]

  conditions {
    display_name = "Instructions moved to the dead-letter topic"
    condition_threshold {
      filter          = "metric.type=\"pubsub.googleapis.com/subscription/dead_letter_message_count\" AND resource.type=\"pubsub_subscription\" AND resource.label.subscription_id=\"${google_pubsub_subscription.signer.name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }

  documentation {
    content   = "Runbook: ${local.runbook}#dead-lettered-instruction"
    mime_type = "text/markdown"
  }
}

# A wallet key should only ever be read by the signer. Anyone else reading one is
# treated as a possible compromise.
resource "google_logging_metric" "wallet_key_reads" {
  name        = "autolister/wallet_key_read_outside_signer"
  description = "A wallet key was read by an identity other than the signer"
  filter      = <<-EOT
    protoPayload.methodName="google.cloud.secretmanager.v1.SecretManagerService.AccessSecretVersion"
    protoPayload.resourceName=~"/secrets/wallet-"
    protoPayload.authenticationInfo.principalEmail!="${google_service_account.signer.email}"
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
  }

  depends_on = [google_project_iam_audit_config.secret_reads]
}

resource "google_monitoring_alert_policy" "wallet_key_reads" {
  display_name          = "Autolister: a wallet key was read outside the signer"
  combiner              = "OR"
  notification_channels = [google_monitoring_notification_channel.email.id]

  conditions {
    display_name = "Wallet key read by another identity"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.wallet_key_reads.name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }

  documentation {
    content   = "Runbook: ${local.runbook}#a-wallet-key-may-be-exposed"
    mime_type = "text/markdown"
  }
}
