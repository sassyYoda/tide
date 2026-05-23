output "cloudrun_backend_sa_email" {
  value = google_service_account.cloudrun_backend.email
}

output "cloudrun_ingest_sa_email" {
  value = google_service_account.cloudrun_ingest.email
}

output "vm_sa_email" {
  value = google_service_account.vm.email
}

output "github_actions_sa_email" {
  value = google_service_account.github_actions.email
}

output "wif_provider_name" {
  # Full resource name; GH Actions google-github-actions/auth@v2 consumes this as
  # workload_identity_provider input.
  value = google_iam_workload_identity_pool_provider.github.name
}

output "wif_pool_name" {
  value = google_iam_workload_identity_pool.github.name
}

# Plan 06-04 — Cloud Scheduler SA email; consumed by modules/cloud-run/scheduler.tf
# as the oauth_token.service_account_email for the 3 cron triggers.
output "scheduler_sa_email" {
  value = google_service_account.scheduler.email
}
