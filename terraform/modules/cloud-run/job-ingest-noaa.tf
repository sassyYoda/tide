# INFRA-03 — NOAA ingest as Cloud Run Job. Schedule lives in scheduler.tf.
# Pitfall P5 — Direct VPC Egress (network_interfaces; NEVER `connector`).
# Pitfall P12 — TIDE_INGEST_VIA_CLOUD_RUN_JOBS=true env signals the VM-side
# Celery beat (celery_app/__init__.py) to strip its duplicate ingest entries
# so we never double-poll NOAA.

resource "google_cloud_run_v2_job" "ingest_noaa" {
  name     = "tide-ingest-noaa"
  location = var.region

  template {
    template {
      service_account = var.ingest_sa_email
      timeout         = "300s"
      max_retries     = 1

      vpc_access {
        egress = "ALL_TRAFFIC"
        network_interfaces { # Pitfall P5 — NEVER `connector =`
          network    = var.vpc_id
          subnetwork = var.subnet_id
        }
      }

      containers {
        image   = "${var.region}-docker.pkg.dev/${var.project_id}/tide/worker:${var.image_tag}"
        command = ["uv", "run", "python", "-m", "celery_app.entrypoints.ingest_noaa"]

        env {
          name  = "TIDE_INGEST_VIA_CLOUD_RUN_JOBS"
          value = "true" # Pitfall P12 — defends future drift even though the
          # one-shot entrypoint doesn't import the beat schedule
        }

        env {
          name = "DATABASE_BUNDLE"
          value_source {
            secret_key_ref {
              secret  = var.secret_ids["tide-db"]
              version = "latest"
            }
          }
        }

        env {
          name = "REDIS_URL"
          value_source {
            secret_key_ref {
              secret  = var.secret_ids["tide-redis-url"]
              version = "latest"
            }
          }
        }
      }
    }
  }
}
