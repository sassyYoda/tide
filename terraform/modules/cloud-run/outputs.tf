output "backend_url" {
  value       = google_cloud_run_v2_service.backend.uri
  description = "Cloud Run-assigned HTTPS URL of the backend service (e.g. https://tide-backend-<hash>-<region>.a.run.app)."
}

output "backend_name" {
  value       = google_cloud_run_v2_service.backend.name
  description = "Cloud Run service name; used by frontend NEXT_PUBLIC_API_BASE_URL wiring in 06-04+."
}
