resource "google_compute_network" "tide" {
  name                    = "tide-vpc"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "tide" {
  name                     = "tide-subnet"
  ip_cidr_range            = "10.0.0.0/24"
  region                   = var.region
  network                  = google_compute_network.tide.id
  private_ip_google_access = true
}

resource "google_compute_firewall" "allow_cloudrun_to_vm" {
  name          = "tide-allow-cloudrun-to-vm"
  network       = google_compute_network.tide.name
  direction     = "INGRESS"
  source_ranges = [google_compute_subnetwork.tide.ip_cidr_range]
  target_tags   = ["tide-vm"]
  allow {
    protocol = "tcp"
    ports    = ["5432", "6333", "6334", "6379"]
  }
}

resource "google_compute_firewall" "allow_ssh_iap" {
  # IAP-tunneled SSH for emergency VM access (still no public IP needed)
  name          = "tide-allow-ssh-iap"
  network       = google_compute_network.tide.name
  direction     = "INGRESS"
  source_ranges = ["35.235.240.0/20"] # IAP CIDR per gcloud docs
  target_tags   = ["tide-vm"]
  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}
