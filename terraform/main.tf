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

# Wave 1, plan 06-02 — e2-micro VM hosting TimescaleDB + Qdrant + Redis (D-03 + L-02).
# Strict mem_limits + 4 GB swap (Pitfall P1) enforced inside the module.
# config_bucket reuses tide-models (no-lifecycle) so the uploaded docker-compose.yml
# and postgresql.conf survive long enough for cloud-init to gsutil cp them.
module "compute_vm" {
  source        = "./modules/compute-vm"
  project_id    = var.project_id
  region        = var.region
  vpc_id        = module.network.vpc_id
  subnet_id     = module.network.subnet_id
  vm_sa_email   = module.iam.vm_sa_email
  backup_bucket = module.gcs.bucket_names["tide-pgdump"]
  qdrant_bucket = module.gcs.bucket_names["tide-qdrant"]
  config_bucket = module.gcs.bucket_names["tide-models"]
}

# Wave 2 — plan 06-03 declared the backend Cloud Run service; plan 06-04 adds
# the 3 ingest Jobs + Cloud Scheduler triggers (NOAA */15, Open-Meteo */30,
# solunar 0 * * * *). Both live in the same `cloud-run` module so they share
# variables.tf and the worker/backend image-tag input.
module "cloud_run" {
  source             = "./modules/cloud-run"
  project_id         = var.project_id
  region             = var.region
  vpc_id             = module.network.vpc_id
  subnet_id          = module.network.subnet_id
  backend_sa_email   = module.iam.cloudrun_backend_sa_email
  ingest_sa_email    = module.iam.cloudrun_ingest_sa_email
  scheduler_sa_email = module.iam.scheduler_sa_email
  image_tag          = var.image_tag
  secret_ids         = module.secret_manager.secret_ids
  vm_internal_ip     = module.compute_vm.vm_internal_ip
}
