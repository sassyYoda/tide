output "vm_internal_ip" {
  description = "VM private IP within tide-subnet — consumed by 06-03 Cloud Run env vars (REDIS_URL, QDRANT_URL, DATABASE_URL)."
  value       = google_compute_instance.tide_vm.network_interface[0].network_ip
}

output "vm_name" {
  value = google_compute_instance.tide_vm.name
}

output "vm_zone" {
  value = google_compute_instance.tide_vm.zone
}
