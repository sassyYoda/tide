variable "project_id" {
  type        = string
  description = "GCP project ID for project-level IAM bindings."
}

variable "github_repo" {
  type        = string
  description = "GitHub repo (owner/name) restricted by the WIF provider attribute_condition."
}
