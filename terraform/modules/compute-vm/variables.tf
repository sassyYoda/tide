# compute-vm module — e2-micro VM hosting TimescaleDB + Qdrant + Redis (D-03 + L-02).
# Free-tier requires us-east1/west1/central1 AND non-preemptible (see main.tf).

variable "project_id" {
  type        = string
  description = "GCP project hosting the VM."
}

variable "region" {
  type        = string
  description = "Region for the VM (must be us-east1/west1/central1 for the always-free e2-micro)."
}

variable "zone" {
  type        = string
  description = "Zone within region for the VM."
  default     = "us-east1-b"
}

variable "vpc_id" {
  type        = string
  description = "VPC network ID from module.network.vpc_id."
}

variable "subnet_id" {
  type        = string
  description = "Subnet ID from module.network.subnet_id."
}

variable "vm_sa_email" {
  type        = string
  description = "VM service account email from module.iam.vm_sa_email (needs secretAccessor + storage.objectAdmin)."
}

variable "backup_bucket" {
  type        = string
  description = "GCS bucket name for pg_dump snapshots (e.g., tide-mvp-tide-pgdump)."
}

variable "qdrant_bucket" {
  type        = string
  description = "GCS bucket name for Qdrant snapshots."
}

variable "config_bucket" {
  type        = string
  description = "GCS bucket holding the VM-side docker-compose.yml + postgresql.conf (reuses tide-models — no lifecycle delete)."
}
