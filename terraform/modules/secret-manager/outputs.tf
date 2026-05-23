output "secret_ids" {
  value = { for k, s in google_secret_manager_secret.this : k => s.id }
  # Plan 06-03 wires Cloud Run env vars by name: each.key resolves to the secret_id used
  # in google_cloud_run_v2_service.template.containers.env.value_source.secret_key_ref.
}
