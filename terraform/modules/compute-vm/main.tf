# compute-vm — e2-micro VM with cloud-init swap + docker-compose stack (D-03, L-02, Pitfall P1).
#
# - machine_type = "e2-micro" + region in us-east1/west1/central1 + non-preemptible
#   == always-free tier (1 per billing account).
# - Cloud-init (metadata.user-data) does ALL host-side setup: 4 GB swap (Pitfall P1),
#   Docker install, gsutil cp the compose+pgconf from a GCS config bucket, systemd
#   unit that runs `docker compose up -d` and gates on a first-boot restore script.
# - Ephemeral public IP is required so the VM can `gsutil cp` from GCS at startup
#   (no Cloud NAT cost; the firewall rules in modules/network block all ingress
#   except VPC-internal Cloud Run + IAP-tunneled SSH).
# - The VM-side docker-compose.yml and postgresql.conf are uploaded to the config
#   bucket as Terraform-managed GCS objects so cloud-init can pull them via gsutil.
#   Changes to either file trigger a fresh upload; `depends_on` on the VM means a
#   subsequent `terraform apply` does not re-create the VM (cloud-init only runs
#   on the first boot; manual re-pull via ssh + re-systemctl is the operator path).

resource "google_storage_bucket_object" "compose" {
  name   = "config/docker-compose.yml"
  bucket = var.config_bucket
  source = "${path.module}/docker-compose.yml"
}

resource "google_storage_bucket_object" "pgconf" {
  name   = "config/postgresql.conf"
  bucket = var.config_bucket
  source = "${path.module}/postgresql.conf"
}

resource "google_compute_instance" "tide_vm" {
  name         = "tide-vm"
  machine_type = "e2-micro" # FREE TIER ONLY in us-west1/east1/central1 (D-03)
  zone         = var.zone
  tags         = ["tide-vm"]

  boot_disk {
    initialize_params {
      image = "projects/debian-cloud/global/images/family/debian-12"
      size  = 30
      type  = "pd-standard"
    }
  }

  network_interface {
    network    = var.vpc_id
    subnetwork = var.subnet_id
    access_config {} # ephemeral public IP for VM -> GCS egress at startup (no Cloud NAT cost)
  }

  service_account {
    email  = var.vm_sa_email
    scopes = ["cloud-platform"]
  }

  metadata = {
    user-data = templatefile("${path.module}/cloud-init.yaml", {
      TIDE_BACKUP_BUCKET = var.backup_bucket
      TIDE_QDRANT_BUCKET = var.qdrant_bucket
      TIDE_CONFIG_BUCKET = var.config_bucket
    })
    enable-oslogin = "TRUE"
  }

  scheduling {
    on_host_maintenance = "MIGRATE"
    automatic_restart   = true
    preemptible         = false # Always-Free requires non-preemptible
  }

  # Recreate the VM if either uploaded config object changes (cloud-init only re-runs on
  # a fresh boot disk; the operator must re-apply or ssh+pull for live config updates).
  depends_on = [
    google_storage_bucket_object.compose,
    google_storage_bucket_object.pgconf,
  ]
}
