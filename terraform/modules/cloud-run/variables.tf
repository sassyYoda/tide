# Shared variables for the cloud-run module. The module file layout:
#   service.tf     — google_cloud_run_v2_service.backend (this plan, 06-03)
#   job-*.tf       — google_cloud_run_v2_job.{ingest,...} (06-04)
# A single variables.tf keeps inputs DRY across both sub-files.

variable "project_id" {
  type        = string
  description = "GCP project ID."
}

variable "region" {
  type        = string
  description = "GCP region (matches Artifact Registry repo region for the image)."
}

variable "vpc_id" {
  type        = string
  description = "VPC self-link/ID from modules/network for Direct VPC Egress (Pitfall P5)."
}

variable "subnet_id" {
  type        = string
  description = "Subnet self-link/ID from modules/network. Cloud Run egresses via this subnet."
}

variable "backend_sa_email" {
  type        = string
  description = "Service account email used by the Cloud Run backend service (consumes secrets, calls VM)."
}

variable "ingest_sa_email" {
  type        = string
  description = "Service account email used by Cloud Run ingest jobs (declared here for 06-04 job-*.tf usage)."
}

variable "scheduler_sa_email" {
  type        = string
  default     = null
  description = "Cloud Scheduler SA email; wired by 06-04 when the scheduler module is enabled."
}

variable "image_tag" {
  type        = string
  default     = "latest"
  description = "Container image tag. CI passes github.sha to enforce reproducibility (Pitfall P7); the `latest` default is only safe for first-time `terraform plan` runs before CI publishes a digest."
}

variable "secret_ids" {
  type        = map(string)
  description = "Map of secret_id values keyed by short-name, from modules/secret-manager.secret_ids. Used by secret_key_ref blocks."
}

variable "vm_internal_ip" {
  type        = string
  description = "Internal IP of the postgres/redis/qdrant VM (from modules/compute-vm.vm_internal_ip in 06-02). Wired here as TIDE_VM_INTERNAL_IP env for upstream health checks."
}
