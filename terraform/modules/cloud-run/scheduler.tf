# INFRA-03 — 3 Cloud Scheduler cron triggers + per-job IAM invoker bindings.
# Free tier: 3 schedulers/month — we use exactly 3 (NOAA every 15 min,
# Open-Meteo every 30 min, solunar on the hour).
#
# Each trigger POSTs to the Cloud Run Jobs admin API with an OAuth token signed
# by var.scheduler_sa_email; the per-job IAM binding below grants that SA
# roles/run.invoker on each specific job (least-privilege per L-11).

locals {
  schedules = {
    ingest_noaa = {
      schedule = "*/15 * * * *"
      job_name = google_cloud_run_v2_job.ingest_noaa.name
    }
    ingest_meteo = {
      schedule = "*/30 * * * *"
      job_name = google_cloud_run_v2_job.ingest_meteo.name
    }
    compute_solunar = {
      schedule = "0 * * * *"
      job_name = google_cloud_run_v2_job.compute_solunar.name
    }
  }
}

resource "google_cloud_scheduler_job" "ingest" {
  for_each = local.schedules

  name      = "tide-${replace(each.key, "_", "-")}-trigger"
  schedule  = each.value.schedule
  time_zone = "Etc/UTC"
  region    = var.region

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${each.value.job_name}:run"

    oauth_token {
      service_account_email = var.scheduler_sa_email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  retry_config {
    retry_count = 1
  }
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker" {
  for_each = local.schedules

  project  = var.project_id
  location = var.region
  name     = each.value.job_name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.scheduler_sa_email}"
}
