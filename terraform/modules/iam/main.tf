# 4 service accounts (RESEARCH §L-11) — least-privilege per consumer.
resource "google_service_account" "cloudrun_backend" {
  account_id   = "tide-cloudrun-backend"
  display_name = "Tide Cloud Run backend"
}

resource "google_service_account" "cloudrun_ingest" {
  account_id   = "tide-cloudrun-ingest"
  display_name = "Tide Cloud Run ingest jobs"
}

resource "google_service_account" "vm" {
  account_id   = "tide-vm"
  display_name = "Tide e2-micro VM"
}

resource "google_service_account" "github_actions" {
  account_id   = "tide-github-actions"
  display_name = "Tide GitHub Actions deployer"
}

# Plan 06-04 — Cloud Scheduler SA. Granted roles/run.invoker per-job in the
# cloud-run module (modules/cloud-run/scheduler.tf), so no project-level
# binding is needed here (least privilege per L-11).
resource "google_service_account" "scheduler" {
  account_id   = "tide-scheduler"
  display_name = "Tide Cloud Scheduler invoker"
}

# WIF pool + provider (Pitfall P6 — no JSON SA keys ever).
resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github-actions"
  display_name              = "GitHub Actions"
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub Actions"
  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.actor"      = "assertion.actor"
    "attribute.repository" = "assertion.repository"
  }
  # Defense-in-depth: restrict to ONLY this repo (Pitfall P6).
  attribute_condition = "assertion.repository == '${var.github_repo}'"
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "github_wif" {
  service_account_id = google_service_account.github_actions.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repo}"
}

# Project-level IAM bindings (L-11 least-privilege roles).
locals {
  backend_roles = [
    "roles/secretmanager.secretAccessor",
    "roles/storage.objectViewer",
    "roles/compute.networkUser",
  ]
  ingest_roles = [
    "roles/secretmanager.secretAccessor",
    "roles/storage.objectAdmin",
    "roles/compute.networkUser",
  ]
  vm_roles = [
    "roles/storage.objectAdmin",
    "roles/secretmanager.secretAccessor",
  ]
  github_roles = [
    "roles/artifactregistry.writer",
    "roles/run.admin",
    "roles/iam.serviceAccountUser",
    "roles/secretmanager.secretAccessor",
  ]
}

resource "google_project_iam_member" "backend" {
  for_each = toset(local.backend_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.cloudrun_backend.email}"
}

resource "google_project_iam_member" "ingest" {
  for_each = toset(local.ingest_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.cloudrun_ingest.email}"
}

resource "google_project_iam_member" "vm" {
  for_each = toset(local.vm_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.vm.email}"
}

resource "google_project_iam_member" "github" {
  for_each = toset(local.github_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.github_actions.email}"
}
