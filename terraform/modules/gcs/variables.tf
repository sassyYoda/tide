variable "project_id" {
  type        = string
  description = "GCP project ID (prefixes bucket names to keep them globally unique)."
}

variable "region" {
  type        = string
  description = "Bucket location (regional, e.g. us-east1)."
}

variable "vm_sa_email" {
  type        = string
  description = "VM service account email — granted storage.objectAdmin on all 4 buckets (writes pg_dump + model artifacts)."
}

variable "backend_sa_email" {
  type        = string
  description = "Cloud Run backend service account email — granted storage.objectViewer (reads model artifacts)."
}

variable "ingest_sa_email" {
  type        = string
  description = "Cloud Run ingest job service account email — granted storage.objectAdmin (writes raw NOAA dumps + qdrant snapshots)."
}
