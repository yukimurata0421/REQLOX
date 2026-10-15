data "google_project" "target" {
  project_id = var.project_id
}

locals {
  labels         = { application = "reqlox", managed_by = "terraform", purpose = "bounded-demo" }
  release_sha256 = filesha256(var.release_archive)
  bucket_name    = "${var.project_id}-${var.name}-releases"
  runtime = jsonencode({
    project_id          = var.project_id, project_number = data.google_project.target.number,
    host_id             = var.name, release_sha256 = local.release_sha256,
    artifact_bucket     = local.bucket_name, artifact_object = "releases/${local.release_sha256}.tar.gz",
    jev_secret_resource = "projects/${var.project_id}/secrets/reqlox-jev-api-key/versions/${var.jev_secret_version}",
    lease_seconds       = var.lease_seconds, application_port = 8765,
    access              = "IAP_TCP_ONLY", paid_model_calls_enabled = false,
    data_disk           = "${var.name}-state", database_backend = "SQLITE"
  })
}

resource "google_project_service" "required" {
  for_each = toset([
    "compute.googleapis.com", "iam.googleapis.com", "iap.googleapis.com",
    "secretmanager.googleapis.com", "storage.googleapis.com", "billingbudgets.googleapis.com", "pubsub.googleapis.com",
    "cloudresourcemanager.googleapis.com", "serviceusage.googleapis.com"
  ])
  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}

resource "google_service_account" "runtime" {
  account_id   = "${var.name}-runtime"
  display_name = "REQLOX bounded demo runtime"
  depends_on   = [google_project_service.required]
}

resource "google_compute_network" "demo" {
  name                    = var.name
  auto_create_subnetworks = false
  depends_on              = [google_project_service.required]
}

resource "google_compute_subnetwork" "demo" {
  name                     = var.name
  region                   = var.region
  network                  = google_compute_network.demo.id
  ip_cidr_range            = "10.82.0.0/24"
  private_ip_google_access = true
}

resource "google_compute_firewall" "iap" {
  name                    = "${var.name}-iap-ui"
  network                 = google_compute_network.demo.name
  direction               = "INGRESS"
  source_ranges           = ["35.235.240.0/20"]
  target_service_accounts = [google_service_account.runtime.email]
  allow {
    protocol = "tcp"
    ports    = ["8080"]
  }
}

resource "google_storage_bucket" "releases" {
  name                        = local.bucket_name
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels                      = local.labels
  versioning {
    enabled = true
  }
  depends_on = [google_project_service.required]
}

resource "google_storage_bucket_object" "release" {
  for_each = merge(var.retained_release_archives, { (local.release_sha256) = var.release_archive })
  name     = "releases/${each.key}.tar.gz"
  bucket   = google_storage_bucket.releases.name
  source   = each.value
}

resource "google_storage_bucket_iam_member" "runtime_read" {
  bucket = google_storage_bucket.releases.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_secret_manager_secret" "jev" {
  secret_id = "reqlox-jev-api-key"
  labels    = local.labels
  replication {
    auto {}
  }
  lifecycle {
    prevent_destroy = true
  }
  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_iam_member" "runtime_read" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.jev.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

# This budget reports delayed billing estimates; the VM lease is a separate bound.
# Disable automatic recipients: notification delivery is outside this deployment.
resource "google_pubsub_topic" "budget" {
  name       = "${var.name}-budget"
  labels     = local.labels
  depends_on = [google_project_service.required]
}

resource "google_billing_budget" "demo" {
  billing_account = var.billing_account_id
  display_name    = "REQLOX bounded demo"
  budget_filter {
    projects               = ["projects/${data.google_project.target.number}"]
    credit_types_treatment = "EXCLUDE_ALL_CREDITS"
    calendar_period        = "MONTH"
  }
  amount {
    specified_amount {
      currency_code = "JPY"
      units         = tostring(var.budget_jpy)
    }
  }
  all_updates_rule {
    disable_default_iam_recipients = true
    pubsub_topic                   = google_pubsub_topic.budget.id
    schema_version                 = "1.0"
  }
  # The Budget API grants its publisher access using the caller's permission.
  depends_on = [google_pubsub_topic.budget]
}

resource "google_compute_disk" "state" {
  name   = "${var.name}-state"
  type   = "pd-standard"
  zone   = var.zone
  size   = 10
  labels = local.labels
  lifecycle {
    prevent_destroy = true
  }
  depends_on = [google_project_service.required]
}

resource "google_compute_instance" "demo" {
  count        = var.deploy_runtime ? 1 : 0
  name         = var.name
  machine_type = var.machine_type
  zone         = var.zone
  labels       = local.labels
  boot_disk {
    auto_delete = true
    initialize_params {
      image = var.image
      size  = 15
      type  = "pd-standard"
    }
  }
  attached_disk {
    source      = google_compute_disk.state.id
    device_name = "reqlox-state"
  }
  network_interface {
    subnetwork = google_compute_subnetwork.demo.id
    # Outbound package/provider HTTPS; ingress is restricted to IAP by the VPC.
    access_config {
      network_tier = "STANDARD"
    }
  }
  service_account {
    email  = google_service_account.runtime.email
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }
  scheduling {
    automatic_restart           = false
    on_host_maintenance         = "MIGRATE"
    instance_termination_action = "STOP"
    max_run_duration {
      seconds = var.lease_seconds
    }
  }
  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }
  metadata = {
    enable-oslogin           = "TRUE"
    block-project-ssh-keys   = "TRUE"
    disable-legacy-endpoints = "TRUE"
    reqlox-runtime           = local.runtime
    reqlox-release-sha256    = local.release_sha256
  }
  metadata_startup_script = templatefile("${path.module}/startup.sh.tftpl", {
    bootstrap_b64 = filebase64("${path.module}/runtime_bootstrap.py")
    context_b64   = filebase64("${path.module}/host_context.py")
  })
  lifecycle {
    precondition {
      condition     = var.jev_secret_version != ""
      error_message = "Register a secret version outside Terraform state before starting the VM."
    }
  }
  depends_on = [google_storage_bucket_object.release, google_storage_bucket_iam_member.runtime_read,
  google_secret_manager_secret_iam_member.runtime_read, google_compute_firewall.iap]
}

resource "google_iap_tunnel_instance_iam_member" "access" {
  for_each = var.deploy_runtime ? var.iap_members : toset([])
  project  = var.project_id
  zone     = var.zone
  instance = google_compute_instance.demo[0].name
  role     = "roles/iap.tunnelResourceAccessor"
  member   = each.value
  condition {
    title      = "reqlox-ui-only"
    expression = "destination.port == 8080"
  }
  lifecycle {
    replace_triggered_by = [google_compute_instance.demo[0]]
  }
}
