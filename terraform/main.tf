# Pitfall P4 reminder: NEVER use google_sql_database_instance for TimescaleDB.
# Cloud SQL does not support the timescaledb extension. The database runs on the
# e2-micro VM defined in modules/compute-vm (wired in plan 06-02).

# Pitfall P5 reminder: NEVER declare a google_vpc_access_connector.
# Cloud Run uses Direct VPC Egress via vpc_access.network_interfaces in modules/cloud-run
# (wired in plan 06-03). The serverless VPC Access connector saves ~$25/mo and is the
# locked decision per CLAUDE.md.

variable "project_id" {
  type = string
}
variable "region" {
  type    = string
  default = "us-east1"
}
variable "github_repo" {
  type    = string
  default = "X-commando/tide"
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
variable "image_tag" {
  type    = string
  default = "latest" # CI overrides with github.sha (Pitfall P7)
}

module "network" {
  source = "./modules/network"
  region = var.region
}

module "iam" {
  source      = "./modules/iam"
  project_id  = var.project_id
  github_repo = var.github_repo
}

module "secret_manager" {
  source              = "./modules/secret-manager"
  project_id          = var.project_id
  openai_api_key      = var.openai_api_key
  anthropic_api_key   = var.anthropic_api_key
  langfuse_public_key = var.langfuse_public_key
  langfuse_secret_key = var.langfuse_secret_key
  db_password         = var.db_password
  backend_sa_email    = module.iam.cloudrun_backend_sa_email
  ingest_sa_email     = module.iam.cloudrun_ingest_sa_email
  vm_sa_email         = module.iam.vm_sa_email
}

module "gcs" {
  source           = "./modules/gcs"
  project_id       = var.project_id
  region           = var.region
  vm_sa_email      = module.iam.vm_sa_email
  backend_sa_email = module.iam.cloudrun_backend_sa_email
  ingest_sa_email  = module.iam.cloudrun_ingest_sa_email
}
