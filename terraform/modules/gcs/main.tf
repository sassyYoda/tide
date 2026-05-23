# 4 GCS buckets (RESEARCH §Wave 0). Lifecycle policy per bucket — never-delete on
# tide-models (training artifacts keep forever); 30d on raw + qdrant snapshots;
# 7d on pg_dump (A5 — short retention because daily dumps + small DB).
locals {
  buckets = {
    "tide-models" = { lifecycle_days = null } # never delete
    "tide-raw"    = { lifecycle_days = 30 }
    "tide-qdrant" = { lifecycle_days = 30 }
    "tide-pgdump" = { lifecycle_days = 7 } # A5 — pg_dump retention
  }
}

resource "google_storage_bucket" "this" {
  for_each                    = local.buckets
  name                        = "${var.project_id}-${each.key}"
  location                    = var.region
  force_destroy               = false
  uniform_bucket_level_access = true
  versioning {
    enabled = false
  }
  dynamic "lifecycle_rule" {
    for_each = each.value.lifecycle_days == null ? [] : [each.value.lifecycle_days]
    content {
      action {
        type = "Delete"
      }
      condition {
        age = lifecycle_rule.value
      }
    }
  }
}

resource "google_storage_bucket_iam_member" "vm_admin" {
  for_each = local.buckets
  bucket   = google_storage_bucket.this[each.key].name
  role     = "roles/storage.objectAdmin"
  member   = "serviceAccount:${var.vm_sa_email}"
}

resource "google_storage_bucket_iam_member" "ingest_admin" {
  for_each = local.buckets
  bucket   = google_storage_bucket.this[each.key].name
  role     = "roles/storage.objectAdmin"
  member   = "serviceAccount:${var.ingest_sa_email}"
}

resource "google_storage_bucket_iam_member" "backend_viewer" {
  for_each = local.buckets
  bucket   = google_storage_bucket.this[each.key].name
  role     = "roles/storage.objectViewer"
  member   = "serviceAccount:${var.backend_sa_email}"
}
