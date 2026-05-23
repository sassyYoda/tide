# INFRA-03 — Solunar compute as Cloud Run Job. Schedule lives in scheduler.tf.
# Pitfall P5 — Direct VPC Egress (network_interfaces; NEVER `connector`).
# Pitfall P12 — TIDE_INGEST_VIA_CLOUD_RUN_JOBS=true env signals the VM-side
# Celery beat to strip its duplicate ingest entries.

resource "google_cloud_run_v2_job" "compute_solunar" {
  name     = "tide-compute-solunar"
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
        command = ["uv", "run", "python", "-m", "celery_app.entrypoints.compute_solunar"]

        env {
          name  = "TIDE_INGEST_VIA_CLOUD_RUN_JOBS"
          value = "true"
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
