# Pitfall P5 ENFORCEMENT: this resource MUST NOT have a `connector` attribute.
# Cloud Run uses Direct VPC Egress via vpc_access.network_interfaces — the
# serverless VPC Access connector ($25/mo) is the wrong default; Direct VPC
# Egress is free and works identically for our throughput.
# Pitfall P9 ENFORCEMENT: min_instance_count MUST be 0 at MVP.
# Keeping a warm instance burns the Cloud Run free tier in days.
# Pitfall P7 ENFORCEMENT: image tag MUST come from var.image_tag (CI passes
# github.sha). The :latest default is only a bootstrap convenience — CI
# overrides on every deploy.

locals {
  # Secret env injection map. Keys are the env var names exposed inside the
  # container; values are the secret_id strings from the secret-manager module
  # (each.key in that module — see modules/secret-manager/main.tf locals.secrets).
  backend_secret_envs = {
    OPENAI_API_KEY    = var.secret_ids["tide-openai-api-key"]
    ANTHROPIC_API_KEY = var.secret_ids["tide-anthropic-api-key"]
    LANGFUSE_BUNDLE   = var.secret_ids["tide-langfuse"] # JSON: { public_key, secret_key }
    DATABASE_BUNDLE   = var.secret_ids["tide-db"]       # JSON: { password, url, sync_url }
    REDIS_URL         = var.secret_ids["tide-redis-url"]
    QDRANT_URL        = var.secret_ids["tide-qdrant-url"]
  }
}

resource "google_cloud_run_v2_service" "backend" {
  name     = "tide-backend"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = var.backend_sa_email

    scaling {
      min_instance_count = 0 # Pitfall P9 — scale-to-zero. Do NOT raise at MVP.
      max_instance_count = 10
    }
    timeout                          = "120s"
    max_instance_request_concurrency = 80

    vpc_access {
      egress = "PRIVATE_RANGES_ONLY"
      network_interfaces { # Pitfall P5 — NEVER `connector =`
        network    = var.vpc_id
        subnetwork = var.subnet_id
        tags       = ["tide-cloudrun"]
      }
    }

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/tide/backend:${var.image_tag}"

      ports {
        container_port = 8000
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
        cpu_idle          = true # bill CPU only during request (scale-to-zero alignment)
        startup_cpu_boost = true # Pitfall P2 — cold-start mitigation
      }

      # Non-secret env: VM internal IP for upstream health checks. The
      # canonical DB/Redis/Qdrant URLs are injected via the Secret Manager
      # bundles above; TIDE_VM_INTERNAL_IP is a debugging convenience.
      env {
        name  = "TIDE_VM_INTERNAL_IP"
        value = var.vm_internal_ip
      }
      env {
        name  = "TIDE_ENVIRONMENT"
        value = "production"
      }

      # Secret env injection. Each entry resolves to
      # value_source.secret_key_ref { secret = secret_id, version = "latest" }.
      # `version = "latest"` is the Secret Manager version selector (NOT a
      # container image tag) and is the documented, safe pattern for rotation
      # — Cloud Run refreshes the value on next revision deploy.
      dynamic "env" {
        for_each = local.backend_secret_envs
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value
              version = "latest"
            }
          }
        }
      }
    }
  }
}

# Public API — allow unauthenticated invocations. Authentication for the MVP
# is handled application-side via rate limiting (SEC-02 / L-05); accounts are
# explicitly out of scope per CLAUDE.md locked decisions.
resource "google_cloud_run_v2_service_iam_member" "public" {
  project  = var.project_id
  location = google_cloud_run_v2_service.backend.location
  name     = google_cloud_run_v2_service.backend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
