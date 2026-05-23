output "vpc_id" {
  value = google_compute_network.tide.id
}

output "subnet_id" {
  value = google_compute_subnetwork.tide.id
}

output "vpc_name" {
  value = google_compute_network.tide.name
}
