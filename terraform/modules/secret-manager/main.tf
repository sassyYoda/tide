# 6 active Secret Manager secrets (Pitfall P11 — JSON-grouping keeps ceiling ≤ 6).
# Plan 06-02 overwrites the redis_url + qdrant_url placeholders with the actual
# VM internal IP after the compute-vm module is applied.
locals {
  secrets = {
    "tide-openai-api-key"    = var.openai_api_key
    "tide-anthropic-api-key" = var.anthropic_api_key
    "tide-langfuse"          = jsonencode({ public_key = var.langfuse_public_key, secret_key = var.langfuse_secret_key })
    "tide-db"                = jsonencode({ password = var.db_password }) # 06-02 extends with url + sync_url after VM IP known
    "tide-redis-url"         = "redis://redis@10.0.0.10:6379/0"            # placeholder; 06-02 overwrites with actual VM IP
    "tide-qdrant-url"        = "http://10.0.0.10:6333"                     # placeholder; 06-02 overwrites
  }
  consumer_sas = {
    backend = var.backend_sa_email
    ingest  = var.ingest_sa_email
    vm      = var.vm_sa_email
  }
}

resource "google_secret_manager_secret" "this" {
  for_each  = local.secrets
  secret_id = each.key
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "this" {
  for_each    = local.secrets
  secret      = google_secret_manager_secret.this[each.key].id
  secret_data = each.value
}

resource "google_secret_manager_secret_iam_member" "consumers" {
  for_each = {
    for pair in setproduct(keys(local.secrets), keys(local.consumer_sas)) :
    "${pair[0]}-${pair[1]}" => { secret = pair[0], sa = local.consumer_sas[pair[1]] }
  }
  secret_id = google_secret_manager_secret.this[each.value.secret].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${each.value.sa}"
}
