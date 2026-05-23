variable "project_id" {
  type        = string
  description = "GCP project ID. Reserved for future cross-project bindings; not currently referenced (provider default applies)."
}

variable "openai_api_key" {
  type      = string
  sensitive = true
}

variable "anthropic_api_key" {
  type      = string
  sensitive = true
}

variable "langfuse_public_key" {
  type      = string
  sensitive = true
}

variable "langfuse_secret_key" {
  type      = string
  sensitive = true
}

variable "db_password" {
  type      = string
  sensitive = true
}

variable "backend_sa_email" {
  type        = string
  description = "Cloud Run backend service account email (consumes secrets at runtime)."
}

variable "ingest_sa_email" {
  type        = string
  description = "Cloud Run ingest jobs service account email."
}

variable "vm_sa_email" {
  type        = string
  description = "VM service account email (mounts pg password via Secret Manager)."
}
